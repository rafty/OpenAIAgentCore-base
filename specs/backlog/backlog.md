# コードの日本語コメント

- コードを実装、または、変更する際など、コードを読む人が理解しやすいように日本語でコメントを入れる
- skillの`create-sdd-tasks`に日本語コメントをいれるように、skillを更新する。


# タスク実行の Skill 作成

- 発生日: 2026.08.06
- 作成者: rafty
- タスク実行の Skill `.agents/skills/execution-sdd-tasks`に作成する。
- タスク実行の継続についても、同じskillにいれること。
- 実行が不可能なタスクの場合は、タスクの行の後ろに理由([理由]・・・)を記載する。
- タスク実行が完了し、次回以降に実施すべきタスクがあれば、tasks.mdの最後に`## 次回以降に実施すべきタスク`に記載する。
- docs/SDD/のドキュメントを更新する。


# AgentCoreのローカルデバッグの検討

- 2026.08.06
- 作成者: rafty
- ビルドしたAgentのコンテナをAWSにデプロイしてデバッグする前に、ローカル環境でAgentをデバッグする検討をする。
- AgentのToolにおけるDBなどはAWSリソースを使い、AgentのPythonコードをローカルデバッグする方法を検討する。

# Agent実行のデバッグ

- Bedrock上のAgentのデバッグができるようにログなどを整備する。
- Amazon Bedrock AgentCore のオブザーバビリティが適切ならそれを対応する。


# マルチエージェントのスペシャリストエージェントのTool実装

- 2026.08.05
- 作成者: rafty
- 天気予報エージェントのToolは、`lambda_tools/weather`にコードがあります。
- ツールスキーマは`lambda_tools/weather/tools.json`にあります。

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
