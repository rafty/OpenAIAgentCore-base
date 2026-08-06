"""Agentのストリーミング実行とSession確定順序を制御する。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Protocol

from agents import Agent, Runner
from openai.types.responses import ResponseTextDeltaEvent

from agent_app.contracts import StreamEvent, completed_event, error_event, text_delta_event
from agent_app.session import AgentCoreMemorySession


class StreamingRunResult(Protocol):
    def stream_events(self) -> AsyncIterator[Any]: ...


class StreamingRunner(Protocol):
    def run_streamed(self, starting_agent: Agent, **kwargs: Any) -> StreamingRunResult: ...


async def stream_agent_response(
    *,
    manager_agent: Agent,
    prompt: str,
    session: AgentCoreMemorySession,
    runner: StreamingRunner = Runner,
) -> AsyncIterator[StreamEvent]:
    """全SDK eventとMemory commitが完了した後だけcompletedを返す。"""

    try:
        result = runner.run_streamed(manager_agent, input=prompt, session=session)
        async for event in result.stream_events():
            # Tool呼び出しなどのSDK内部eventは公開せず、利用者向けテキスト差分だけを中継する。
            if getattr(event, "type", None) != "raw_response_event":
                continue
            data = getattr(event, "data", None)
            if isinstance(data, ResponseTextDeltaEvent) and data.delta:
                yield text_delta_event(data.delta)

        # 全event消費とMemory確定の両方が成功した場合にだけ完了を通知する。
        await session.commit()
        yield completed_event()
    except asyncio.CancelledError:
        # クライアント切断は通常エラーへ変換せず、未確定履歴を破棄してキャンセルを伝播する。
        await session.rollback()
        raise
    except Exception:
        try:
            await session.rollback()
        except Exception:
            # rollbackは未確定bufferのbest-effort破棄。内部例外は応答へ出さない。
            pass
        yield error_event()
