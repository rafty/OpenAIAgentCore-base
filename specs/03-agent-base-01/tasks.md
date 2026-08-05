# Tasks: OpenAI Agents SDK AgentのAgentCore Runtime基盤

## 前提確認

- [ ] T001 固定した依存バージョンと公開インターフェースの互換性を確認する
  - 対象: `openai-agents==0.19.4`、`openai[bedrock]==2.53.0`、`bedrock-agentcore==1.20.0`
  - 実施内容: Python 3.12およびLinux ARM64を対象に3パッケージを同時解決し、Bedrock provider、`OpenAIResponsesModel`、`SessionABC`、`BedrockAgentCoreApp`、Memory clientの主要importと計画で利用する公開インターフェースを確認する。
  - 完了条件: 依存解決と主要importが成功し、`plan.md`の技術方針で使用するAPIが存在する。互換性問題がある場合は実装を開始せず、`plan.md`の再レビューが必要であることを記録している。
  - 依存: なし

- [ ] T002 [P] `BedrockAgentCoreApp`のHTTP・SSE・キャンセル境界を確認する
  - 対象: `bedrock-agentcore==1.20.0`の`BedrockAgentCoreApp`
  - 実施内容: 最小のcontract probeで、非同期entrypointが検証後に非同期streamを返す構成、stream開始前のHTTPエラー、dictからSSEへの変換、クライアント切断時のgenerator cancelを確認する。
  - 完了条件: `plan.md`で定めた入力検証前後のHTTP境界とSSE生成方式を実装できることを確認している。相違がある場合は実装を止め、仕様または計画への影響を記録している。
  - 依存: T001

- [ ] T003 [P] AgentCore MemoryのイベントAPIとblob payload契約を確認する
  - 対象: `bedrock-agentcore==1.20.0`のMemory client、`CreateEvent`、`ListEvents`
  - 実施内容: Memory clientのactor/session指定、ページング、client token、blob payloadの入出力形状を確認し、version付きSession operation envelopeを欠落なく往復できるテストダブルの契約を定める。
  - 完了条件: ローカル実装とテストで固定するAPI形状が明確になり、実サービスでの確認はユーザーがAWS検証を明示依頼した場合だけ行う境界が維持されている。
  - 依存: T001

## 実装タスク

### Agent依存関係とアプリケーション基盤

- [ ] T010 Agent実行依存とテスト実行環境を固定する
  - 対象: `agents/requirements.txt`、`pyproject.toml`、`uv.lock`
  - 実施内容: Agentコンテナの3パッケージを完全一致バージョンで`requirements.txt`へ定義し、同じ依存をリポジトリの開発依存へ追加する。`agents/src`をpytestのPython pathへ設定し、`uv lock`でlockfileを更新する。
  - 完了条件: コンテナ側は`requirements.txt`、CDK・テスト側は`uv`という管理境界が維持され、両側の主要3パッケージが同一バージョンで解決される。
  - 依存: T001、T002、T003

- [ ] T011 [P] 環境設定の読み込みと起動時検証を実装する
  - 対象: `agents/src/agent_app/__init__.py`、`agents/src/agent_app/config.py`
  - 実施内容: `agent_app` packageと設定オブジェクトを作成し、`AWS_REGION`、`BEDROCK_OPENAI_MODEL_ID`、`AGENTCORE_MEMORY_ID`を読み込む。リージョンとモデルIDの固定値および必須値を検証し、秘密値を設定対象に含めない。
  - 完了条件: 正しい非秘密設定だけで構成を生成でき、不足値または仕様外のregion/model IDは安全な起動時エラーになる。
  - 依存: T010

- [ ] T012 [P] 入力検証とSSEイベント契約を実装する
  - 対象: `agents/src/agent_app/contracts.py`
  - 実施内容: JSON object、`prompt`、`actor_id`、Runtimeコンテキストの`session_id`を検証し、HTTP 400/5xxの安全な応答と`text_delta`、`completed`、`error`のJSONイベント生成を定義する。
  - 完了条件: actor/session IDの長さとパターン、必須fieldの型・空値を仕様どおり判定でき、入力payloadからRuntime session IDを受け取らず、エラーへ内部情報を含めない。
  - 依存: T010

