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
    create_knowledge_gateway_mcp_server,
)
from agent_app.session import AgentCoreMemorySession


# AgentCore標準loggerのchildを使い、Runtimeのlogging設定後も安全な障害分類を残す。
logger = logging.getLogger("bedrock_agentcore.app.agent_app.service")


class StreamingRunResult(Protocol):
    def stream_events(self) -> AsyncIterator[Any]: ...


class StreamingRunner(Protocol):
    def run_streamed(self, starting_agent: Agent, **kwargs: Any) -> StreamingRunResult: ...


class GatewayMCPServer(Protocol):
    async def connect(self) -> None: ...

    async def list_tools(self, *args: Any, **kwargs: Any) -> list[Any]: ...

    async def cleanup(self) -> None: ...


MCPServerFactory = Callable[[AppConfig], GatewayMCPServer]
AgentFactory = Callable[
    [
        Model,
        Sequence[GatewayMCPServer],
        bool,
        Sequence[GatewayMCPServer],
        bool,
    ],
    AgentBundle,
]


class MCPCleanupError(RuntimeError):
    """MCP接続を有限時間内に安全に解放できなかった状態。"""


async def stream_agent_response(
    *,
    config: AppConfig,
    model: Model,
    prompt: str,
    session: AgentCoreMemorySession,
    weather_mcp_server_factory: MCPServerFactory = create_gateway_mcp_server,
    knowledge_mcp_server_factory: MCPServerFactory = create_knowledge_gateway_mcp_server,
    agent_factory: AgentFactory = create_agents,
    runner: StreamingRunner = Runner,
) -> AsyncIterator[StreamEvent]:
    """cleanup、Memory commit、completedの順を守って一つのturnを実行する。"""

    active_servers: list[GatewayMCPServer] = []
    cleanup_attempted: set[int] = set()

    async def cleanup_server(server: GatewayMCPServer) -> None:
        """一つのserverを有限時間で解放し、二重cleanupを防ぐ。"""

        server_id = id(server)
        if server_id in cleanup_attempted:
            return
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
            cleanup_attempted.add(server_id)
            raise MCPCleanupError() from exc
        else:
            cleanup_attempted.add(server_id)
            if server in active_servers:
                active_servers.remove(server)

    async def cleanup_all_servers() -> None:
        """接続と逆順に全serverのcleanupを試行してから成否を返す。"""

        first_error: MCPCleanupError | None = None
        for server in reversed(tuple(active_servers)):
            try:
                await cleanup_server(server)
            except asyncio.CancelledError:
                raise
            except MCPCleanupError as exc:
                # 一つの失敗で残りの接続を放置せず、全resourceの解放を試みる。
                first_error = first_error or exc
        if first_error is not None:
            raise first_error

    async def prepare_gateway(
        factory: MCPServerFactory,
        *,
        gateway_kind: str,
    ) -> GatewayMCPServer | None:
        """Gateway一系統のfactory、connect、Tool検証を独立して完結する。"""

        try:
            server = factory(config)
        except Exception:
            logger.warning(
                "Gateway Toolを利用不能として継続します: kind=%s stage=factory",
                gateway_kind,
            )
            return None

        active_servers.append(server)
        try:
            async with asyncio.timeout(MCP_TRANSPORT_TIMEOUT_SECONDS):
                await server.connect()
            async with asyncio.timeout(MCP_CLIENT_SESSION_TIMEOUT_SECONDS):
                await server.list_tools()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Gateway Toolを利用不能として継続します: kind=%s stage=connect_or_list",
                gateway_kind,
            )
            # 部分接続を解放できた場合だけ、この経路を利用不能として継続する。
            await cleanup_server(server)
            return None
        return server

    try:
        # 一方のfactory／接続障害を他方へ波及させず、利用可否を別々に確定する。
        weather_server = await prepare_gateway(
            weather_mcp_server_factory, gateway_kind="weather"
        )
        knowledge_server = await prepare_gateway(
            knowledge_mcp_server_factory, gateway_kind="knowledge"
        )
        weather_servers = [weather_server] if weather_server is not None else []
        knowledge_servers = [knowledge_server] if knowledge_server is not None else []
        bundle = agent_factory(
            model,
            weather_servers,
            weather_server is not None,
            knowledge_servers,
            knowledge_server is not None,
        )
        result = runner.run_streamed(bundle.manager, input=prompt, session=session)
        async for event in result.stream_events():
            # Tool呼び出しなどのSDK内部eventは公開せず、利用者向けテキスト差分だけを中継する。
            if getattr(event, "type", None) != "raw_response_event":
                continue
            data = getattr(event, "data", None)
            if isinstance(data, ResponseTextDeltaEvent) and data.delta:
                yield text_delta_event(data.delta)

        # 接続解放前のturnをMemoryへ確定せず、cleanup→commit→completedを固定する。
        await cleanup_all_servers()
        await session.commit()
        yield completed_event()
    except asyncio.CancelledError:
        # 切断時も同じtaskでcleanupとrollbackをbest-effort実行し、元のcancelを再送出する。
        try:
            await cleanup_all_servers()
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
            await cleanup_all_servers()
        except BaseException:
            pass
        try:
            await session.rollback()
        except BaseException:
            pass
        yield error_event()
