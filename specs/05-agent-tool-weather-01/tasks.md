# Tasks: AgentCore Gateway Weather／TimeモックTool統合

## 前提確認

- [ ] T001 対象featureの作業条件と既存差分を確認する
  - 対象: `AGENTS.md`、`README.md`、`docs/SDD/README.md`、現在のGitブランチと作業ツリー
  - 実施内容: 適用される指示、SDDレビューゲート、要件ブランチ、既存の未コミット・ステージ済み・未追跡差分を確認し、本feature外の差分を変更、破棄または混在させない作業境界を記録する。
  - 完了条件: `05-agent-tool-weather`ブランチ上で、保護すべき既存差分と本featureの変更対象を区別できている。
  - 依存: なし

- [ ] T002 承認済み仕様とADRの要求境界を確認する
  - 対象: `specs/05-agent-tool-weather-01/specs.md`、`docs/ADR/adr-0001-use-bedrock-mantle-with-runtime-role-sigv4.md`、`docs/ADR/adr-0002-use-agents-as-tools.md`、`docs/ADR/adr-0003-use-dedicated-agentcore-gateway-for-weather-tools.md`
  - 実施内容: スコープ、対象外、FR-001〜FR-008、非機能要件、AC-001〜AC-006、IAM境界、Agents-as-Tools、モック制約およびAWS操作の承認条件を確認する。
  - 完了条件: 実装で維持する契約、意図的に変わる挙動および実装してはならない対象を説明できる。
  - 依存: T001

- [ ] T003 承認済み実装計画と変更対象を確認する
  - 対象: `specs/05-agent-tool-weather-01/plan.md`、関連するAgent／CDK／Lambdaコード、テスト、`docs/Agent/README.md`、`docs/CDK/README.md`
  - 実施内容: 変更対象、変更しないもの、固定リソース名、技術方針、失敗境界、検証方針、実施順序および未検証の技術項目を確認する。
  - 完了条件: 各実装・検証タスクの対象と依存関係がplanと一致し、仕様や設計方針を追加または再定義していない。
  - 依存: T002

- [ ] T004 固定依存と公開APIの互換性を実装前に確認する
  - 対象: Python 3.12の隔離環境、`uv.lock`で固定された`aws-cdk-lib`、`mcp-proxy-for-aws==1.6.4`、`mcp==1.29.0`、`openai-agents==0.19.4`
  - 実施内容: 3つのMCP関連packageを同時解決し、`MCPServerStreamableHttp`の継承と`create_streams()`差し替え、`use_structured_content=False`、`aws_iam_streamablehttp_client()`の引数・戻り値、`mcp.types.LATEST_PROTOCOL_VERSION`を最小probeで確認する。あわせて、CDKのGateway authorizer、MCP protocol version、inline schema、Lambda target、IAM credential provider、Gateway grantおよびLambda ARM64／asset除外APIを最小import・一時synthで確認し、Linux ARM64向け依存解決可否も早期確認する。probeはリポジトリの依存定義や生成物を変更しない隔離環境で行う。
  - 完了条件: 固定versionのままplanの実装方式が成立し、MCP clientの最新protocol versionが`2025-11-25`である。成立しない項目がある場合は実装へ進まず、仕様を推測で変更せずplan段階へ戻す。
  - 依存: T003
  - 対応: AC-002、AC-005の実装前提

## 実装タスク

### MCP依存関係とRuntime設定

- [ ] T010 Runtimeと開発環境へ固定MCP依存を追加する
  - 対象: `agents/requirements.txt`、`pyproject.toml`、`uv.lock`
  - 実施内容: `mcp-proxy-for-aws==1.6.4`と`mcp==1.29.0`をRuntimeとdev groupの両方へ完全一致で追加し、既存の固定versionを変更せず`uv`でlockを更新する。`uv.lock`は手作業で編集しない。
  - 完了条件: 両manifestのMCP依存versionが一致し、Python 3.12で同時解決・主要importが成功し、`pyproject.toml`と`uv.lock`が整合している。
  - 依存: T004

- [ ] T011 [P] Gatewayの非秘密設定を読み込み検証する
  - 対象: `agents/src/agent_app/config.py`
  - 実施内容: `AppConfig`へ`gateway_url`と`gateway_target_name`を追加し、HTTPS、userinfo／query／fragmentなし、`us-east-2`のAgentCore Gateway host、`/mcp` path、Target名の許容文字と長さを検証する。欠落・不正時は値を含まない既存の`ConfigurationError`へ変換する。
  - コメント: URL制限がSigV4署名先のservice／regionを固定する安全境界である理由と、設定値を例外へ含めず内部endpointの漏えいを防ぐ理由を、日本語で非自明な検証箇所へ記載する。
  - 完了条件: 有効な2環境変数を読み込め、不正値をAgent実行前に拒否し、エラー、レスポンスおよびログへ設定値を出力しない。日本語コメントが検証の設計意図を説明し、自明なコードの読み替えになっていない。
  - 依存: T004
  - 対応: FR-007、AC-003、AC-004

### Weather／Time Lambda Tool

- [ ] T020 [P] Lambdaハンドラーの入力・metadata・Tool分岐を安全に強化する
  - 対象: `lambda_tools/weather/handler.py`、参照のみの`lambda_tools/weather/tools.json`
  - 実施内容: `event`、`context.client_context`、`custom`、`bedrockAgentCoreToolName`を段階的に型検証し、正しい`${target}___${tool}`だけを解決する。`get_weather`と`get_time`の正常な固定モック契約を維持し、event、入力、metadataおよび未知Toolの不正時は正常フィールド、入力値、受信Tool名を含まない固定の`error`だけを返す。外部I/Oとシステム時計を追加しない。
  - コメント: Mappingを段階検証する理由、`___`形式を必須とする理由、不正な受信値をエラーへ反射しない安全上の意図を日本語で記載し、変更するdocstringも日本語へ揃える。
  - 完了条件: 正常な2 ToolだけがFR-003のJSON互換モック結果を返し、全不正系が安全な`error`だけになる。日本語コメントが安全境界の判断理由を説明し、自明な分岐の読み替えになっていない。
  - 依存: T004
  - 対応: AC-001、AC-004