### AgentCore Memory Session

- [ ] T020 [P] Session operation envelopeのcodecと履歴foldを実装する
  - 対象: `agents/src/agent_app/session.py`
  - 実施内容: `schema_version`、`operation`、`items`を持つUTF-8 JSON blobを直列化・復元し、`append`、`pop`、`clear`を順に適用して論理履歴を構築する。未知version、未知operation、破損payloadはfail-closedとする。
  - 完了条件: OpenAI Agents SDKのSession itemの型と順序を保って往復でき、論理的なpop/clear後の履歴を決定的に復元できる。
  - 依存: T010、T003

- [ ] T021 AgentCore Memoryアクセス境界を実装する
  - 対象: `agents/src/agent_app/session.py`
  - 実施内容: Memory client factory、actor/sessionを必須指定した全ページ取得、イベント時刻とIDによる安定sort、client token付きイベント作成を実装する。同期APIは`asyncio.to_thread()`へ隔離する。
  - 完了条件: 指定されたMemory、actor、session以外を読み書きせず、複数pageを欠落なく取得し、同期I/Oがevent loopを直接ブロックしない。
  - 依存: T011、T020

- [ ] T022 `AgentCoreMemorySession`のSession protocolと確定制御を実装する
  - 対象: `agents/src/agent_app/session.py`
  - 実施内容: `SessionABC`の`get_items()`、`add_items()`、`pop_item()`、`clear_session()`を実装する。通常実行のitemはバッファし、`commit()`で単一append eventとして確定し、`rollback()`で破棄する。同一リトライではclient tokenを再利用する。
  - 完了条件: 正常commitだけが次回復元可能になり、失敗・キャンセル時の未確定itemは保存されず、limit、pop、clearがSession protocolどおり動作する。
  - 依存: T020、T021

### Bedrockモデルとマルチエージェント

- [ ] T030 [P] Bedrock Responses modelのファクトリーを実装する
  - 対象: `agents/src/agent_app/models.py`
  - 実施内容: `AsyncOpenAI(provider=bedrock(region=...))`と`OpenAIResponsesModel`を生成し、固定モデルIDを明示的に利用する。API key、Bearer token、静的AWS認証情報は設定しない。
  - 完了条件: Runtime実行ロールの標準AWS認証情報チェーンとSigV4を使用するモデルを注入可能に生成でき、グローバル既定clientへ依存しない。
  - 依存: T010、T011

- [ ] T031 マネージャーAgentとWeather AgentをAgent-as-Toolで構成する
  - 対象: `agents/src/agent_app/agent_factory.py`
  - 実施内容: 日本語instructionsを持つ両Agentを生成し、Weather Agentを`Agent.as_tool()`でマネージャーAgentへ登録する。Handoffを設定せず、天気Tool未実装と捏造禁止を両Agentおよびtool descriptionへ明記する。
  - 完了条件: マネージャーAgentが会話と最終回答を所有し、Weather Agentが実天気Toolや`lambda_tools/weather`を使用せず、モデルをテストダブルへ差し替えられる。
  - 依存: T030

### ストリーミング実行とRuntime HTTP境界

- [ ] T040 Agent実行とSession確定順序を制御するサービスを実装する
  - 対象: `agents/src/agent_app/service.py`
  - 実施内容: `Runner.run_streamed()`の全イベントを消費し、`ResponseTextDeltaEvent`だけを`text_delta`へ変換する。全消費後にSessionをcommitして`completed`を1回返し、通常例外時はrollback後に安全な`error`だけを返し、キャンセル時はrollbackして再送出する。
  - 完了条件: 正常、モデル失敗、Session/Memory失敗、クライアント切断の各経路で`completed`と`error`が排他的になり、不完全な履歴を確定しない。
  - 依存: T012、T022、T031

