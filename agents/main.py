"""AgentCore Runtimeコンテナの起動entrypoint。"""

from agents import set_tracing_disabled

from agent_app.runtime import create_runtime_app


def main() -> None:
    """トレースを無効化してAgentCore標準HTTP serverを起動する。"""

    # アプリ生成より先に無効化し、初期化中のSDK処理もトレース対象にしない。
    set_tracing_disabled(True)
    app = create_runtime_app()
    app.run(port=8080)


if __name__ == "__main__":
    main()