### Weather／TimeモックLambdaリソース

- [ ] T030 [P] 最小権限のWeather／TimeモックLambda Constructを定義する
  - 対象: 新規`agent_core_cdk_stack/constructs/weather_time_mock_lambda_construct.py`
  - 実施内容: `OpenAiWeatherTimeMock`をPython 3.12、ARM64、128 MB、5秒、`handler.lambda_handler`で定義する。`/aws/lambda/OpenAiWeatherTimeMock`のLogGroupを7日保持・`DESTROY`で先行作成し、Lambda専用Roleは`lambda.amazonaws.com`だけを信頼して対象LogGroupの`CreateLogStream`と`PutLogEvents`だけを許可する。`AWSLambdaBasicExecutionRole`、`CreateLogGroup`、環境変数、SecretおよびVPCを追加しない。assetから`tools.json`、cache、`.DS_Store`を除外し、Lambda関数参照を公開する。
  - コメント: 専用LogGroup／Roleでwildcard権限を避ける理由、Lambda code assetのS3配布とGateway schemaのinline化が別概念である理由、`tools.json`を実行assetから除外する理由を日本語で記載する。
  - 完了条件: Constructが指定したLambda、Role、LogGroup、assetを再現し、Roleにログ以外の権限や秘密設定がない。日本語コメントが最小権限とasset境界の選択理由を説明している。
  - 依存: T004
  - 対応: AC-002

### 専用AgentCore Gateway

- [ ] T040 [P] 条件付き信頼ポリシーを持つ専用Gateway Constructを定義する
  - 対象: 新規`agent_core_cdk_stack/constructs/agent_core_weather_gateway_construct.py`
  - 実施内容: `OpenAiWeatherGateway`用の物理名を固定しない専用実行Roleを作成し、Principalを`bedrock-agentcore.amazonaws.com`、`SourceAccount`をstack account、`SourceArn`を`gateway/OpenAiWeatherGateway-*`へ限定する。GatewayへこのRoleを明示的に渡し、受信認証を`AWS_IAM`、MCP supported versionsを`2025-11-25`と`2025-03-26`にする。search type、instructions、`DEBUG`、KMS、PolicyおよびInterceptorを追加しない。
  - コメント: `gateway.gateway_arn`の直接参照による循環を避け、固定Gateway名とstack tokenからARN patternを組み立てる理由と、L2既定Roleへ任せず専用Roleを明示する理由を日本語で記載する。
  - 完了条件: Gatewayが専用Role、`AWS_IAM`および2 protocol versionを明示し、Role trustがservice、account、対象Gateway名へ限定され、Gateway resourceへの循環参照と`DEBUG`設定がない。日本語コメントが循環回避と権限境界を説明している。
  - 依存: T004
  - 対応: AC-002

### Lambda GatewayTarget

- [ ] T050 Weather／Time LambdaをインラインスキーマのGatewayTargetとして登録する
  - 対象: 新規`agent_core_cdk_stack/constructs/weather_time_gateway_target_construct.py`
  - 実施内容: `tools.json`をUTF-8 JSONとしてsynth時に読み、`ToolDefinition`、再帰的な`SchemaDefinition`および`SchemaDefinitionType`へ限定変換し、未対応shapeはfail-fastにする。`WeatherTimeMock`を`GatewayTarget.for_lambda()`、明示的な`from_iam_role()`、`ToolSchema.from_inline()`で作成する。Gateway Roleへ対象Lambda関数だけの`InvokeFunction`を付与し、GrantをTargetより前に適用して作成順を固定する。schema取得用S3権限を追加せず、Target名をRuntimeへ渡せる形で公開する。
  - コメント: 生のJSON dictをjsii L2型へ直接渡せない理由、schema正本を複製せず変換する意図、未知shapeをfail-fastにする理由、inline化でGatewayのS3権限を避ける理由およびGrant依存を明示する理由を日本語で記載する。
  - 完了条件: inline payloadが`tools.json`由来の2 Toolだけを含み、credential providerが`GATEWAY_IAM_ROLE`、Invoke policyが対象Lambda関数へ限定され、Targetがpolicyへ依存し、Gateway RoleにS3、Secrets Manager、KMSまたは他Lambdaの権限がない。日本語コメントがCDK固有の制約と選択理由を説明している。
  - 依存: T030、T040
  - 対応: AC-001、AC-002

### Runtimeとスタックの配線

- [ ] T060 Gateway参照・Target名・最小権限をRuntimeとスタックへ接続する
  - 対象: `agent_core_cdk_stack/constructs/agent_core_runtime_construct.py`、`agent_core_cdk_stack/agent_core_stack.py`
  - 実施内容: Runtime ConstructへGatewayとTarget名を注入し、`AGENTCORE_GATEWAY_URL`へ生成されたGateway URL参照、`AGENTCORE_GATEWAY_TARGET_NAME`へ`WeatherTimeMock`を追加する。対象Gateway ARNへの`bedrock-agentcore:InvokeGateway`だけをRuntime Roleへ付与し、既存モデル／Memory権限を維持する。StackはMemory、Lambda、Gateway、Target、Runtimeを生成して参照・依存関係だけを組み合わせる。
  - コメント: Gateway URLをCloudFormation tokenのまま非秘密設定で渡す理由、TargetとRuntimeが同じ定数を使う理由およびStackが個別resource詳細ではなく依存配線だけを所有する理由を日本語で記載する。
  - 完了条件: Runtime環境変数のURLがGateway URL参照、Target名が固定値であり、追加Gateway権限が対象Gatewayの`InvokeGateway`だけになる。既存HTTP／SSE、Memory、モデル、Public networkおよび`DEFAULT` endpointの契約を変えず、日本語コメントが配線責務を説明している。
  - 依存: T050
  - 対応: AC-002、AC-004

