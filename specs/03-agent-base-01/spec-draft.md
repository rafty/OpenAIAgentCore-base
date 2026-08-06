# Agent 要件概要

## 1. 目的

- OpenAI Agents SDKで作成したマルチエージェントをAmazon Bedrock AgentCore Runtime上で実行できるようにします。
- AWS CDKでAgentCore Runtime、AgentCore Memory、実行ロールなどの関連AWSリソースを定義し、再現可能な形でデプロイできるようにします。
- 本要件はPoCを対象とします。本番運用に向けた追加対応は`specs/backlog/backlog.md`で管理します。

## 2. 対象範囲

- OpenAI Agents SDKによるマネージャーAgentとWeather Agentの実装
- OpenAI PythonのAmazon Bedrockプロバイダーを利用した`openai.gpt-5.5`の呼び出し
- `bedrock-agentcore`の`BedrockAgentCoreApp`によるAgentCore Runtime向けHTTPアプリケーション
- OpenAI Agents SDKのストリーミング実行
- OpenAI Agents SDK SessionとAgentCore Memoryによる会話履歴の保持
- AgentコンテナとAgentCore関連AWSリソースのAWS CDKによる定義
- ローカルテスト、コンテナテスト、`cdk synth`による自動検証

## 3. 対象外

- 実データを取得する天気取得Toolの実装
- AgentCore ObservabilityおよびOpenAI Agents SDKのトレース出力
- 本番環境向けの最小権限化、閉域ネットワーク、利用者認証、監視・アラーム、運用設計
- 長期記憶の抽出戦略を利用した、セッションをまたぐユーザー情報の活用
- ユーザーの明示的な依頼を伴わないAWS環境へのデプロイおよびスモークテスト

## 4. Agent実行要件

- SDK名は「OpenAI Agents SDK」に統一します。
- Agentの実行にはOpenAI Agents SDKの`Agent`と`Runner.run_streamed()`を使用します。
- `Runner.run_streamed()`が返すイベントを完了まで消費し、生成テキストをAgentCore RuntimeのHTTPレスポンスとして逐次ストリーミングします。
- AgentCore Runtimeで実行するため、Agentのエントリーポイントを`BedrockAgentCoreApp`でラップします。
- 入力JSONは必須の文字列フィールド`prompt`と`actor_id`を持つ形式とします。
- `actor_id`はAgentCore Memoryの`actorId`として使用し、AgentCore Memoryが許容する形式と長さを検証します。
- AgentCore Runtimeの`runtimeSessionId`は入力JSONに重複して含めず、`BedrockAgentCoreApp`の実行コンテキストから取得します。
- `prompt`または`actor_id`の欠落、空文字、文字列以外の値、不正な形式は入力エラーとして扱い、モデルを呼び出しません。
- ストリーミングレスポンスはSSEとし、各`data`をJSONオブジェクトで返します。
- SSEイベントは少なくとも次の3種類を持ちます。
  - `text_delta`: `delta`フィールドに生成されたテキスト差分を設定します。
  - `completed`: ストリームが正常完了したことを示し、正常時に1回だけ返します。
  - `error`: ストリーミング開始後に処理を継続できない場合に、`message`フィールドで安全なエラーメッセージを返します。
- 入力検証エラーなどストリーミング開始前に判明したエラーは適切なHTTPエラーとし、開始後のエラーは`error`イベントを返してストリームを終了します。
- 内部例外、スタックトレース、認証情報をクライアントへ返しません。

入力例を次に示します。

```json
{
  "prompt": "今日の天気を教えてください。",
  "actor_id": "poc-user-001"
}
```

SSEイベント例を次に示します。

```text
data: {"type":"text_delta","delta":"現在、"}

data: {"type":"text_delta","delta":"天気取得Toolは未実装です。"}

data: {"type":"completed"}
```

## 5. モデル接続要件

- AgentCore RuntimeとAgentCore Memoryを配置するAWSリージョンは`us-east-2`とします。CDKスタック自体のデプロイ先も`us-east-2`に固定し、異なるリージョンへのデプロイを許容しません。
- 使用するモデルIDは`openai.gpt-5.5`とします。
- OpenAI PythonのAmazon Bedrockプロバイダーを使用し、OpenAI Agents SDKのモデルクライアントとして設定します。
- AgentCore Runtimeの実行ロールから取得したAWS認証情報を用いてSigV4認証します。
- `OPENAI_API_KEY`およびAmazon Bedrock APIキーは使用しません。
- Agentコンテナの依存関係には、Amazon Bedrockプロバイダーを含むOpenAI Python、OpenAI Agents SDK、`bedrock-agentcore`を含めます。具体的なバージョンは実装計画で決定し、互換性を固定します。

