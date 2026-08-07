# 仕様駆動開発(SDD) ガイド

このプロジェクトでは、Amazon Bedrock AgentCoreを複数人で開発するために、仕様駆動開発（SDD / Spec-Driven Development）を採用しています。

実装前に仕様、実装計画、実装タスクを段階的に整理し、要件単位のブランチとPull Requestでレビュー可能な状態を保ちながら開発を進めます。

SDDの基本方針、具体的な実施手順、共同開発のルールは、次のドキュメントを参照してください。

- [SDDガイド](docs/SDD/README.md)
- [SDDの実施手順](docs/SDD/workflow.md)
- [SDD共同開発ルール](docs/SDD/team-development.md)

# AWS CDK Pythonプロジェクト

このプロジェクトは、Pythonで開発し、[uv](https://docs.astral.sh/uv/)で依存関係を管理するAWS CDKプロジェクトです。

`cdk.json`には、AWS CDK ToolkitがCDKアプリケーションをどのように実行するかを定義します。

このプロジェクトでは、CDKアプリケーションを`uv`経由で実行するように設定しています。

[docs/CDK/README.md](docs/CDK/README.md)

## AgentCore Runtime PoC

このPoCは、OpenAI Agents SDKのマネージャーAgentとWeather AgentをAmazon Bedrock AgentCore Runtimeで実行します。マネージャーAgentが会話と最終回答を所有し、Weather Agentだけが専用のAgentCore GatewayへSigV4で接続して、Lambdaターゲットの`get_weather`と`get_time`を利用します。

Weather／Time Toolは接続確認用の固定モックだけを返し、現在の実天気や実時刻を取得しません。GatewayまたはToolを利用できない場合も、両Agentは値を推測せず取得不能を案内します。

- Agent構成、MCP接続、HTTP／SSE／Memory契約、コンテナおよびRuntime検証: [Agentドキュメント](docs/Agent/README.md)
- Gateway、GatewayTarget、Lambda、IAM境界およびCDK検証: [CDKドキュメント](docs/CDK/README.md)

主要なローカル検証コマンドは次のとおりです。

```bash
uv lock --check
uv run pytest
uv run python app.py
docker build --platform linux/arm64 -t openai-agentcore-poc:local agents
```