### SigV4 MCPアダプター

- [ ] T070 [P] SigV4 MCP serverとTool公開範囲を実装する
  - 対象: 新規`agents/src/agent_app/gateway_tools.py`
  - 実施内容: `MCPServerStreamableHttp`を継承し、`create_streams()`だけを`aws_iam_streamablehttp_client()`へ差し替える。service=`bedrock-agentcore`、region、endpoint、transport 30秒、ClientSession 10秒、cleanup 5秒、`terminate_on_close=True`、再試行0、固定server名`AgentCoreWeatherGateway`、`use_structured_content=False`、`cache_tools_list=True`を設定し、proxy loggerの実効levelをINFO以上に保つ。Target名から接頭辞付き2 Toolを構築して完全一致allowlistにし、初回一覧で片方でも欠ければGateway全体を利用不能とする。profile、静的credentialおよびBearer tokenを受け取らないfactoryにする。
  - コメント: Agents SDKのsession管理を維持するため`create_streams()`だけを差し替える理由、Tool cacheをリクエスト内に限定する理由、同一呼び出し内で再試行しない理由および固定server名でendpoint漏えいを避ける理由を日本語で記載する。
  - 完了条件: Runtime Roleの標準認証情報チェーンだけで署名するserverを生成でき、Weather／Timeの2 Tool以外をAgentへ公開せず、timeout、終了、cache、再試行およびログlevelの契約がplanどおりである。日本語コメントが接続・認証境界を説明している。
  - 依存: T010、T011
  - 対応: AC-003、AC-004

- [ ] T071 Tool結果を正規化して安全な利用不能結果へ変換する
  - 対象: `agents/src/agent_app/gateway_tools.py`
  - 実施内容: transportまたは`call_tool`が送出する例外を捕捉し、例外本文を含まない固定の日本語利用不能結果へ変換する。返却された`CallToolResult`はplanの優先順で正規化し、`isError`を先に判定する。`structuredContent`をMappingの正本とし、未提供時は単一TextContentのJSON objectを使用し、両方を解釈できる場合は一致を要求する。不一致、複数content、非text、JSON／Mapping不正、Lambdaの`error`、`data_type!="mock"`およびToolごとの正常フィールド欠落も同じ利用不能結果へ変換する。正常Mappingは変更せず渡す。
  - コメント: recoverableなTool呼び出し例外とfatalな接続ライフサイクル失敗を区別する理由、両表現の一致を要求して曖昧な結果を採用しない理由、形式不正をfail-closedにする理由および固定エラーへ変換して内部情報を遮断する理由を日本語で記載する。
  - 完了条件: transport／Tool呼び出し例外をRunner全体の失敗へ漏らさずWeather Agentが扱える固定結果へ変換し、競合・曖昧・不完全な結果を正常値として扱わない。正常結果だけが`data_type="mock"`とTool固有フィールドを保持し、モデル、レスポンスおよびログへ内部例外や入力値を流さない。日本語コメントが失敗分類と正規化の判断基準を説明している。
  - 依存: T070
  - 対応: AC-003、AC-004

### Weather／Manager Agent構成

- [ ] T080 [P] Weather／Manager Agentを天気・時刻・MCP利用へ更新する
  - 対象: `agents/src/agent_app/agent_factory.py`
  - 実施内容: model、利用可能なMCP server群およびGateway利用可否からリクエスト単位の`AgentBundle`を作る。Gateway MCP serverはWeather Agentだけへ登録し、WeatherのローカルTool／HandoffとManagerのMCP／Handoffを空にし、Managerの直接Toolは`weather_agent`だけに維持する。Weather Agent-as-Toolのdescriptionを天気と時刻の両方へ拡張する。天気を`get_weather(location)`、時刻・タイムゾーン・都市時刻を`get_time(timezone)`へルーティングし、正常時の固定モック明示と障害時の固定値・システム時計・推測値禁止を両Agentの日本語instructionsへ反映する。
  - コメント: ManagerへMCP Toolを直接渡さず最終回答所有を維持する理由、Gateway利用可否が安全な取得不能instructionsを選ぶ状態である理由およびモック値を実データと誤認させない意図を日本語で記載する。
  - 完了条件: WeatherだけがMCP Toolへアクセスし、Manager→WeatherのAgent-as-ToolとManager最終回答を維持する。正常時は日本語で固定モックと明示し、利用不能時は値を補完しない。日本語コメントがAgent責務境界を説明している。
  - 依存: T010
  - 対応: AC-003、AC-004

### リクエスト単位の実行ライフサイクル

