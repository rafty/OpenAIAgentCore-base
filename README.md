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

このPoCは、OpenAI Agents SDKのManager、Weather、AWS Knowledge AgentをAmazon Bedrock AgentCore Runtimeで実行します。Managerが会話と最終回答を所有し、Weather AgentとAWS Knowledge AgentをAgent-as-Toolとして必要に応じて利用します。

Weather AgentはWeather専用GatewayのLambdaターゲットから固定モックの`get_weather`／`get_time`だけを利用します。AWS Knowledge Agentは別のKnowledge専用GatewayからManaged Knowledge Baseの`Retrieve`だけを利用し、`knowledge-base-s3/`の5文書を根拠として社内AWS標準、見積基準、過去案件へ回答します。一方のGateway障害を他方へ波及させず、検索結果が空の状態と取得不能を区別します。

- Agent構成、MCP接続、HTTP／SSE／Memory契約、コンテナおよびRuntime検証: [Agentドキュメント](docs/Agent/README.md)
- 2 Gateway、Managed Knowledge Base、Data Source、初回同期、IAM境界およびCDK検証: [CDKドキュメント](docs/CDK/README.md)
- `us-east-1`のデプロイ済みAgentを実際に呼び出す手順とテストケース: [手動テストガイド](docs/ManualTesting/README.md)

主要なローカル検証コマンドは次のとおりです。

```bash
uv lock --check
uv run pytest
uv run python app.py
docker build --platform linux/arm64 -t openai-agentcore-poc:local agents
```

PoC全体のデプロイ先は`us-east-1`です。初回`cdk diff`より前に、対象profileとaccountを確認して同リージョンをCDK bootstrapします。`uv run python app.py`とテストはAWSへ書き込みませんが、bootstrap、`cdk diff`、`cdk deploy`、初回ingestion job、Runtime／GatewayのAWS E2E、旧`us-east-2` stackの削除はAWS環境と料金へ影響します。実施順序と削除ゲートは[CDKドキュメント](docs/CDK/README.md)に従ってください。