## 6. マルチエージェント要件

- Agents-as-Tools型のマルチエージェント構成とします。
- マネージャーAgentが利用者との対話、スペシャリストAgentの選択、最終回答を担当します。
- Weather Agentを`Agent.as_tool()`でマネージャーAgentへ登録します。Handoffは使用しません。
- Weather Agent自体は実装しますが、実データを取得する天気取得Toolは本要件では実装しません。
- Weather Agentは天気取得Toolが未実装であり、現在は天気情報を取得できないことを明示して回答します。架空の天気や取得していない天気情報を回答してはいけません。
- 今後追加するスペシャリストAgentも、原則としてマネージャーAgentからAgent-as-Toolとして利用できる構成にします。

## 7. Agentへの指示

- Agentの`instructions`など、モデルへ渡す指示は原則として日本語で記述します。
- Agent-as-Toolの`tool_description`など、モデルが参照する説明も原則として日本語で記述します。
- Agentに関連するSkillを追加する場合も、原則として日本語で記述します。
- マネージャーAgentには、利用可能なスペシャリストAgentの責務と利用条件を明示します。
- Weather Agentには、天気取得Toolが未実装の間は情報を捏造しないことを明示します。

## 8. セッション・会話履歴要件

- OpenAI Agents SDKのSessionインターフェースを使用し、同じ会話セッション内の実行間で会話履歴を引き継ぎます。
- 会話履歴の永続化先にはAgentCore Memoryの短期記憶を使用し、AWS CDKでMemoryリソースを定義します。
- AgentCore Memoryに対応するOpenAI Agents SDK Session実装を用意し、履歴を二重管理しません。
- `BedrockAgentCoreApp`の実行コンテキストから取得する`context.session_id`をAgentCore Memoryの`sessionId`へ対応付けます。
- 入力JSONの`actor_id`をAgentCore Memoryの`actorId`へ対応付けます。
- AgentCore Memoryの`actorId`と`sessionId`を組み合わせ、異なる利用者および会話の履歴を分離します。
- AgentCore Memoryは短期記憶のみを使用し、保存期間を30日とします。
- AgentCore Memoryの暗号化にはAWS所有キーを使用し、本要件ではカスタマー管理KMSキーを作成しません。
- PoC用スタックの削除時にはAgentCore Memoryも削除するように、Removal Policyを`DESTROY`とします。
- ストリーミング処理が正常終了した時点で、利用者入力とAgentの最終応答が次回実行で復元できる状態にします。
- ストリーミング中断やモデル呼び出し失敗時に、不完全な応答を正常な会話履歴として確定しないようにします。
- 長期記憶の抽出戦略は使用せず、セッションをまたいだユーザー属性や嗜好の再利用は対象外とします。

## 9. Agentコードの構成

- Agentコードは`<プロジェクトルート>/agents/`に配置し、Dockerビルドできる構成にします。
- `agents/`配下のPython依存関係は`uv`ではなく`requirements.txt`で管理します。
- コンテナイメージはAgentCore Runtimeの要件に合わせてLinux ARM64でビルドします。
- コンテナはポート`8080`で待ち受け、`BedrockAgentCoreApp`が提供する`/invocations`と`/ping`を利用できるようにします。

```text
project/
└── agents/
    ├── main.py
    ├── requirements.txt
    ├── Dockerfile
    └── .dockerignore
```

## 10. CDK要件

- 既存スタック`<プロジェクトルート>/agent_core_cdk_stack/agent_core_stack.py`から、`<プロジェクトルート>/agent_core_cdk_stack/constructs/`配下の適切な粒度のConstructを呼び出します。
- AgentCore Runtime、AgentCore Memory、IAMなどのリソース定義をスタックへ直接ベタ書きせず、責務ごとにConstructへ分割します。
- `agentcore.AgentRuntimeArtifact.from_asset()`で`agents/`をDockerビルドし、`platform=ecr_assets.Platform.LINUX_ARM64`を指定します。
- AgentCore Runtimeは次のPoC構成とします。
  - プロトコル: HTTP
  - インバウンド認証: IAM
  - ネットワーク: Public
  - Runtime endpoint: `DEFAULT`のみ
  - AgentCoreの高度なトレーシング: 無効