- [ ] T090 MCP・Runner・Memoryの確定順序と失敗境界を実装する
  - 対象: `agents/src/agent_app/service.py`
  - 実施内容: cached model、MCP factoryおよびAgent factoryを受け取り、MCP接続、初回`tools/list`、Gateway利用可否確定後のAgent生成、Runner実行、MCP cleanup、Memory commit、`completed`の順で処理する。接続／一覧取得失敗は5秒以内に部分接続をcleanupし、成功した場合だけMCPなしの利用不能Agentへ切り替える。接続後のAgent生成、Runner、SessionまたはMemory失敗では、有限timeoutでMCP cleanupを必ず試してからrollbackし、安全なSSE `error`を返して`completed`を返さない。cleanup自体の失敗・timeoutもrollbackする。`CancelledError`ではcleanupとrollbackをbest-effortで行い、その失敗で置き換えず元のキャンセルを再送出する。ログは障害段階と安全な分類だけにする。
  - コメント: AgentをGateway利用可否の確定後に生成する理由、fallbackを部分接続のcleanup成功後に限定する理由、全post-connect失敗でcleanupをrollback／commitより先に行う理由、キャンセルを通常エラーへ変換せず再送出する理由および例外本文を記録しないログ境界を日本語で記載する。
  - 完了条件: 正常時だけcleanup後にcommitし、その後に`completed`を返す。安全な接続失敗またはTool呼び出し例外を取得不能へ変換できたturnだけを保存し、cleanup不能、Agent生成／Runner／Session／Memory失敗およびキャンセルではcleanupを試行してからrollbackし、commitしない。日本語コメントがrecoverable／fatalの分類、fail-closedおよび確定順序の理由を説明している。
  - 依存: T071、T080
  - 対応: AC-003、AC-004

- [ ] T091 Runtimeをリクエスト単位のMCP／Agent生成へ変更する
  - 対象: `agents/src/agent_app/runtime.py`
  - 実施内容: プロセス単位のManager Agent cacheを廃止してモデルだけを遅延生成後に再利用し、cached model、MCP factoryおよびAgent factoryをserviceへ注入する。各`/invocations`のasync iterator内でMCP serverとAgent bundleを1つずつ生成し、並行session間でMCP session、Tool cacheおよび障害状態を共有しない。既存の入力、session、設定検証をstream開始前に維持する。
  - コメント: modelだけをcacheしてMCP／Agentをcacheしない理由、設定検証をgenerator内部へ遅延させずHTTP境界を維持する理由およびfactory注入が実AWSを使わない決定的テストの境界になる理由を日本語で記載する。
  - 完了条件: 同一processでも呼び出しごとにMCP serverとAgentが新規生成され、modelだけが再利用される。設定不正はstream前の安全なHTTP 5xxとなり、`POST /invocations`、`GET /ping`、SSEおよびsession契約を変更しない。日本語コメントがライフサイクル分離の設計意図を説明している。
  - 依存: T011、T070、T080、T090
  - 対応: AC-003、AC-004

## テスト / 検証タスク

### Lambda ToolとCDK構成の単体検証

- [ ] T100 [P] ツールスキーマとLambdaハンドラーの契約テストを追加する
  - 対象: 新規`tests/unit/test_weather_tool_handler.py`、`lambda_tools/weather/tools.json`
  - 実施内容: JSON parse、2 Toolだけの定義、モック説明、入力type／requiredとhandler分岐の一致を確認する。Gateway contextを再現し、両正常値、event非Mapping、入力欠落・型不正・空・空白、context／custom／Tool名／delimiter不正、未知Toolをparameterizeする。失敗結果が`error`だけで正常フィールドや受信値を含まず、全応答をJSON serializeできることを検証する。
  - コメント: 複雑なGateway context fixtureと境界値には、再現する契約や安全上の意図が分かる日本語コメントを追加する。
  - 完了条件: AC-001の全項目とLambdaレベルの内部値非露出を決定的に検証し、対象テストが成功する。
  - 依存: T020
  - 対応: AC-001、AC-004、AC-005

- [ ] T101 [P] Gateway／Lambda／IAM／assetのCDKテストを追加する
  - 対象: 新規`tests/unit/test_weather_tool_gateway_stack.py`
  - 実施内容: CDK appのoutdirと検査対象assetを各テストの`tmp_path`配下へ隔離し、リポジトリの`cdk.out/`を使用・変更しない。Lambda、Gateway、Target、LogGroup、Role、Policyおよび固定名をCloudFormationから確認する。Lambdaはruntime／architecture／memory／timeout／handler、LogGroupは7日保持と`DeletionPolicy`／`UpdateReplacePolicy`、実行RoleはLambda serviceだけのtrust、対象LogGroupへの`CreateLogStream`／`PutLogEvents`だけ、managed basic policyと`CreateLogGroup`なしを確認する。Gatewayは`AWS_IAM`、2 protocol version、専用`RoleArn`を確認し、Gateway serviceのAssumeRole statementが指定`SourceAccount`／`SourceArn`条件付きだけで、同Principalの無条件statementが存在しないことを確認する。Targetは`GATEWAY_IAM_ROLE`、InvokeFunctionの対象限定、policy依存、schema用S3権限なしを確認する。inline schemaを正本の`tools.json`とname、description、inputSchemaまで正規化比較し、未対応schema shapeがsynth前に明示的に失敗する異常系テストも追加する。Gateway RoleにS3、Secrets Manager、KMSおよび他Lambda権限がなく、Gatewayに`DEBUG`がないことを確認する。asset manifest／staged assetを追跡し、`handler.py`が含まれ`tools.json`、cacheおよび一時ファイルが含まれないことを確認する。
  - コメント: logical ID文字列へ依存せずresource参照を追跡する理由と、asset内容・IAM境界を確認する非自明なassert群の目的を日本語で補足する。
  - 完了条件: AC-002のGateway、Lambda、Target、IAM、LogGroup、正本と一致するinline schema、未知schemaのfail-fast、依存順およびasset項目をtemplateとassetから確認でき、無条件Gateway trust、過剰なLambdaログ権限、managed basic policy、S3／Secrets Manager／KMS／他Lambda権限が存在しないことを自動検証して対象テストが成功する。並列実行時も一時成果物が`tmp_path`外へ作られない。
  - 依存: T030、T040、T050
  - 対応: AC-002、AC-005