- [ ] T041 検証後にstreamを返すRuntimeアプリケーションを実装する
  - 対象: `agents/src/agent_app/runtime.py`
  - 実施内容: `BedrockAgentCoreApp`のアプリケーションファクトリーとentrypointを作成し、payloadと`context.session_id`の検証成功後だけ非同期ジェネレーターを返す。Agent、Session、Memory client、serviceの依存注入境界を用意する。
  - 完了条件: 入力不正はモデル・Memory未呼び出しでストリーム開始前のHTTP 400、設定・context不備は安全な5xx、正常時はSSEになる。
  - 依存: T002、T011、T012、T040

- [ ] T042 ポート8080で起動するコンテナentrypointを実装する
  - 対象: `agents/main.py`
  - 実施内容: OpenAI Agents SDKのトレースを明示的に無効化し、Runtimeアプリケーションを生成して`app.run(port=8080)`を呼び出す。Agent生成やMemory処理は持たせない。
  - 完了条件: `/invocations`と標準`/ping`を提供するアプリケーションがポート8080で起動し、entrypointの責務が起動処理に限定されている。
  - 依存: T041

### Agentコンテナ

- [ ] T050 Linux ARM64向け非rootコンテナを定義する
  - 対象: `agents/Dockerfile`、`agents/.dockerignore`
  - 実施内容: Python 3.12 slim系base image、`requirements.txt`の依存導入、`PYTHONPATH=/app/src`、非root user、`EXPOSE 8080`、`CMD ["python", "main.py"]`を定義する。Git情報、cache、テスト生成物、ローカル設定をbuild contextから除外する。
  - 完了条件: コンテナへ`uv`、CDK側の依存ファイル、認証情報を持ち込まず、Linux ARM64で再現可能な実行イメージを構築できる定義になっている。
  - 依存: T010、T042

### AgentCore Memory・Runtime CDK構成

- [ ] T060 [P] AgentCore Memory Constructを実装する
  - 対象: `agent_core_cdk_stack/constructs/agent_core_memory_construct.py`
  - 実施内容: `agentcore.Memory`を短期記憶30日、長期記憶strategyなし、KMS key指定なしで作成し、`RemovalPolicy.DESTROY`を設定する。Runtime Constructへ渡すMemory参照を公開する。
  - 完了条件: AWS所有キーを利用し、スタック削除時にMemoryも削除されるPoC構成が責務別Constructへ閉じている。
  - 依存: T010

- [ ] T061 AgentCore Runtime Constructを実装する
  - 対象: `agent_core_cdk_stack/constructs/agent_core_runtime_construct.py`
  - 実施内容: `agents/`のLinux ARM64 asset、HTTP protocol、IAM authorizer、Public network、tracing無効、4つの非秘密環境変数を明示する。Runtime roleへ`AmazonBedrockMantleInferenceAccess`と対象Memoryのread/write権限を付与し、名前付きendpointは作らない。
  - 完了条件: `DEFAULT` endpointだけを使用するRuntime、実行ロール、Memory接続がConstructで定義され、API keyや静的認証情報が含まれない。
  - 依存: T050、T060

- [ ] T062 既存スタックとCDKアプリケーションをConstructへ接続する
  - 対象: `agent_core_cdk_stack/agent_core_stack.py`、`agent_core_cdk_stack/constructs/.gitkeep`、`app.py`
  - 実施内容: Memory ConstructをRuntime Constructへ渡して組み立て、不要になったplaceholderを削除する。既存stack IDと既定accountを維持し、regionを`us-east-2`へ固定する。
  - 完了条件: スタックが個別リソース定義を持たずConstructの組み立てだけを担い、`us-east-2`以外をデプロイ先にしない構成になっている。
  - 依存: T060、T061

## テスト / 検証タスク

### 単体検証

