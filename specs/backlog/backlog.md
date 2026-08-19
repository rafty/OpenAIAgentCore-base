# AgentCoreのローカルデバッグの検討

- 2026.08.06
- 作成者: rafty
- ビルドしたAgentのコンテナをAWSにデプロイしてデバッグする前に、ローカル環境でAgentをデバッグする検討をする。
- AgentのToolにおけるDBなどはAWSリソースを使い、AgentのPythonコードをローカルデバッグする方法を検討する。

# Agent実行のデバッグ

- Bedrock上のAgentのデバッグができるようにログなどを整備する。
- Amazon Bedrock AgentCore のオブザーバビリティが適切ならそれを対応する。

---

# Amazon Bedrock Managed Knowledge Base

- Bedrock Managed Knowledge BaseをRAGサービスとして利用する。
- S3にドキュメントを配置する
- S3のネイティブコネクターを使用する

## AgenticRetrieveStreamの対応

AgentCore GatewayのManaged Knowledge Base Connectorには、 Retrieve、 AgenticRetrieveStream があります。
AWSの現在のドキュメントでは、Retrieve は単一検索、AgenticRetrieveStream は複数ステップのagentic retrievalとして説明されています。
https://docs.aws.amazon.com/ja_jp/bedrock-agentcore/latest/devguide/gateway-add-target-api-target-config.html

最初は、
```
AWS Knowledge Agent
    ↓
Retrieve
    ↓
関連chunk取得
    ↓
Knowledge AgentのLLMで回答生成
```
がよいと思います。
これなら、 S3文書が正しくIngestionされたか Embeddingされたか 検索クエリが正しいか どのchunkが返ったか
Agentが取得結果から回答できたか Managerが正しくAWS Knowledge Agentを選択したか を比較的切り分けやすくなります。
その後、
```
Retrieve
        ↓
AgenticRetrieveStream
```
へ進めれば、「普通のRAG」と「Agentic RAG」の違いもPoCできます。

# SQLでDBに問い合わせするAgent & MCP?サーバ
- 見積もり用DBにSQLで問い合わせするAgent & MCP?サーバを実装する。

---

# Amazon Bedrock AgentCore のオブザーバビリティ

- 2026.08.05
- 作成者: rafty
CloudWatch Logsへの独自出力だけで完結させず、Amazon Bedrock AgentCore Observabilityを利用する予定。

## 質問
- `final_output`や`last_agent.name`などをログとして出力したいが、AgentCore ObservabilityまたはCloudWatch Logsのどこへ出力されるか。

---

# AgentCore RuntimeのMMDSv2確認と条件付き対応

- 2026.08.05
- 作成者: rafty
- AgentCore Runtimeのデプロイ後に`GetAgentRuntime`を実行し、`metadataConfiguration.requireMMDSV2`が`true`であることを確認する。
- `requireMMDSV2`が`true`の場合は、追加対応を行わない。
- `requireMMDSV2`が未設定、`null`、または`false`の場合は、まず利用中のCloudFormationおよびAWS CDKが作成時の明示指定に対応していないか再確認する。
- 標準のCloudFormationまたはAWS CDKで有効化できない場合に限り、`UpdateAgentRuntime`で`metadataConfiguration.requireMMDSV2=true`を設定するCDKカスタムリソースを追加する。
- カスタムリソースを追加する場合は、Runtimeの更新時に必要な他プロパティの引き継ぎ、標準リソースとの更新競合、再実行時の冪等性、失敗時の復旧、削除時の挙動を検証する。
- CloudFormationまたはAWS CDKがMMDSv2の設定を正式サポートした時点でカスタムリソースを撤去し、標準プロパティへ移行する。

---

# 本番運用対応

- 2026.08.05
- 作成者: codex

本要件のPoCでは簡易な構成を許容するため、正式なサービスとして本番運用する前に、少なくとも次を要件化して対応する。

- Runtime実行ロールへ付与するAWS管理ポリシー`AmazonBedrockMantleInferenceAccess`を見直し、利用するモデルと操作に限定した最小権限のカスタムポリシーへ移行する。
- IAMによるインバウンド認証だけで要件を満たすかを確認し、エンドユーザーを識別するOAuth/JWT認証やAgentCore Identityの利用要否を検討する。
- Publicネットワークの利用を見直し、VPC接続、PrivateLink、必要なVPCエンドポイント、送信先制御を検討する。
- `DEFAULT` endpointだけの運用を見直し、名前付きendpoint、Runtimeバージョンの昇格、ロールバック、既存セッションへの影響を含むリリース方式を定義する。
- AgentCore Observability、トレース、アプリケーションログ、メトリクス、アラームを設計し、記録項目と機密情報・個人情報のマスキング方針を定義する。
- AgentCore Memoryの保存期間、利用者分離、暗号化キー、削除要求、バックアップまたは復旧、長期記憶戦略の要否を定義する。
- 同時セッション数、呼び出し時間、モデルおよびMemoryのクォータを確認し、コスト予算とアラートを設定する。

---

# Weather／Time Toolの実データ化

- 2026.08.07
- 作成者: codex
- `specs/05-agent-tool-weather-01/`で提供する天気・時刻情報は、外部サービスへ接続しない固定モックだけであり、現在の実天気または実時刻を提供しない。
- 実天気／実時刻の取得は後続要件とし、外部サービスの選定、認証方式、利用制限、入力・出力契約および障害時の振る舞いを設計してから実装する。
- 高度な運用対応は、上記「本番運用対応」を共通の正本とし、Weather／Time固有の要件が生じた場合だけ後続featureで追加する。