- [ ] T102 [P] Runtimeとスタック配線のCDK回帰テストを拡張する
  - 対象: `tests/unit/test_open_ai_agent_core_base_stack.py`
  - 実施内容: CDK appのoutdirをテストごとの`tmp_path`へ隔離し、リポジトリの`cdk.out/`を使用・変更しない。既存Memory、RuntimeおよびDocker asset検証を維持し、Runtime環境変数のGateway URLが新規Gateway参照、Target名が`WeatherTimeMock`、Runtime Roleの追加actionが対象Gatewayの`InvokeGateway`だけであることを確認する。既存Mantle／Memory grant、region、HTTP／Public networkを維持し、API key、静的credential、内部値および`DEBUG`の非混入を確認する。
  - コメント: CloudFormation tokenとRole policyを参照経由で照合するassertには、固定文字列比較では不十分な理由を日本語で記載する。
  - 完了条件: 新規配線と既存CDK契約の回帰を同時に検証し、対象テストが成功する。並列実行時も一時成果物が`tmp_path`外へ作られない。
  - 依存: T060
  - 対応: AC-002、AC-004、AC-005

### MCP／Agent／Runtimeの単体検証

- [ ] T110 [P] MCP依存の固定versionとprotocol契約テストを拡張する
  - 対象: `tests/unit/agent/test_dependencies.py`
  - 実施内容: Runtime／dev manifestのMCP依存完全一致、実際のinstalled version、必要な公開API importおよび`mcp.types.LATEST_PROTOCOL_VERSION == "2025-11-25"`を自動回帰化する。
  - コメント: protocol versionのassertが依存更新による暗黙の契約変更を防ぐことを、日本語で非自明な箇所へ記載する。
  - 完了条件: 固定依存とMCP protocol契約を自動検証でき、対象テストが成功する。
  - 依存: T010
  - 対応: AC-005

- [ ] T111 [P] SigV4 MCPアダプターを単体検証する
  - 対象: 新規`tests/unit/agent/test_gateway_tools.py`
  - 実施内容: transport factory spyでendpoint、service、region、timeout、終了、再試行、固定server名、profile／静的credential／Bearerなしを確認する。2 Tool allowlist、1 request内の一覧cache、必須Tool欠落、transport／`call_tool`の例外送出、`structuredContent`、単一TextContent、両者一致／不一致、複数content、非text、JSON不正、`isError`、Lambda `error`、`data_type`および正常フィールドを網羅し、安全な固定エラーへ正規化されることを確認する。`caplog`でURL、ARN、入力、credentialおよび例外本文がないことを検証する。
  - コメント: Fakeのevent順、両content不一致および意図的な秘密値を使う漏えい検査には、再現する失敗境界を日本語で記載する。
  - 完了条件: 実AWSへ接続せずMCP transport、Tool公開範囲、結果正規化およびログ安全性を検証し、対象テストが成功する。
  - 依存: T070、T071
  - 対応: AC-003、AC-004、AC-005

- [ ] T112 [P] Gateway設定の正常・境界・不正値を単体検証する
  - 対象: `tests/unit/agent/test_config.py`
  - 実施内容: Gateway URLとTarget名の正常値、欠落、scheme／host／region／path／userinfo／query／fragmentおよび許容文字・長さの境界をparameterizeし、例外とログへ設定値が含まれないことを確認する。
  - コメント: 名前だけでは意図が分からない境界値に、GatewayまたはSigV4契約との対応を日本語で補足する。
  - 完了条件: 有効値だけを受理し、不正値がstream開始前に安全に拒否される設定契約を検証し、対象テストが成功する。
  - 依存: T011
  - 対応: AC-003、AC-004

- [ ] T113 [P] Weather／Manager Agentの責務とinstructionsを単体検証する
  - 対象: `tests/unit/agent/test_agent_factory.py`
  - 実施内容: WeatherだけがMCP serverを持ち、Managerの直接ToolがWeatherだけ、両AgentがHandoffなしであることを確認する。天気／時刻routing、固定モック明示、実データ断定禁止およびGateway利用不能時の推測禁止をinstructionsとdescriptionから確認する。
  - コメント: Agent-as-Toolの所有境界を検証するassert群に、その境界を固定する理由を日本語で記載する。
  - 完了条件: ADR-0002のManager所有とADR-0003のWeather限定MCP利用を自動検証し、対象テストが成功する。
  - 依存: T080
  - 対応: AC-003、AC-004

- [ ] T114 MCP・Runner・Memoryライフサイクルを単体検証する
  - 対象: `tests/unit/agent/test_service.py`
  - 実施内容: 呼び出し順と回数を記録するFake MCP／Runner／Sessionを用い、connect→list→Agent生成→run→cleanup→commit→`completed`を確認する。connect、list、call、cleanupの例外と無期限待機、Tool／Lambda失敗、Agent生成／Runner／Memory失敗およびキャンセルを再現する。connect／list失敗はcleanup成功後に取得不能最終回答→commit→`completed`へ進みrollbackしないこと、transport／Tool呼び出し例外も取得不能最終回答→cleanup→commit→`completed`になることを確認する。すべてのpost-connect fatal failureはcleanup→rollbackの順で、cleanup失敗・timeoutではrollbackして`completed`を返さず、キャンセル時はcleanup→rollback後に元の`CancelledError`を再送出し、cleanup／rollbackの失敗が元のキャンセルを置き換えないことを確認する。
  - コメント: timeout／キャンセルfixture、順序・回数記録、recoverableな接続／Tool失敗を保存する理由およびcleanup失敗をrecoverableにしない理由を日本語で補足する。
  - 完了条件: recoverableな接続／Tool失敗だけが安全な最終回答としてcommitされ、全fatal経路でcleanupを試行して接続リークと未確定Memory保存を防ぎ、安全なSSE／ログだけを返すことを検証して対象テストが成功する。
  - 依存: T071、T080、T090
  - 対応: AC-004、AC-005