- [ ] T100 [P] Agent依存バージョンの一致をテストする
  - 対象: `tests/unit/agent/`、`agents/requirements.txt`、`pyproject.toml`
  - 実施内容: 主要3パッケージがコンテナ用とテスト用で完全一致し、必要な公開interfaceをimportできることを自動テストへ固定する。
  - 完了条件: バージョン差異、欠落、import不能をテストが検出する。
  - 依存: T010

- [ ] T101 [P] 設定の正常系と起動時エラーをテストする
  - 対象: `tests/unit/agent/`、`agents/src/agent_app/config.py`
  - 実施内容: 必須環境変数、固定region/model ID、Memory ID、トレース無効設定の正常・異常境界をテストする。
  - 完了条件: 正しい設定だけが受理され、設定不備に秘密値や内部例外を含まない安全なエラーとなる。
  - 依存: T011

- [ ] T102 [P] 入力とSSEイベント契約をテストする
  - 対象: `tests/unit/agent/`、`agents/src/agent_app/contracts.py`
  - 実施内容: payload型、必須fieldの欠落・空・型不正、actor/session IDの境界値と形式、および3種類のSSE JSON eventをparameterized testで確認する。
  - 完了条件: AC-004の入力境界とAC-005のevent schemaを検証し、入力不正時にmodel/session factoryが呼ばれないことを確認できる。
  - 依存: T012、T041

- [ ] T103 [P] Bedrock model設定と認証情報非依存をテストする
  - 対象: `tests/unit/agent/`、`agents/src/agent_app/models.py`
  - 実施内容: provider、region、Responses model、model IDを検査し、API key、Bearer token、静的AWS認証情報が設定されないことを確認する。
  - 完了条件: AC-002のモデル接続と認証方針をAWSへ接続せず自動検証できる。
  - 依存: T030

- [ ] T104 [P] Agent-as-Tool構成と捏造禁止をテストする
  - 対象: `tests/unit/agent/`、`agents/src/agent_app/agent_factory.py`
  - 実施内容: Weather Agentのtool登録、Handoffなし、日本語instructions、未実装回答、マネージャーAgentの最終回答所有を構成検査とテストModelで確認する。
  - 完了条件: AC-003を満たし、Weather AgentもマネージャーAgentも取得していない天気を生成しないことを決定的に検証できる。
  - 依存: T031

- [ ] T105 [P] Sessionの履歴復元・分離・確定制御をテストする
  - 対象: `tests/unit/session/`、`agents/src/agent_app/session.py`
  - 実施内容: fake Memory clientで複数page、安定順序、limit、同一・異なるactor/session、append/pop/clear、未知version、破損payload、遅延I/O、commit/rollback、client token再利用をテストする。
  - 完了条件: AC-006を満たし、失敗・キャンセル時の未確定履歴、別actor/sessionの履歴、破損データを正常履歴として扱わない。
  - 依存: T022

- [ ] T106 [P] ストリームの正常・異常・キャンセル処理をテストする
  - 対象: `tests/unit/agent/`、`agents/src/agent_app/service.py`
  - 実施内容: 複数delta、全イベント消費、commit成功・失敗、model/session例外、キャンセルをテストし、event順序とSessionのcommit/rollback呼び出しを検査する。
  - 完了条件: 正常時は末尾の`completed`が1回だけ、開始後失敗時は安全な`error`だけ、キャンセル時は追加eventなしとなる。
  - 依存: T040

- [ ] T107 [P] AgentCore CDKリソースと主要propertyをテストする
  - 対象: `tests/unit/test_open_ai_agent_core_base_stack.py`
  - 実施内容: 既存の空テストをCDK assertionsへ置き換え、Runtime、Memory、role/policy、HTTP、IAM authorizer、Public network、tracing無効、環境変数、30日retention、strategy/KMSなし、DeletionPolicy、ARM64 asset、regionを検査する。
  - 完了条件: AC-001、AC-002のIAM部分、AC-007のasset設定を自動検証でき、名前付きendpointが含まれない。
  - 依存: T062

