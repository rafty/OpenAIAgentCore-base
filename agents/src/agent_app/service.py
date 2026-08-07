"""MCP、Agent、Sessionのストリーミング実行と確定順序を制御する。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any, Protocol

from agents import Agent, Model, Runner
from openai.types.responses import ResponseTextDeltaEvent

from agent_app.agent_factory import AgentBundle, create_agents
from agent_app.config import AppConfig
from agent_app.contracts import StreamEvent, completed_event, error_event, text_delta_event
from agent_app.gateway_tools import (
    MCP_CLEANUP_TIMEOUT_SECONDS,
    MCP_CLIENT_SESSION_TIMEOUT_SECONDS,
    MCP_TRANSPORT_TIMEOUT_SECONDS,
    create_gateway_mcp_server,
)
from agent_app.session import AgentCoreMemorySession


logger = logging.getLogger(__name__)


class StreamingRunResult(Protocol):
    def stream_events(self) -> AsyncIterator[Any]: ...


class StreamingRunner(Protocol):
    def run_streamed(self, starting_agent: Agent, **kwargs: Any) -> StreamingRunResult: ...


class GatewayMCPServer(Protocol):
    async def connect(self) -> None: ...

    async def list_tools(self, *args: Any, **kwargs: Any) -> list[Any]: ...

    async def cleanup(self) -> None: ...


MCPServerFactory = Callable[[AppConfig], GatewayMCPServer]
AgentFactory = Callable[[Model, Sequence[GatewayMCPServer], bool], AgentBundle]


class MCPCleanupError(RuntimeError):
    """MCP接続を有限時間内に安全に解放できなかった状態。"""


async def stream_agent_response(
    *,
    config: AppConfig,
    model: Model,
    prompt: str,
    session: AgentCoreMemorySession,
    mcp_server_factory: MCPServerFactory = create_gateway_mcp_server,
    agent_factory: AgentFactory = create_agents,
    runner: StreamingRunner = Runner,
) -> AsyncIterator[StreamEvent]:
    """cleanup、Memory commit、completedの順を守って一つのturnを実行する。"""

    active_server: GatewayMCPServer | None = None
    cleanup_attempted = False

    async def cleanup_active_server() -> None:
        """cleanupを有限時間で行い、キャンセル中断時だけ同一taskで再試行可能にする。"""

        nonlocal active_server, cleanup_attempted
        if active_server is None or cleanup_attempted:
            return
        server = active_server
        try:
            # asyncio.timeoutは現在taskのまま期限を設け、connectとcleanupを別taskへ
            # 分離してanyioのcancel scopeを壊すasyncio.wait_forを避ける。
            async with asyncio.timeout(MCP_CLEANUP_TIMEOUT_SECONDS):
                await server.cleanup()
        except asyncio.CancelledError:
            # 外部キャンセルでcleanup自体が中断された場合は接続参照を保持し、外側の
            # cancel handlerが同じtaskで有限時間cleanupを再試行できるようにする。
            raise
        except Exception as exc:
            # 通常の失敗とtimeoutはterminalなcleanup失敗として二重試行を防ぐ。
            cleanup_attempted = True
            raise MCPCleanupError() from exc
        else:
            # 正常終了後にだけactive状態を不可逆に外す。
            cleanup_attempted = True
            active_server = None

    try:
        gateway_available = False
        try:
            active_server = mcp_server_factory(config)
        except Exception:
            # factory段階では接続resourceが存在しないため、安全な取得不能Agentへ移行できる。
            logger.warning("Gateway Toolを利用不能として継続します: stage=factory")
        else:
            try:
                async with asyncio.timeout(MCP_TRANSPORT_TIMEOUT_SECONDS):
                    await active_server.connect()
                async with asyncio.timeout(MCP_CLIENT_SESSION_TIMEOUT_SECONDS):
                    await active_server.list_tools()
                gateway_available = True
            except asyncio.CancelledError:
                raise
            except Exception:
                # 部分接続を解放できた場合だけ、MCPなしの安全なAgentへfallbackする。
                logger.warning("Gateway Toolを利用不能として継続します: stage=connect_or_list")
                await cleanup_active_server()

        # Gateway利用可否を確定してからAgentを生成し、ManagerへMCPを直接渡さない。
        servers = [active_server] if gateway_available and active_server is not None else []
        bundle = agent_factory(model, servers, gateway_available)
        result = runner.run_streamed(bundle.manager, input=prompt, session=session)
        async for event in result.stream_events():
            # Tool呼び出しなどのSDK内部eventは公開せず、利用者向けテキスト差分だけを中継する。
            if getattr(event, "type", None) != "raw_response_event":
                continue
            data = getattr(event, "data", None)
            if isinstance(data, ResponseTextDeltaEvent) and data.delta:
                yield text_delta_event(data.delta)

        # 接続解放前のturnをMemoryへ確定せず、cleanup→commit→completedを固定する。
        await cleanup_active_server()
        await session.commit()
        yield completed_event()
    except asyncio.CancelledError:
        # 切断時も同じtaskでcleanupとrollbackをbest-effort実行し、元のcancelを再送出する。
        try:
            await cleanup_active_server()
        except BaseException:
            pass
        try:
            await session.rollback()
        except BaseException:
            pass
        raise
    except Exception:
        # 例外本文やendpointを記録せず、障害分類だけを運用ログへ残す。
        logger.warning("Agent turnをfail-closedで終了します: stage=runtime")
        try:
            await cleanup_active_server()
        except BaseException:
            pass
        try:
            await session.rollback()
        except BaseException:
            pass
        yield error_event()