- [ ] T115 Runtimeの依存生成・再利用・HTTP前処理を単体検証する
  - 対象: `tests/unit/agent/test_runtime.py`
  - 実施内容: 同じcached modelがserviceへ渡されて再利用され、MCP serverとAgent bundleが呼び出し単位に生成されること、Agent factoryが`tools/list`後に確定したGateway利用可否を受けて呼ばれること、並行呼び出しで状態を共有しないこと、factory注入およびstream開始前の入力・session・設定5xx境界を確認する。
  - コメント: async iterator消費と依存生成の時点など、遅延実行上の非自明な前提を日本語で記載する。
  - 完了条件: process単位model cacheとrequest単位MCP／Agent lifecycleを区別して検証し、既存HTTP前処理の回帰を含め対象テストが成功する。
  - 依存: T091、T114
  - 対応: AC-003、AC-004、AC-005

### Agent／HTTP／コンテナの結合検証

- [ ] T120 マルチAgentとMCP Toolの決定的な統合テストを実装する
  - 対象: `tests/integration/agent/test_multi_agent.py`
  - 実施内容: 決定的ModelとFake MCPで天気／時刻をparameterizeし、Manager→Weather→接頭辞付きMCP Tool→Weather→Managerの経路、FR-003固定値、`data_type="mock"`、日本語のモック明示および最終AgentがManagerであることを確認する。接続、transport／Tool呼び出し例外、Lambdaおよび形式異常では、SSE全体のfatal errorではなく、架空値や内部情報を含まない取得不能最終回答となってcommit／`completed`へ進むことを確認し、実Model／AWSを呼び出さない。
  - コメント: scripted Modelの各段階がどのAgentまたはTool応答を再現するか、日本語で説明する。
  - 完了条件: 天気と時刻の正常経路および障害時経路をAgent-as-Tool境界まで決定的に検証し、対象テストが成功する。
  - 依存: T111、T113、T114、T115
  - 対応: AC-003、AC-004、AC-005

- [ ] T121 [P] Runtime HTTP／SSE／Memory契約の結合回帰テストを更新する
  - 対象: `tests/integration/agent/test_runtime_http.py`
  - 実施内容: 新しいfactory注入境界を通して、`POST /invocations`、`GET /ping`、入力4xx、設定5xx、正常／異常SSE、`completed`／`error`排他、Memory commit／rollbackおよびactor／session分離が変わらないことを確認する。
  - コメント: 本番serviceとMemory fakeを通す理由、およびSSE終端とMemory確定順の対応を日本語で非自明な箇所へ記載する。
  - 完了条件: Gateway統合後も既存HTTP、SSEおよびMemory契約を維持し、対象テストが成功する。
  - 依存: T091、T114
  - 対応: AC-004、AC-005

- [ ] T122 [P] コンテナ契約ハーネスを新しい依存注入境界へ追従させる
  - 対象: `tests/container/harness_main.py`、`tests/container/test_harness.py`
  - 実施内容: 本番と同じRuntime factoryを使用したまま、実Model、Gateway、LambdaおよびMemoryへ接続しない決定的依存を注入し、host上のTestClientで`/ping`、入力エラー、正常／異常SSEおよび終端排他を確認する。build済みimageの起動検証はT133と区別する。
  - コメント: 本番factoryを意図的に通し、テスト専用のHTTP迂回実装を作らない理由を日本語で記載する。
  - 完了条件: 更新後のfactory signatureでハーネスが起動し、host上の契約テストが成功する。
  - 依存: T091
  - 対応: AC-004、AC-005

### ローカル総合検証

- [ ] T130 依存整合と全自動テストを実行する
  - 対象: `uv lock --check`、`uv run pytest`
  - 実施内容: lock整合を確認した後、既存回帰を含む全テストを実行し、失敗がないことを確認する。
  - 完了条件: 両コマンドが成功し、実行コマンドと結果を記録している。
  - 依存: T100、T101、T102、T110、T111、T112、T113、T114、T115、T120、T121、T122
  - 対応: AC-001〜AC-005のローカル部分

- [ ] T131 CDK synth結果とLambda assetを検査する
  - 対象: `uv run python app.py`または小文字の`cdk synth`、生成CloudFormationテンプレート、asset manifest／一時staged asset
  - 実施内容: synthを実行し、Gateway、Lambda、Target、Role／Policy、inline schema、IAM action／resource／trust、専用Gateway `RoleArn`、Runtime環境変数、Target依存、2 protocol version、`DEBUG`／Secret／schema用S3権限なしを確認する。Lambda assetに`handler.py`が含まれ、`tools.json`、cacheおよび一時ファイルが含まれないことを確認し、生成物をソースとして編集・commitしない。
  - 完了条件: synthが成功し、AC-002と生成物安全性の確認結果を記録している。
  - 依存: T130
  - 対応: AC-002、AC-004、AC-005

- [ ] T132 Linux ARM64 Runtime imageをbuildする
  - 対象: `docker build --platform linux/arm64 -t openai-agentcore-poc:local agents`
  - 実施内容: 固定したMCP依存を含む本番Runtime imageをLinux ARM64向けにbuildする。
  - 完了条件: image buildが成功する。Dockerを利用できない場合は未完了のまま、対象と理由を記録し、成功扱いしない。
  - 依存: T130
  - 対応: AC-005

