"""実AWS接続なしで本番Runtime factoryを起動するコンテナ契約ハーネス。"""

import os

from agent_app.config import AppConfig
from agent_app.runtime import create_runtime_app


def create_harness_app():
    """本番HTTP境界へ決定的な依存だけを注入した検証用アプリを返す。"""

    mode = os.environ.get("CONTAINER_TEST_MODE", "success")

    async def stream_service(**kwargs):
        # 実モデルやAWSを使わず、コンテナ内で正常・異常SSEだけを再現する。
        yield {"type": "text_delta", "delta": "container"}
        if mode == "error":
            yield {"type": "error", "message": "処理中にエラーが発生しました。"}
            return
        yield {"type": "completed"}

    return create_runtime_app(
        config=AppConfig("us-east-2", "openai.gpt-5.5", "test-memory", "1"),
        manager_agent=object(),
        session_factory=lambda config, invocation: object(),
        stream_service=stream_service,
    )


def main() -> None:
    create_harness_app().run(port=8080)


if __name__ == "__main__":
    main()