- Runtimeの環境変数には秘密情報を設定せず、少なくとも次を設定します。
  - `AWS_REGION=us-east-2`
  - `BEDROCK_OPENAI_MODEL_ID=openai.gpt-5.5`
  - `OPENAI_AGENTS_DISABLE_TRACING=1`
  - AgentCore MemoryのMemory ID
- PoCではRuntime実行ロールへAWS管理ポリシー`AmazonBedrockMantleInferenceAccess`を付与します。
- Runtime実行ロールへ、対象のAgentCore Memoryの会話履歴を読み書きするために必要な権限を付与します。
- OpenAI Agents SDKのトレーシングは既定のOpenAI向けエクスポートを行わせないため無効化し、AgentCoreの高度なトレーシングとは別の設定として扱います。
- AgentCore MemoryはAWS CDKのMemory Constructで、短期記憶の保存期間を30日、長期記憶戦略なし、カスタマー管理KMSキーなしとして定義します。
- AgentCore MemoryへRemoval Policyの`DESTROY`を設定します。

参考となるRuntime定義の要点は次のとおりです。最終的な配置とConstruct分割は実装計画で決定します。

```python
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_iam as iam

artifact = agentcore.AgentRuntimeArtifact.from_asset(
    directory="./agents",
    platform=ecr_assets.Platform.LINUX_ARM64,
)

runtime = agentcore.Runtime(
    self,
    "OpenAiAgentRuntime",
    runtime_name="OpenAiAgentRuntime",
    agent_runtime_artifact=artifact,
    authorizer_configuration=agentcore.RuntimeAuthorizerConfiguration.using_iam(),
    network_configuration=agentcore.RuntimeNetworkConfiguration.using_public_network(),
    protocol_configuration=agentcore.ProtocolType.HTTP,
    tracing_enabled=False,
    environment_variables={
        "AWS_REGION": "us-east-2",
        "BEDROCK_OPENAI_MODEL_ID": "openai.gpt-5.5",
        "OPENAI_AGENTS_DISABLE_TRACING": "1",
    },
)

runtime.role.add_managed_policy(
    iam.ManagedPolicy.from_aws_managed_policy_name(
        "AmazonBedrockMantleInferenceAccess"
    )
)
```

## 11. 検証要件

- マネージャーAgent、Weather Agent、入力検証、ストリーミング、セッション処理を単体テストします。
- `prompt`と`actor_id`の正常系および入力エラーをテストします。
- SSEで`text_delta`が逐次返され、正常時に`completed`が1回だけ返されることをテストします。
- ストリーミング開始後の失敗時に`error`が返され、内部情報が漏えいしないことをテストします。
- Weather Agentが実在する天気情報を捏造せず、未実装であることを回答することをテストします。
- 同じ`actorId`と`sessionId`で会話履歴が復元され、異なる識別子間で履歴が混在しないことをテストします。
- AgentコンテナをLinux ARM64向けにビルドし、ローカルで`/ping`と`/invocations`を検証します。
- `uv run pytest`と`uv run python app.py`または`cdk synth`を実行し、生成されたCloudFormationテンプレートでMemoryの保存期間、暗号化設定、Removal Policyを確認します。なお、`uv`はリポジトリ側のCDKとテストの実行に使用し、`agents/`コンテナ内の依存関係管理には使用しません。
- AWS環境への`cdk deploy`、Runtime呼び出し、AgentCore Memoryとの統合スモークテストは、ユーザーの明示的な依頼を受けて手動で実施します。

## 12. 未確定事項・要確認事項

- 現時点で、仕様化を妨げる未確定事項はありません。

## 13. ADR

- OpenAI Responses APIをBedrock Mantle経由で利用し、AgentCore Runtime実行ロールのSigV4で認証する判断は、`docs/ADR/adr-0001-use-bedrock-mantle-with-runtime-role-sigv4.md`に記録します。
- HandoffではなくAgents-as-Tools型でマルチエージェントを構成する判断は、`docs/ADR/adr-0002-use-agents-as-tools.md`に記録します。