- [ ] T133 build済みimageでコンテナHTTP契約を確認する
  - 対象: build済み`openai-agentcore-poc:local` image、read-only mountした`tests/container/harness_main.py`
  - 実施内容: Linux ARM64 imageを実際に起動し、別processから`/ping`、正常／異常`/invocations`、SSE終端および`completed`／`error`排他を確認する。host上のTestClientだけで代替しない。
  - 完了条件: build済みimage上で全HTTP確認が成功する。Dockerを利用できない場合は未完了のまま、理由を記録する。
  - 依存: T122、T132
  - 対応: AC-004、AC-005

- [ ] T134 ローカル差分と成果物の衛生状態を確認する
  - 対象: `git diff --check`、`git status --short`、本featureの全差分
  - 実施内容: whitespace error、feature外の変更、ユーザーの既存差分への意図しない変更、Secret、credential、state、一時ファイル、生成物および不要ファイルの混入を確認する。
  - 完了条件: 本featureの差分が承認済みscopeに限定され、混入がない。既存の別差分は所有者の変更として保護されている。
  - 依存: T131。T132／T133は実施状態と未実施理由を確認する
  - 対応: AC-004、AC-005

## ドキュメント更新タスク

- [ ] T200 [P] ルートREADMEのPoC概要と検証導線を更新する
  - 対象: `README.md`
  - 実施内容: 専用Gateway、Weather／TimeモックToolを含むPoC概要、Agent／CDK文書への短い導線および主要ローカル検証コマンドを実装へ合わせる。詳細手順や図を重複させず、新規Mermaid図は追加しない。
  - 完了条件: ルートREADMEが実装と一致し、詳細文書への導線が有効である。
  - 依存: T130、T131
  - 対応: AC-006

- [ ] T201 [P] Agent文書と既存Mermaid図をGateway統合後へ更新する
  - 対象: `docs/Agent/README.md`
  - 実施内容: Weather Agentの天気＋時刻担当、MCP／SigV4、2つのGateway環境変数、固定依存、リクエスト単位接続、モック制約、取得不能時の動作、ローカル検証およびRuntime E2Eを記載する。既存flowchartをGateway→Target→Lambdaまで更新し、既存sequence diagramをconnect／initialize／list／run／cleanup→commitと失敗・キャンセル時rollbackへ更新する。
  - 完了条件: 本文が実装・運用手順と一致し、2つの図が構成とライフサイクルを正しく説明し、Mermaid構文が正しく表示できる。
  - 依存: T130、T131
  - 対応: AC-006

- [ ] T202 [P] CDK文書へリソース・IAM境界・検証手順を反映する
  - 対象: `docs/CDK/README.md`
  - 実施内容: 3つの新規Construct、固定リソース名、Gateway／Target／Lambda、IAM trustと権限境界、inline schema、Lambda設定、synth／diff／deploy後確認を記載し、コマンド表記を小文字の`cdk`へ揃える。Runtime Role→Gateway→Gateway Role→Target→Lambdaとinline schemaの関係を示す小さなMermaid図を追加する。
  - 完了条件: 本文と図が実装・CloudFormation・検証手順と一致し、Mermaid構文が正しく表示できる。
  - 依存: T130、T131
  - 対応: AC-006

- [ ] T203 [P] 実データ取得を後続要件としてbacklogへ整合させる
  - 対象: `specs/backlog/backlog.md`
  - 実施内容: 既存のユーザー差分を先に確認して上書きや重複を避け、本featureが固定モックだけを提供し、実天気／実時刻取得と高度な運用対応が後続要件であることを不足分だけ記録する。図は追加しない。
  - 完了条件: backlogが承認済み仕様、ADR-0002およびADR-0003と一致し、既存差分を保護している。
  - 依存: T002
  - 対応: AC-006

- [ ] T204 [P] ADR-0003の関連plan参照だけを更新する
  - 対象: `docs/ADR/adr-0003-use-dedicated-agentcore-gateway-for-weather-tools.md`
  - 実施内容: `Related plan`を`specs/05-agent-tool-weather-01/plan.md`へ更新する。決定本文と他の関連項目を変更せず、新しいADRを作成しない。
  - 完了条件: ADR-0003から承認済みplanへ辿れ、設計判断の内容に差分がない。
  - 依存: T003
  - 対応: AC-006

- [ ] T205 仕様・ADR・実装・テスト・文書の整合性をレビューする
  - 対象: `specs.md`、ADR-0002、ADR-0003、実装、テスト、`README.md`、`docs/Agent/README.md`、`docs/CDK/README.md`、`specs/backlog/backlog.md`
  - 実施内容: 構成、Tool名、環境変数、IAM境界、検証コマンド、モック制約、障害時動作および参照リンクを相互に照合する。
  - 完了条件: AC-006の対象間に矛盾、古い「Tool未実装」説明または無効なリンクがない。
  - 依存: T200、T201、T202、T203、T204
  - 対応: AC-006

## 条件付きAWS E2E

- [ ] T210 明示承認後にAWS差分を確認してdeployし、GatewayTargetの準備完了を確認する
  - 対象: 対象AWS accountの`us-east-2`、小文字の`cdk diff`、承認されたdeploy手順
  - 実施内容: ユーザーがAWS環境への変更と検証を明示的に依頼した場合だけ、`cdk diff`で意図しない削除・権限拡大がないことを確認し、承認された方法でdeployしてGatewayとGatewayTargetが`READY`になるまで確認する。T132／T133が未完了の場合は、その理由とリスクをユーザーへ示して追加の進行判断を得るまでdeployしない。
  - 完了条件: 明示承認の証跡があり、ローカル検証の未完了項目がないか追加判断済みで、差分がplanどおりであり、GatewayとTargetが`READY`である。明示依頼がない場合は実行せず未完了のままにする。
  - 依存: T134、T205。T132／T133が未完了の場合は追加の明示判断
  - 対応: AC-005