### 結合検証 / 動作確認

- [ ] T110 [P] 決定的なモデルでマルチエージェント実行を検証する
  - 対象: `tests/integration/agent/`
  - 実施内容: 実モデルを呼ばないテストModelで天気質問をWeather Agentへ委譲し、未実装結果をマネージャーAgentが利用者向け最終回答へ統合する実行経路を検証する。
  - 完了条件: Agent-as-Toolが実際に呼ばれ、Handoffや架空の天気を使わずマネージャーAgentが最終回答を返す。
  - 依存: T031、T040、T104

- [ ] T111 RuntimeのHTTP 4xx・SSE・Session連携を検証する
  - 対象: `tests/integration/agent/`
  - 実施内容: test Modelとfake Memory clientをアプリケーションファクトリーへ注入し、`/invocations`の入力エラー、context session ID、複数delta、正常完了、開始後失敗、Memory失敗、切断をHTTP/SSE parserで確認する。
  - 完了条件: AC-004、AC-005、AC-006をHTTP境界で満たし、各SSE `data`がJSONとして解析でき、内部例外が露出しない。
  - 依存: T041、T102、T105、T106

- [ ] T112 コンテナ契約テスト用ハーネスを作成する
  - 対象: `tests/container/`
  - 実施内容: 本番コードと同じアプリケーションファクトリーへtest Modelとfake Memory clientを注入し、実AWS接続なしでコンテナの`/ping`と`/invocations`を検証できるハーネスを作成する。
  - 完了条件: 本番の入力/SSE/Session境界を差し替えず、依存だけを注入してコンテナ契約を再現できる。
  - 依存: T050、T111

### 静的検証 / ビルド

- [ ] T120 `uv`環境のlock整合性と自動テストを検証する
  - 対象: `uv lock --check`、`uv run pytest`
  - 実施内容: lockfileの整合性を確認し、Agent、Session、HTTP統合、CDK assertionを含むテストsuiteを実行する。
  - 完了条件: 両コマンドがエラーなく完了し、AC-002からAC-006およびAC-008に対応する結果を記録している。
  - 依存: T100、T101、T102、T103、T104、T105、T106、T107、T110、T111

- [ ] T121 CDK synthとCloudFormationテンプレートを検証する
  - 対象: `uv run python app.py`、生成された`cdk.out`のCloudFormationテンプレート
  - 実施内容: ローカルsynthを実行し、CDK assertionと同じ主要property、Secret非混入、MemoryのDeletionPolicy、region、ARM64 assetを生成テンプレートで確認する。
  - 完了条件: synthが成功し、AC-001、AC-002、AC-008を満たすテンプレートである。生成物は変更対象へ含めない。
  - 依存: T107、T120

- [ ] T122 Linux ARM64コンテナとHTTP契約を検証する
  - 対象: `docker build --platform linux/arm64 -t openai-agentcore-poc:local agents`、ローカルコンテナ
  - 実施内容: ARM64 imageをbuildし、非root user、依存import、ポート8080の`/ping`、テストハーネスを用いた`/invocations`の4xx・正常SSE・異常SSEを確認する。
  - 完了条件: AC-007を満たし、`requirements.txt`から再現した同一コンテナでhealthとHTTP/SSE契約が成功する。
  - 依存: T112、T120

- [ ] T123 差分・生成物・認証情報の混入を検査する
  - 対象: `git diff --check`、`git status --short`、コンテナ内容、CloudFormationテンプレート
  - 実施内容: 不要な整形、cache、`cdk.out`、Docker一時物、API key、AWS access key、secret、state fileが成果物へ含まれていないことを検査する。
  - 完了条件: 依頼範囲外の変更と機密情報がなく、生成物・一時ファイルがGit差分へ含まれていない。
  - 依存: T121、T122

