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

このPoCは、OpenAI Agents SDKのManager、Weather、AWS Knowledge、Estimation AgentをAmazon Bedrock AgentCore Runtimeで実行します。Managerが会話と最終回答を所有し、3つの専門AgentをAgent-as-Toolとして必要に応じて利用します。

Weather AgentはWeather専用GatewayのLambdaターゲットから固定モックの`get_weather`／`get_time`だけを利用します。AWS Knowledge Agentは別のKnowledge専用GatewayからManaged Knowledge Baseの`Retrieve`だけを利用し、`knowledge-base-s3/`の5文書を根拠として社内AWS標準、見積基準、過去案件へ回答します。一方のGateway障害を他方へ波及させず、検索結果が空の状態と取得不能を区別します。

Estimation Agentは3つ目の専用Gatewayに公開された4つの業務Toolだけを使い、DynamoDBの架空の類似案件、標準工数、単価、価格ポリシーからAWS構築見積をpreviewまたは明示保存します。Sample Dataの正本は`dynamodb-seed/`で管理し、`search_summary`だけをAmazon BedrockのCohere Embed Multilingual v3で実行時にEmbeddingします。類似案件0件でも標準マスターだけで継続し、汎用DB操作や自動Seedは提供しません。

- Agent構成、MCP接続、Estimationの保存意図、HTTP／SSE／Memory契約、コンテナおよびRuntime検証: [Agentドキュメント](docs/Agent/README.md)
- 3 Gateway、Managed Knowledge Base、DynamoDB Vector Index、Custom Resource、IAM境界およびCDK検証: [CDKドキュメント](docs/CDK/README.md)
- DynamoDBの架空案件・マスター・利用時入力・評価ケース: [Estimation Sample Data](dynamodb-seed/README.md)
- `us-east-1`のデプロイ済みAgentを実際に呼び出す手順とテストケース: [手動テストガイド](docs/ManualTesting/README.md)
- 設計判断: [Embedding](docs/ADR/adr-0007-use-bedrock-cohere-multilingual-embeddings-for-dynamodb-vector-search.md)、[Vector Index管理](docs/ADR/adr-0008-manage-dynamodb-vector-index-with-custom-resource-provider.md)、[単一テーブルとopaque ref](docs/ADR/adr-0009-use-single-table-and-opaque-context-for-estimation.md)、[GatewayとIAM分離](docs/ADR/adr-0010-use-single-estimation-gateway-target-with-separated-iam.md)

主要なローカル検証コマンドは次のとおりです。

```bash
uv lock --check
uv run pytest
uv run python app.py
docker build --platform linux/arm64 -t openai-agentcore-poc:local agents
```

PoC全体のデプロイ先は`us-east-1`です。初回`cdk diff`より前に、対象profileとaccountを確認して同リージョンをCDK bootstrapします。`uv run python app.py`とテストはAWSへ書き込みませんが、bootstrap、`cdk diff`、`cdk deploy`、初回ingestion job、Runtime／GatewayのAWS E2E、旧`us-east-2` stackの削除はAWS環境と料金へ影響します。実施順序と削除ゲートは[CDKドキュメント](docs/CDK/README.md)に従ってください。