- [ ] T211 SigV4 MCP clientでGatewayと両Toolを直接検証する
  - 対象: deploy済み専用Gateway、`WeatherTimeMock___get_weather`、`WeatherTimeMock___get_time`
  - 実施内容: SigV4署名したMCP clientでinitializeし、応答protocol versionが`2025-11-25`であることを確認する。`tools/list`に接頭辞付き2 Toolが含まれることを確認し、Gateway組み込みToolは許容する。両`tools/call`がFR-003の固定値と`data_type="mock"`を返すことを確認する。
  - 完了条件: initialize、list、両callが成功し、応答が仕様と一致する。
  - 依存: T210
  - 対応: AC-003、AC-005

- [ ] T212 RuntimeからLambdaまでの実経路と安全なログを相関確認する
  - 対象: deploy済みAgentCore Runtime、専用Gateway、対象LambdaのCloudWatch Logsまたは`Invocations` metric
  - 実施内容: T211の直接call完了後にLambda log最新event時刻または`Invocations`をbaselineとして記録する。Runtimeへ天気と時刻の入力を送り、Managerが日本語で固定モックと明示する最終回答を確認した後、baseline以後の新しいLambda `START`／`END`または期待回数のmetric増加によりRuntime→Weather→Gateway→Lambda→Weather→Managerを相関確認する。Gateway／Lambda／Runtimeログにcredential、不要な入力および内部例外がないことも確認し、相関用の入力ログを追加しない。
  - 完了条件: 天気・時刻の最終回答と対象Lambdaの新規実行記録を同じ検証時間帯で対応付け、安全なログ方針も確認している。
  - 依存: T211
  - 対応: AC-003、AC-004、AC-005

- [ ] T213 AWS E2Eとローカル検証の実施状態を記録する
  - 対象: T132、T133、T210〜T212、実装完了報告
  - 実施内容: 明示依頼によりAWS E2Eを実施した場合は各結果を記録する。明示依頼がない場合はT210〜T212を未完了のまま保持し、理由を「AWS E2E未検証」と記録する。T132／T133も成功した場合だけ完了報告を「ローカル実装・検証済み／AWS E2E未検証」とし、Docker検証を実施できない場合は「ローカル自動テスト・synth済み／Docker・AWS E2E未検証」のように、実際に完了した範囲と未実施理由を記載する。
  - 完了条件: DockerとAWS E2Eの実施状態を過大申告せず、成功した項目、未実施項目および理由を区別している。
  - 依存: T134、T205。AWS E2Eを実施する場合はT210〜T212
  - 対応: AC-005

## 完了確認

- [ ] T300 受け入れ条件とタスク結果の対応を確認する
  - 対象: AC-001〜AC-006、本tasksの実施結果
  - 実施内容: AC-001をT100／T130、AC-002をT101／T102／T131、AC-003をT111／T113／T120と条件付きT211／T212、AC-004をT111／T112／T114／T115／T120／T121／T122／T131と条件付きT212、AC-005をT130〜T134および条件付きT210〜T213、AC-006をT200〜T205で確認する。
  - 完了条件: 各受け入れ条件について、成功した検証または明示された未実施項目を追跡でき、未確認項目を完了扱いしていない。
  - 依存: T130、T131、T205、T213。T132／T133は実施状態と未実施理由を確認する

- [ ] T301 planの実装方針・変更対象・対象外との一致を確認する
  - 対象: `specs/05-agent-tool-weather-01/plan.md`、本featureの全差分
  - 実施内容: 専用Gateway、固定モック、Agents-as-Tools、リクエスト単位MCP lifecycleおよびIAM境界に沿い、外部実データ、Handoff、共有Gateway、S3 schema、Policy／Interceptor、VPC、Observabilityおよび本番運用要件が混入していないことを確認する。
  - 完了条件: 差分が承認済みplanの変更対象に限定され、変更しないものを維持している。
  - 依存: T300

- [ ] T302 最終差分に不要物と秘密情報がないことを確認する
  - 対象: `git diff --check`、`git status --short`、tracked／untracked差分
  - 実施内容: feature外差分、ユーザーの既存差分への意図しない変更、Secret、認証情報、state、一時ファイル、`.DS_Store`、IDE設定、`cdk.out/`、cacheおよびその他生成物が成果物へ含まれないことを確認する。
  - 完了条件: Pull Request候補の差分に不要物や秘密情報がなく、既存の別差分を破壊または混在させていない。
  - 依存: T301

- [ ] T303 実施した検証結果と未実施理由を記録する
  - 対象: T004、T100〜T134、T210〜T213で実行したコマンドと結果
  - 実施内容: 成功・失敗したコマンド、対象テスト、synth、DockerおよびAWS E2Eの結果を区別し、未実施項目は対象と理由を記録する。
  - 完了条件: 実行していない検証を成功扱いせず、第三者が検証状態を確認できる。
  - 依存: T302

- [ ] T304 featureの完了状態を過大申告せず確定する
  - 対象: `specs.md`、`plan.md`、`tasks.md`、最終実装・テスト・文書差分
  - 実施内容: ローカル検証と文書整合の実施状態を確認する。AWS E2Eを実施した場合だけT210〜T212とAC-005のE2E部分を完了にし、未実施の場合は当該checkboxを残す。T132／T133を含むローカル必須検証がすべて成功した場合だけ「ローカル実装・検証済み／AWS E2E未検証」と報告し、Dockerその他の未実施項目がある場合は完了範囲と理由を個別に示す。
  - 完了条件: 実際の検証状態とtasksのcheckboxおよび完了報告が一致し、残タスクと理由が明確である。
  - 依存: T303