- [ ] T124 AWS検証の実施可否と結果を記録する
  - 対象: `cdk diff`、`cdk deploy`、AgentCore Runtime・Memoryスモークテスト
  - 実施内容: ユーザーが明示的に依頼した場合だけ、AWS差分、SigV4モデル接続、SSE、同一・異なるactor/sessionの履歴復元・分離を確認する。依頼がない場合はAWS操作を行わず、その理由を完了報告へ記録する。MMDSv2確認は実施しない。
  - 完了条件: 明示依頼がある場合は承認範囲のAWS検証結果が記録され、ない場合は未実施と理由が明記されている。
  - 依存: T121、T122

## ドキュメント更新タスク

- [ ] T200 [P] Agentの構成・契約・検証・運用上の注意を文書化する
  - 対象: `docs/Agent/README.md`、`docs/Agent/.gitkeep`
  - 実施内容: Agent構成、ディレクトリ、固定依存、環境変数、入力/SSE契約、Session operation envelope、ローカルテスト、ARM64 build、デプロイ・呼び出し手順、同一session並行呼び出しの注意、Memory retentionと削除警告を記載し、placeholderを削除する。構成関係と正常・異常時の履歴確定順序をMermaid図で示す。
  - 完了条件: 文書が実装と一致し、AWS操作には明示依頼が必要であることと`cdk destroy`による履歴削除リスクが明確である。Mermaid図が本文と整合し、構文を正しく表示できる。
  - 依存: T042、T050、T062

- [ ] T201 [P] ルートREADMEへAgent文書と標準検証コマンドの導線を追加する
  - 対象: `README.md`
  - 実施内容: 詳細を重複させず`docs/Agent/README.md`へのリンクと、`uv run pytest`、synth、Linux ARM64 Docker buildの主要コマンドを追加する。
  - 完了条件: リポジトリ利用者がAgentの詳細手順へ到達でき、READMEのCDK・uv方針と実装が一致している。
  - 依存: T050、T062

- [ ] T202 [P] 既存ADRのSDD関連リンクを更新する
  - 対象: `docs/ADR/adr-0001-use-bedrock-mantle-with-runtime-role-sigv4.md`、`docs/ADR/adr-0002-use-agents-as-tools.md`
  - 実施内容: 設計判断本文を変更せず、`Related specs`を`specs.md`、`Related plan`を`plan.md`、`Related tasks`を本ファイルへ更新する。新規ADRは作成しない。
  - 完了条件: ADRの判断内容と実装が矛盾せず、関連するSDD成果物へ正しくリンクしている。
  - 依存: T031、T062

## 完了確認

- [ ] T300 `specs.md`の全受け入れ条件との対応を確認する
  - 完了条件: AC-001からAC-008までが実装・テスト・検証タスクの結果へ対応付けられ、確認漏れがない。
  - 依存: T120、T121、T122、T124、T200、T201、T202

- [ ] T301 `plan.md`の実装方針と変更対象に沿っていることを確認する
  - 完了条件: Agent、Session、Runtime、コンテナ、CDK、依存関係、テスト、文書が計画どおり分離され、未解決になった技術事項が明記されている。
  - 依存: T300

- [ ] T302 対象外の変更が差分に混ざっていないことを確認する
  - 完了条件: `lambda_tools/weather`、Observability、長期記憶、KMS key、OAuth/JWT、閉域ネットワーク、名前付きendpoint、MMDSv2、Backlogの実装変更が含まれていない。
  - 依存: T123、T301

- [ ] T303 シークレット、一時ファイル、不要ファイルが差分に含まれていないことを確認する
  - 完了条件: API key、静的AWS認証情報、state、cache、`cdk.out`、Docker一時物、`.DS_Store`、IDE設定が成果物へ含まれていない。
  - 依存: T123、T302

- [ ] T304 検証結果と未実施項目を完了報告用に整理する
  - 完了条件: 実行したコマンドと結果、ACごとの確認結果、AWS検証の実施有無と理由、残存リスクが記録され、未実施検証を成功扱いしていない。
  - 依存: T124、T303
