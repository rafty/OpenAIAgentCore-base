# Tasks: Managed Knowledge Baseを利用するAWS Knowledge Agent

## 前提確認

- [x] T001 対象featureに適用される指示と既存差分を確認する
  - 対象: `AGENTS.md`、関連する`README.md`、`docs/`、Gitブランチ、作業ツリー
  - 実施内容: `06-rag-knowledge-agent-01`ブランチであること、適用される指示、既存のstaged／unstaged／untracked差分を確認し、本featureと無関係な差分を変更しない範囲を明確にする
  - 完了条件: 適用指示と保護対象の既存差分が記録され、`main`上で作業しておらず、対象外ファイルへ変更を加えない準備ができている
  - 依存: なし

- [x] T002 `specs.md`、`plan.md`および既存ADRのレビュー状態を確認する
  - 対象: `specs/06-rag-knowledge-agent-01/specs.md`、`specs/06-rag-knowledge-agent-01/plan.md`、`docs/ADR/adr-0002-*.md`から`docs/ADR/adr-0005-*.md`
  - 実施内容: スコープ、対象外、受け入れ条件、実装方針、未解決事項を確認する。ADR-0004とADR-0005は、statusを推測で変更せず、人のレビューにより採用済みであることを確認する
  - 完了条件: `specs.md`と`plan.md`が実装開始可能なレビュー状態であり、ADR-0004／0005の採用が人により確認されている。未承認または矛盾がある場合は実装へ進まず、上流成果物へ戻る理由が記録されている
  - 依存: T001

- [x] T003 [P] 固定依存で利用するCDK L1型とMCP APIを最小probeで確認する
  - 対象: `pyproject.toml`、`uv.lock`、`agents/requirements.txt`、`aws_cdk.aws_bedrock`、`aws_cdk.aws_bedrockagentcore`、既存MCP関連API
  - 実施内容: importと一時的な最小synthにより、Managed Knowledge Base、managed connector data source、Gateway Connector Target、token受渡し、asset API、SigV4 MCP APIのproperty名と生成shapeを確認する。probeだけを理由に依存ファイルは変更しない
  - 完了条件: 現在の固定versionで計画どおり実装可能であることが確認されている。成立しない場合は曖昧なdictや広範なescape hatchで回避せず、確認結果を記録して`plan.md`の見直しへ戻っている
  - 依存: T002

- [x] T004 [P] 変更前のローカル検証結果を記録する
  - 対象: `uv.lock`、既存テスト、CDKアプリケーション
  - 実施内容: `uv lock --check`、`uv run pytest`、`uv run python app.py`を実行し、既存失敗と生成物の有無を記録する
  - 完了条件: 各コマンドの成否と既存失敗が区別して記録され、`cdk.out/`等の生成物を編集またはコミット対象にしていない
  - 依存: T002

- [x] T005 [P] ナレッジ文書と変更境界の現状を確定する
  - 対象: `knowledge-base-s3/`、`agent_core_cdk_stack/`、`agents/src/agent_app/`、`tests/`、関連README
  - 実施内容: 5つのMarkdownと5つのsidecar metadataの正確な相対パス、既存Construct／Agent／テストの責務、変更しないHTTP・SSE・Memory・Weather契約を対応付ける
  - 完了条件: 登録対象10ファイルと各変更対象が一覧化され、仕様にないファイル、契約、AWSリソースを追加しない境界が明確になっている
  - 依存: T002

- [x] T006 更新されたリージョン移行要件とAWS初期状態を確認する
  - 対象: `specs/06-rag-knowledge-agent-01/specs.md`、`specs/06-rag-knowledge-agent-01/plan.md`、`docs/ADR/adr-0006-migrate-poc-to-us-east-1-before-decommissioning-us-east-2.md`、対象AWS profile
  - 実施内容: 承認済みのAC-009、ADR-0006のAccepted判断、PoC全体を`us-east-1`へ移行する範囲、bootstrap、新環境先行検証、旧環境削除条件を確認する。read-only照会で対象account、`us-east-1`の`CDKToolkit`未作成、旧`us-east-2` stackと`CDKToolkit`の状態を記録する
  - 完了条件: 対象account／profile、新旧region、stack名、bootstrap要否、削除禁止対象、新環境が失敗した場合に旧環境を保持するゲートが明確で、上流成果物に矛盾がない
  - 依存: T002、T133
  - 対応: AC-009
  - 実施結果: default profileがaccount `338456725408`を指すこと、`us-east-1`に`CDKToolkit`が存在しないこと、旧`us-east-2`の`OpenAiAgentCoreBaseStack`が`UPDATE_COMPLETE`、同リージョンの`CDKToolkit`がbootstrap version 32の`CREATE_COMPLETE`であることをread-onlyで確認した。ADR-0006の成功ゲートと削除禁止対象に矛盾はない

## 実装タスク

### ナレッジ文書配置

- [x] T010 [P] ナレッジ文書専用S3バケットと文書配置Constructを実装する
  - 対象: `agent_core_cdk_stack/constructs/knowledge_document_bucket_construct.py`
  - 実施内容: 公開遮断、SSE-S3、SSL強制、`RemovalPolicy.DESTROY`、object自動削除を持つ専用バケットを作成する。`knowledge-base-s3/`の通常ファイルをsynth前に列挙し、仕様の5 Markdownと対応する5 metadataだけに完全一致することを検証してから、相対パスを維持した`BucketDeployment`を`prune=True`、`retain_on_delete=False`で定義する
  - コメント（コードを変更する場合）: fail-fastする理由、専用bucketでroot pruneを許容する理由、相対パスとsidecar metadataの対応を維持する意図を日本語で説明する
  - 完了条件: 未知ファイル、欠落、重複または対応不一致をasset生成前に拒否し、正しい10ファイルだけを配置するConstructが公開されている。日本語コメントが設計判断を補い、コードの自明な読み替えになっていない
  - 依存: T003、T005
  - 対応: AC-003、AC-004

### Managed Knowledge Baseとデータソース

- [x] T020 [P] Managed Knowledge Baseと専用service roleを実装する
  - 対象: `agent_core_cdk_stack/constructs/managed_knowledge_base_construct.py`
  - 実施内容: `OpenAiKnowledgeBase`をtype `MANAGED`、embedding model type `MANAGED`で定義し、顧客管理Storage／Embedding／Rerankingを設定しない。Bedrockだけを条件付きで信頼するroleへ、専用bucketの`ListBucket`と`GetObject`だけを許可し、Knowledge Baseとroleの削除方針をPoC方針に合わせる
  - コメント（コードを変更する場合）: wildcardをKnowledge Base ARN種別内に限定する理由、service-managed embeddingで`InvokeModel`を付与しない理由、最小S3権限の境界を日本語で説明する
  - 完了条件: 固定名、MANAGED設定、条件付きtrust、最小S3読取権限、`RemovalPolicy.DESTROY`を持つConstructが公開され、不要なKMS／Secrets Manager／書込権限がない。日本語コメントが設計判断を補い、コードの自明な読み替えになっていない
  - 依存: T003、T005
  - 対応: AC-004

- [x] T021 Managed Knowledge Base用S3 Data Source Constructを実装する
  - 対象: `agent_core_cdk_stack/constructs/knowledge_data_source_construct.py`
  - 実施内容: `OpenAiKnowledgeDataSource`を`MANAGED_KNOWLEDGE_BASE_CONNECTOR`として定義し、S3 connector parameters、`DeletionProtectionStatus=ENABLED`、threshold `20`、`DataDeletionPolicy=DELETE`、`RemovalPolicy.DESTROY`を設定する。Managed Knowledge BaseとBucketDeploymentへの依存を明示し、Data Source IDを公開する
  - コメント（コードを変更する場合）: 削除保護20%の意味、追加prefixを設定しない理由、文書配置完了後にData Sourceを作成する必要性を日本語で説明する
  - 完了条件: 専用bucketだけを参照し、文書配置前に作成されず、同期Custom Resourceや定期同期を含まないData Source Constructが公開されている。日本語コメントが設計判断を補い、コードの自明な読み替えになっていない
  - 依存: T010、T020
  - 対応: AC-004

### Knowledge GatewayとRetrieve Target

- [x] T030 Knowledge専用AgentCore Gatewayと実行roleを実装する
  - 対象: `agent_core_cdk_stack/constructs/agent_core_knowledge_gateway_construct.py`
  - 実施内容: `OpenAiKnowledgeGateway`をIAM受信認証とMCP protocolで作成し、既存Weather Gatewayとは別の条件付きtrust roleを使用する。backend権限を対象Knowledge Base ARNの`bedrock:GetKnowledgeBase`と`bedrock:Retrieve`だけに限定する
  - コメント（コードを変更する場合）: Gateway分離の障害・権限上の意図、SourceArn条件の導出、`AgenticRetrieveStream`等を許可しない最小権限方針を日本語で説明する
  - 完了条件: 固定名のKnowledge専用Gatewayと最小権限roleが公開され、S3／Lambda／Secrets Manager／KMSまたはwildcard resourceへの不要な権限がない。日本語コメントが設計判断を補い、コードの自明な読み替えになっていない
  - 依存: T020
  - 対応: AC-005

- [x] T031 Retrieveだけを公開するKnowledge Gateway Targetを実装する
  - 対象: `agent_core_cdk_stack/constructs/knowledge_retrieve_gateway_target_construct.py`
  - 実施内容: L1 `CfnGatewayTarget`に`bedrock-knowledge-bases` Connector、Target名`KnowledgeRetrieve`、credential provider `GATEWAY_IAM_ROLE`、enabled operation `Retrieve`だけを設定する。Knowledge Base ID、`numberOfResults=5`、`HYBRID`を管理者固定とし、overrideはquery textとmetadata filterだけに限定する
  - コメント（コードを変更する場合）: L1利用範囲をConstruct内へ閉じる理由、固定値をモデルへ公開しない理由、IAM Policyを作成順の依存先にする理由を日本語で説明する
  - 完了条件: 公開Tool名が`KnowledgeRetrieve___Retrieve`となるTargetが作成され、`AgenticRetrieveStream`、`userContext`、件数やKnowledge Base IDのoverrideを公開していない。日本語コメントが設計判断を補い、コードの自明な読み替えになっていない
  - 依存: T030
  - 対応: AC-005

### Gateway設定とMCP adapter

- [x] T040 [P] WeatherとKnowledgeを分離したGateway設定を実装する
  - 対象: `agents/src/agent_app/config.py`
  - 実施内容: Gateway単位のURL、region、Target名を保持する設定構造を追加し、既存Weather環境変数の意味を維持したままKnowledge用`AGENTCORE_KNOWLEDGE_GATEWAY_URL`と`AGENTCORE_KNOWLEDGE_GATEWAY_TARGET_NAME`を読み込む。両URLとTarget名をstream開始前に既存制約で検証し、安全な設定エラーへ変換する
  - コメント（コードを変更する場合）: 既存環境変数をrenameしない互換性判断、Gateway単位で検証する理由、内部設定値をエラーへ露出しない意図を日本語で説明する
  - 完了条件: 2 Gatewayの有効な設定を独立参照でき、欠落、不正host／path／userinfo／port／query／fragment、不正Target名を安全に拒否する。日本語コメントが設計判断を補い、コードの自明な読み替えになっていない
  - 依存: T003、T005

- [x] T041 Knowledge Retrieve用MCP adapterと結果正規化を実装する
  - 対象: `agents/src/agent_app/gateway_tools.py`
  - 実施内容: 既存SigV4 transportと有限timeoutを再利用し、WeatherとKnowledgeのTool allowlistとavailabilityを分離する。`KnowledgeRetrieve___Retrieve`のqueryとfilterを再検証し、許可leaf、nest 2段、最大8条件に限定する。`CallToolResult`を検証し、chunk本文、bucket名を除く相対文書パス、許可metadata、任意scoreへ正規化する。空結果と取得不能を区別し、例外／不正結果／timeoutを内部詳細のない固定結果へ変換する
  - コメント（コードを変更する場合）: Gateway schemaに加えてadapterでも検証する防御理由、S3 URIから安全に相対パスを得る条件、空結果と障害を分ける理由、キャンセルを再送出する意図を日本語で説明する
  - 完了条件: 未知field、空query、不正filter、非TEXT、source欠落、競合表現をbackendまたはモデルへ通さず、S3 bucket名、Knowledge Base ID、Gateway URL、ARN、内部例外を結果へ含めない。日本語コメントが設計判断を補い、コードの自明な読み替えになっていない
  - 依存: T040
  - 対応: AC-002、AC-006

### Agent構成と複数Gatewayライフサイクル

- [x] T050 複数Gatewayの独立接続とcleanup／Memory境界を実装する
  - 対象: `agents/src/agent_app/service.py`
  - 実施内容: WeatherとKnowledgeのMCP instanceをリクエストごとに生成し、個別にconnect／tools list／availability判定する。片系障害後も他系を継続し、接続済みserverを逆順かつ有限時間でcleanupする。全cleanup成功後だけcommitと`completed`を行い、cleanup不能、全経路障害、例外ではrollbackと安全なSSE `error`、キャンセルではbest-effort cleanup／rollback後に元の例外を再送出する
  - コメント（コードを変更する場合）: 部分障害を局所化する状態管理、逆順cleanup、commitをcleanup後へ置く理由、キャンセルを握りつぶさない理由を日本語で説明する
  - 完了条件: server、Tool cache、availabilityをリクエスト間で共有せず、正常、部分障害、全障害、timeout、例外、キャンセルの全経路で接続リークと不正commitがない。日本語コメントが設計判断を補い、コードの自明な読み替えになっていない
  - 依存: T041
  - 対応: AC-006

- [x] T051 [P] AWS Knowledge AgentとManagerのルーティングを実装する
  - 対象: `agents/src/agent_app/agent_factory.py`
  - 実施内容: `AgentBundle`へAWS Knowledge Agentを追加し、Managerの直接Toolを`weather_agent`と`aws_knowledge_agent`に限定する。WeatherへWeather MCPだけ、KnowledgeへKnowledge MCPだけを渡し、全handoffを空に保つ。日本語instructionsへ担当範囲、複合質問、Retrieve必須、根拠文書、捏造禁止、空結果／障害の区別、検索結果内命令の非実行、見積の式・単位・根拠を定義する
  - コメント（コードを変更する場合）: Managerが会話と最終回答を所有する理由、MCPを専門Agentだけへ閉じる境界、利用不能な専門AgentもToolとして保つ理由を日本語で説明する
  - 完了条件: Manager／Weather／Knowledgeの3 Agent構成が作成され、2 Gatewayの4通りの利用可否で安全に動作し、ManagerがMCPを直接保持せず、Handoffが追加されていない。日本語コメントが設計判断を補い、コードの自明な読み替えになっていない
  - 依存: T040、T041
  - 対応: AC-001、AC-002

- [x] T052 Runtimeの依存注入を2 Gateway対応へ更新する
  - 対象: `agents/src/agent_app/runtime.py`
  - 実施内容: Weather／KnowledgeそれぞれのMCP factoryと更新後のAgent factoryをserviceへ注入し、モデルだけを再利用しながらMCP serverとAgent bundleをRuntime呼び出しごとに生成する。既存のHTTP入力、SSE、Memory、初期化エラー境界を維持する
  - コメント（コードを変更する場合）: モデルとリクエストスコープresourceの寿命を分ける理由、factory分離がテストと障害局所化に必要な理由を日本語で説明する
  - 完了条件: 2 GatewayのfactoryをFakeへ置換可能で、リクエスト間にMCP／Agent状態が残らず、既存Runtime公開契約が変わっていない。日本語コメントが設計判断を補い、コードの自明な読み替えになっていない
  - 依存: T050、T051
  - 対応: AC-006

### CDK stackとRuntime配線

- [x] T060 Knowledge関連Construct、Runtime環境変数、IAMおよびOutputをstackへ接続する
  - 対象: `agent_core_cdk_stack/constructs/agent_core_runtime_construct.py`、`agent_core_cdk_stack/agent_core_stack.py`
  - 実施内容: 文書bucket／deployment、Managed Knowledge Base、Data Source、Knowledge Gateway／Targetを責務順に生成し、RuntimeへKnowledge Gateway URL／Target名を非秘密環境変数として渡す。Runtime roleへKnowledge Gatewayだけの`InvokeGateway`を追加し、Weather権限を維持する。Runtimeを両Targetへ依存させ、初回同期用Knowledge Base IDとData Source IDだけをCloudFormation Outputへ追加する
  - コメント（コードを変更する場合）: Construct間の作成順、RuntimeがKnowledge BaseやS3へ直接アクセスしない権限境界、同期をdeployから分離するOutputの用途を日本語で説明する
  - 完了条件: 既存Weather／Memory／Runtime契約を維持したstackにKnowledge経路が接続され、Runtimeに余分なBedrock／S3権限や同期Custom Resourceがなく、固定名と環境変数が計画と一致する。日本語コメントが設計判断を補い、コードの自明な読み替えになっていない
  - 依存: T021、T031、T040
  - 対応: AC-004、AC-005

- [x] T061 PoC全体の固定リージョンを`us-east-1`へ変更する
  - 対象: `app.py`、`agents/src/agent_app/config.py`
  - 実施内容: CDK stackの`cdk.Environment.region`、Agentの固定AWS region、AgentCore Gateway host suffixを`us-east-1`へ統一する。Runtime、Memory、Weather／Knowledge Gateway、Lambda、Managed Knowledge Base、S3および関連IAMを同一stack・同一regionへ配置し、旧`us-east-2`または他regionのGateway URLを設定エラーとして拒否する
  - コメント（コードを変更する場合）: Managed Knowledge Base対応リージョンへPoC全体を移す理由、複数リージョンへ分割しない理由、Gateway URLの署名regionとhostを一致させる必要性を日本語で説明する
  - 完了条件: `app.py`とAgent設定の固定regionが`us-east-1`で一致し、regionをまたぐresource参照や旧region URLの受理がなく、既存HTTP／SSE／Memory／Weatherの論理契約を変更していない。日本語コメントが設計判断を補い、コードの自明な読み替えになっていない
  - 依存: T006、T060
  - 対応: AC-006、AC-009
  - 実施結果: `app.py`、Agent設定、Runtime環境変数を`us-east-1`へ統一し、Gateway host suffixも同リージョンへ変更した。Managed Knowledge Baseとモデルを同一リージョンへ置く理由とcross-regionを避ける理由を日本語コメントで記録し、実装領域に旧`us-east-2`固定値が残っていないことを確認した

## テスト / 検証タスク

### ナレッジ文書とCDK単体検証

- [x] T100 [P] ナレッジ文書とsidecar metadataの契約テストを追加する
  - 対象: `tests/unit/test_knowledge_documents.py`、`knowledge-base-s3/`
  - 実施内容: 5 Markdown＋5 metadataの完全一致、UTF-8、JSON shape、型、許可値、一対一対応、仕様固有値、登録対象外ファイル、秘密情報らしき値の非混入を決定的に検証する
  - 完了条件: 仕様の標準値、監視値、見積値、過去案件値とmetadataを自動検証し、追加・欠落・不正ファイルで失敗する
  - 依存: T005
  - 対応: AC-003

- [x] T101 [P] S3バケット、assetおよびBucketDeploymentを単体検証する
  - 対象: `tests/unit/test_knowledge_base_gateway_stack.py`、`agent_core_cdk_stack/constructs/knowledge_document_bucket_construct.py`
  - 実施内容: 公開遮断、SSE-S3、SSL、削除方針、`prune`、`retain_on_delete`、相対path、10ファイル限定、内容hashによる更新検知、生成物非混入、fail-fastを検証する
  - 完了条件: 一時出力先でasset内容を検査し、仕様外ファイルやpath変換を見逃さず、通常のリポジトリ生成物をコミット対象にしない
  - 依存: T010
  - 対応: AC-003、AC-004

- [x] T102 [P] Managed Knowledge BaseとData Sourceを単体検証する
  - 対象: `tests/unit/test_knowledge_base_gateway_stack.py`
  - 実施内容: MANAGED設定、service-managed embedding、Storage設定なし、service role trust、S3最小権限、managed connector、削除保護20、DataDeletionPolicy、Removal Policy、BucketDeployment依存、同期Custom ResourceなしをCloudFormation assertionで検証する
  - 完了条件: 計画したresource shapeと依存関係が固定され、カスタムVector Store、Embedding権限、過剰IAM、予定外の同期resourceを検出できる
  - 依存: T020、T021
  - 対応: AC-004

- [x] T103 [P] Knowledge GatewayとRetrieve Targetを単体検証する
  - 対象: `tests/unit/test_knowledge_base_gateway_stack.py`
  - 実施内容: GatewayのIAM認証／MCP、条件付きtrust、対象Knowledge Baseだけの`GetKnowledgeBase`／`Retrieve`、Connector source、Retrieveだけのenabled operation、固定値、限定override、TargetとIAM Policyの依存を検証する
  - 完了条件: `KnowledgeRetrieve___Retrieve`だけが公開され、`AgenticRetrieveStream`、`userContext`、管理者固定値のoverride、wildcard backend権限が存在しない
  - 依存: T030、T031
  - 対応: AC-005

- [x] T104 CDK stackとRuntime配線の回帰テストを更新する
  - 対象: `tests/unit/test_open_ai_agent_core_base_stack.py`
  - 実施内容: Knowledge環境変数、両Gatewayへの限定`InvokeGateway`、両Targetへの依存、同期用Output、既存Memory／Runtime／Weather／Docker asset契約を検証する
  - 完了条件: Knowledge経路の追加と既存resource契約の維持を同時に検証し、Runtime roleからKnowledge Base／S3への直接権限を検出できる
  - 依存: T060
  - 対応: AC-004、AC-005、AC-008

### Agent単体検証

- [x] T110 [P] 2 Gateway設定と後方互換性の単体テストを追加する
  - 対象: `tests/unit/agent/test_config.py`
  - 実施内容: Weather／KnowledgeのURLとTarget名、欠落、不正値、安全な設定エラー、既存Weather環境変数の互換性を検証する
  - 完了条件: 両設定の正常系と境界値が網羅され、内部URLやTarget名を外部エラーへ露出しない
  - 依存: T040

- [x] T111 [P] Knowledge MCP adapterの入力・結果・障害を単体検証する
  - 対象: `tests/unit/agent/test_gateway_tools.py`
  - 実施内容: Tool allowlist、非空query、filter属性／演算子／nest／件数、未知parameter、空／正常／不正結果、相対文書path、metadata allowlist、bucket名除去、Tool error、timeout、キャンセル、SigV4設定をFakeで検証する
  - 完了条件: backendを呼ばない拒否経路、空検索と取得不能の区別、内部AWS値を含まないcanonical結果を決定的に確認できる
  - 依存: T041
  - 対応: AC-002、AC-006

- [x] T112 [P] 3 Agent構成とルーティングinstructionsを単体検証する
  - 対象: `tests/unit/agent/test_agent_factory.py`
  - 実施内容: Managerの直接Tool、専門AgentごとのMCP境界、Handoffなし、4通りのGateway利用可否、担当領域、複合利用、根拠提示、捏造禁止、prompt injection非実行、見積計算条件を検証する
  - 完了条件: Manager、Weather、Knowledgeの責務と公開Tool名が固定され、ManagerにMCP serverが直接登録されていない
  - 依存: T051
  - 対応: AC-001、AC-002

- [x] T113 複数Gatewayのservice／runtimeライフサイクルを単体検証する
  - 対象: `tests/unit/agent/test_service.py`、`tests/unit/agent/test_runtime.py`
  - 実施内容: 2 Gatewayのconnect／list／run／逆順cleanup、片系・両系障害、cleanup失敗、timeout、キャンセル、commit／rollback、factory注入、モデル再利用、MCP／Agentのリクエスト単位生成をFakeで検証する
  - 完了条件: 全分岐でcleanup回数、順序、Memory確定状態、例外伝播が期待どおりで、リクエスト間リークがない
  - 依存: T050、T052
  - 対応: AC-006

### 結合検証とRuntime回帰

- [x] T120 決定的な複数Agent結合テストを追加する
  - 対象: `tests/integration/agent/test_multi_agent.py`
  - 実施内容: 実AWSを呼ばないModel／MCP test doubleで、AWS標準、監視、見積、過去案件、工数計算、metadata filter、空結果、命令形式データ、Weather＋Knowledge複合質問、片系・両系障害を検証する
  - 完了条件: AC-001とAC-002の具体例を含む回答、文書根拠、計算結果、prompt injection非実行、空結果／障害の安全な回答が決定的に再現される
  - 依存: T111、T112、T113
  - 対応: AC-001、AC-002、AC-006

- [x] T121 Runtime HTTP／SSE／Memory境界の結合回帰テストを更新する
  - 対象: `tests/integration/agent/test_runtime_http.py`、`tests/container/harness_main.py`、`tests/container/test_harness.py`
  - 実施内容: 更新したfactory signatureへFakeを追従させ、入力、`GET /ping`、SSE `text_delta`／`completed`／`error`、HTTP error、Memory、依存初期化境界を実AWSなしで検証する
  - 完了条件: Knowledge統合後も既存HTTP／SSE／Memory契約が変わらず、コンテナharnessが外部AWS接続なしで完結する
  - 依存: T052、T113
  - 対応: AC-006、AC-008

### `us-east-1`リージョン契約の再検証

- [x] T122 [P] CDK stackの固定リージョンを単体検証する
  - 対象: `tests/unit/test_open_ai_agent_core_base_stack.py`、`app.py`
  - 実施内容: stackが`us-east-1`としてsynthされ、Runtime、Memory、Weather／Knowledge Gateway、Lambda、Managed Knowledge Base、S3およびIAMが単一stackに含まれることを検証する。template、ARN、endpointまたは期待値に旧`us-east-2`前提が残っていないことも検証する
  - 完了条件: `us-east-1`の単一stack構成を決定的に検証でき、Knowledge経路だけを別regionへ分割する回帰を検出できる
  - 依存: T061、T104
  - 対応: AC-004、AC-005、AC-009
  - 実施結果: CDK関連3テストのregion fixtureと期待値を`us-east-1`へ更新し、通常環境で8テストが成功した。sandbox内の初回実行はjsii package cacheへの`utime`が拒否されたため、同一コマンドを承認済み通常環境で再実行している

- [x] T123 [P] Agent設定の`us-east-1` Gateway URL契約を単体検証する
  - 対象: `tests/unit/agent/test_config.py`
  - 実施内容: Weather／Knowledgeの`us-east-1` Gateway URLを受理し、旧`us-east-2`とその他regionのhost、署名region不一致、既存の不正URL／Target名を安全に拒否することを検証する
  - 完了条件: 2 Gatewayの正常値とregion境界が網羅され、内部URLを外部エラーへ露出せず、既存環境変数名の互換性が維持されている
  - 依存: T061、T110
  - 対応: AC-006、AC-009
  - 実施結果: Agent、integration、container harnessのregion fixtureを`us-east-1`へ更新し、`test_config.py`の52テストが成功した。正常な`us-east-1` URLを受理し、旧`us-east-2`のAWS regionとGateway hostを負例として安全に拒否することを確認した

### 静的検証、buildおよびリージョン移行前の再確認

- [x] T130 ロック整合性、全テスト、CDK synthおよび生成templateを検証する
  - 対象: `uv.lock`、全テスト、CDK app、CloudFormation template、CDK asset
  - 実施内容: `uv lock --check`、`uv run pytest`、`uv run python app.py`を実行し、生成templateとassetから固定名、resource shape、IAM、依存関係、10ファイル限定、同期Custom Resourceなしを確認する
  - 完了条件: 全コマンドが成功し、CloudFormation／assetが仕様と計画に一致し、`cdk.out/`等の生成物が差分へ含まれていない
  - 依存: T100、T101、T102、T103、T104、T110、T111、T112、T113、T120、T121
  - 対応: AC-003、AC-004、AC-005、AC-006、AC-008

- [x] T131 Linux／arm64コンテナをbuildしRuntime契約を検証する
  - 対象: Runtime Docker image、`tests/container/`
  - 実施内容: リポジトリで定義されたLinux／arm64 build手順でimageを作成し、外部AWSへ接続しないharnessでprocess起動、`GET /ping`、`POST /invocations`、SSE終端を確認する
  - 完了条件: buildとharnessが成功し、固定依存のimport、Runtime起動、既存HTTP／SSE契約を実行環境相当で確認できる
  - 依存: T130
  - 対応: AC-008
  - 実施結果: Rancher DesktopのDockerで`linux/arm64` imageをbuildし、imageが`os=linux`、`arch=arm64`、`user=agent`であることを確認した。固定依存5件とRuntime／Gateway factoryのimport、`GET /ping`、無効入力のHTTP 400、正常SSEの`text_delta`→`completed`、異常SSEの`text_delta`→安全な`error`終端が成功した

- [x] T124 リージョン変更後のローカル回帰、synthおよびLinux／arm64 buildを再実行する
  - 対象: `uv.lock`、全テスト、CDK app、CloudFormation template、CDK asset、Runtime Docker image、`tests/container/`
  - 実施内容: `uv lock --check`、`uv run pytest`、`uv run python app.py`、生成template／asset検査、Linux／arm64 Docker build、container harnessを再実行する。templateの対象region、Knowledge resource shape、IAM、10ファイル、HTTP／SSE契約を確認する
  - 完了条件: 全コマンドが成功し、templateとassetが`us-east-1`の計画に一致し、imageがLinux／arm64・非rootで動作し、生成物が差分へ含まれていない
  - 依存: T122、T123、T130、T131
  - 対応: AC-003、AC-004、AC-005、AC-006、AC-008、AC-009
  - 実施結果: `uv lock --check`、全240テスト、`uv run python app.py`、一時出力先への`cdk synth`が成功した。template environmentは`aws://338456725408/us-east-1`で旧region固定値がなく、Knowledge assetは相対pathの10ファイルだけ、Docker assetは`linux/arm64`だった。Rancher Desktopでimageを再buildし、`linux arm64 agent`、`GET /ping`、HTTP 400、正常SSE `text_delta`→`completed`、異常SSE `text_delta`→安全な`error`を実コンテナで確認した。生成物はignoredのままである

- [x] T133 未実施または失敗した検証と理由を記録する
  - 対象: 本featureで計画したローカル検証、コンテナ検証、AWS検証
  - 実施内容: 実行コマンド、結果、失敗が変更前から存在したか、環境制約、権限不足、明示承認なし等の理由、残る確認事項を区別して記録する
  - 完了条件: 実行していない検証を成功扱いせず、レビュー担当者がローカル確認済み範囲とAWS未確認範囲を判別できる
  - 依存: T130、T131
  - 実施結果: 変更前は`uv lock --check`、`uv run pytest`（177 passed）、`uv run python app.py`が成功した。変更後は`uv lock --check`、`uv run pytest`（240 passed）、`uv run python app.py`が成功し、一時出力先のsynth templateとassetでKnowledge関連resource、IAM、依存、同期Custom Resourceなし、正確な10ファイルを確認した。Rancher DesktopでLinux／arm64 image build、固定依存import、非root起動、`GET /ping`、入力エラー、正常／異常SSEのコンテナ契約も成功した
  - AWS検証結果: default profileのaccount `338456725408`、`us-east-2`でCDK bootstrap version 32と既存stackの`UPDATE_COMPLETE`を確認した。`cdk diff`のtemplate差分は計画したKnowledge resourceと限定IAMを示したが、CloudFormation change setはManaged Knowledge Baseとmanaged connectorが同リージョンで未サポートのため早期検証に失敗した。`cdk deploy`、初回同期、Gateway／Runtime E2Eは実行していない
  - 差分確認: 今回更新した`tasks.md`の`git diff --check`は成功した。全体の`git diff --check`は作業開始前から保護している`specs/06-rag-knowledge-agent-01/prompts.md`の末尾空白4件で失敗するため、feature実装の成功とは区別して残している
  - 未実施範囲: 旧計画の`us-east-2`ではManaged Knowledge Baseを利用できず、`cdk deploy`、AWS初回同期、Gateway／Runtime E2Eは未確認である。この記録はリージョン移行前の履歴として維持し、更新後計画の結果はT142で記録する

## ドキュメント更新タスク

- [x] T200 ルートREADMEのPoC概要と検証入口を更新する
  - 対象: `README.md`
  - 実施内容: Manager、Weather、AWS Knowledge Agent、2 Gateway、Managed Knowledge Baseの構成、主要設定、ローカル検証コマンド、AWS操作には明示承認が必要であることを現在の実装に合わせて記載する
  - 完了条件: READMEが実装済みの公開挙動とコマンドに一致し、未実装または未検証のAWS動作を完了済みとして記載していない
  - 依存: T060、T120、T130
  - 対応: AC-007、AC-008

- [x] T201 Agentの構成、Retrieve契約およびライフサイクルを文書化する
  - 対象: `docs/Agent/README.md`
  - 実施内容: 3 Agentの責務、Agent-as-Tool、Knowledge設定、Retrieve入力／filter／結果正規化、根拠提示、prompt injection対策、2 MCPの接続・独立障害・cleanup／commit順序、ローカル検証とRuntime E2Eを記載する。関係と処理順を文章だけで把握しにくい箇所はMermaid図を追加または更新する
  - 完了条件: 文書と実装／テストが一致し、Mermaid図を変更した場合は目的が明確で本文と整合し、構文を検証して正しく表示できる
  - 依存: T041、T050、T051、T052、T120、T121
  - 対応: AC-001、AC-002、AC-006、AC-007、AC-008

- [x] T202 CDK構成、初回同期およびAWS E2E手順を文書化する
  - 対象: `docs/CDK/README.md`
  - 実施内容: Knowledge関連Construct、固定名、S3配置、Managed Knowledge Base、Data Source、Gateway Connector、IAM、Removal Policy、synth確認を記載する。CloudFormation OutputからIDを解決し、対象profile／account／regionを確認してingestion jobを開始・監視し、`COMPLETE`後だけRetrieve／Runtime E2Eへ進む手順を記載する。resource関係と同期フローはMermaid図で示す
  - 完了条件: 手順が実装されたOutputとAWS CLIに一致し、deployと同期が分離され、失敗／停止時の確認事項と明示承認条件が記載されている。Mermaid図が本文と整合し、構文を検証して正しく表示できる
  - 依存: T010、T020、T021、T030、T031、T060、T130
  - 対応: AC-004、AC-005、AC-007、AC-008

- [x] T203 採用済みADRの関連SDDリンクだけを更新する
  - 対象: `docs/ADR/adr-0004-use-managed-knowledge-base-retrieve-via-dedicated-gateway.md`、`docs/ADR/adr-0005-deploy-knowledge-documents-with-cdk-and-sync-after-deploy.md`
  - 実施内容: T002で人による採用を確認したADRについて、判断本文とstatusを変更せず、`Related plan`等の関連情報を本featureの`plan.md`と`tasks.md`へ接続する。新しい設計判断を追加しない
  - 完了条件: ADRの判断、理由、statusを推測で変更せず、SDD成果物への参照だけが正しく更新されている。新しい重要判断が必要になった場合はこのタスクで追記せず、`create-adr` skillを使用する別依頼が必要であることを記録している
  - 依存: T002、T060

- [x] T204 [P] ルートREADMEとAgent文書を`us-east-1`配置へ更新する
  - 対象: `README.md`、`docs/Agent/README.md`
  - 実施内容: PoC全体の対象region、2 GatewayのURL／署名region、bootstrap前提、Runtime E2Eの対象を`us-east-1`へ更新する。既存のAgent構成図や接続フローを変更する場合は、単一region構成と本文が一致するようMermaid図も更新する
  - 完了条件: 実装済みAgent／Gateway契約と`us-east-1`配置が文書で一致し、旧`us-east-2`を現行deploy先として案内していない。Mermaid図を変更した場合は本文と整合し、構文が正しく表示できる
  - 依存: T061、T124、T200、T201
  - 対応: AC-007、AC-008、AC-009
  - 実施結果: ルートREADMEとAgent文書の現行deploy先、環境変数、Gateway URL検証、bootstrap、Runtime ARN例、モデル確認を`us-east-1`へ更新した。Agent文書の削除節は新stackの`cdk destroy`を案内せず、新環境の全E2E成功後だけCDK文書の旧`us-east-2`廃止手順へ進む内容に変更した。既存Mermaidの論理構成はregion非依存で本文と整合するため変更していない

- [x] T205 [P] CDK文書へbootstrap、移行E2Eおよび旧環境廃止手順を追加する
  - 対象: `docs/CDK/README.md`
  - 実施内容: STSによるaccount／profile確認、`us-east-1`の`CDKToolkit`確認とbootstrap、CloudFormation事前検証、deploy、S3、初回同期、Gateway／Runtime E2E、新環境成功ゲート、旧`us-east-2` stackのCloudFormation削除、残存監査、`us-east-1`の`CDKToolkit`維持、旧`CDKToolkit`の不存在を許容する方針、復旧不能データを具体的なコマンド順で記載する。移行の成功／失敗分岐と削除順序はMermaidフローで示す
  - 完了条件: `app.py`を`us-east-1`へ変更した後でも旧stackだけを誤りなく削除でき、失敗時は旧環境を保持する手順になっている。監査APIとPoC識別条件がplanと一致し、Mermaid図が本文と整合して正しく表示できる
  - 依存: T006、T061、T124、T202
  - 対応: AC-007、AC-008、AC-009
  - 実施結果: 現行deploy先を`us-east-1`へ更新し、STS確認、`CDKToolkit`の事前確認とbootstrap、CloudFormation事前検証、deploy、10 object、初回同期、Gateway／Runtime E2E、新環境成功ゲート、旧`us-east-2` stackのCloudFormation削除、残存監査を具体的な順序とコマンドで記載した。現行`us-east-1`の`CDKToolkit`だけを維持対象とし、旧`us-east-2`の`CDKToolkit`は不存在でも失敗とせず再bootstrapしない方針へ更新した。失敗時に旧環境を保持する分岐と削除順序をMermaidで示し、旧Memory／S3／ログ等が復旧不能であること、名前だけ一致するstack外resourceを自動削除しないことも明記した

## AWSリージョン移行、E2Eおよび旧環境廃止

- [x] T132 `us-east-1`をCDK bootstrapする
  - 対象: 対象AWS account／profile、`us-east-1`の`CDKToolkit`
  - 実施内容: STS caller identityでaccountを確認し、`us-east-1`の`CDKToolkit`が未作成であることを再確認する。`cdk bootstrap aws://<確認済みaccount>/us-east-1 --profile <確認済みprofile>`を実行し、CloudFormation stack状態、bootstrap version、file assetとLinux／arm64 container image assetの基盤を確認する
  - 完了条件: `us-east-1`の`CDKToolkit`が`CREATE_COMPLETE`または`UPDATE_COMPLETE`で、後続のtemplate／file／container image assetを利用できる。別account／regionへbootstrapしておらず、新環境の成功前に旧`us-east-2` stackを削除していない
  - 依存: T006、T124、T204、T205
  - 対応: AC-009
  - 実施結果: profile `default`のSTS caller identityがaccount `338456725408`であること、`us-east-1`に`CDKToolkit`が未作成であることを再確認し、`cdk bootstrap aws://338456725408/us-east-1 --profile default`を実行した。stackは`CREATE_COMPLETE`、bootstrap version 32で、file asset用S3 bucketとLinux／arm64 container image asset用ECR repositoryはいずれも`CREATE_COMPLETE`だった。旧`us-east-2`のPoC stackは`UPDATE_COMPLETE`、同regionの`CDKToolkit`はversion 32の`CREATE_COMPLETE`で維持されている

- [x] T134 `us-east-1`のCloudFormation事前検証を伴う`cdk diff`を実行する
  - 対象: `OpenAiAgentCoreBaseStack`、`us-east-1`、CloudFormation read-only change set
  - 実施内容: `app.py`の固定region、対象account／profile／stackを再確認して`cdk diff`を実行し、Managed Knowledge Baseの`MANAGED`とData Sourceの`MANAGED_KNOWLEDGE_BASE_CONNECTOR`がresource schemaに受理されることを確認する。新規resource、IAM拡張、S3削除設定、Removal Policy、意図しない削除も確認する
  - 完了条件: CloudFormation事前検証が成功し、差分が承認済みspecs／planの`us-east-1`単一stackに限定されている。失敗時はdeployと旧環境削除へ進まず、理由を記録している
  - 依存: T132
  - 対応: AC-004、AC-005、AC-009
  - 実施結果: `app.py`、Runtime環境変数、2 Gateway hostが`us-east-1`であることとRancher Desktop／Docker daemonの稼働を再確認し、account `338456725408`、profile `default`で`cdk diff OpenAiAgentCoreBaseStack`を実行した。CloudFormation read-only change setは成功し、全resourceが新規追加で意図しない削除はなかった。生成templateでもKnowledge Baseの`MANAGED`、Data Sourceの`MANAGED_KNOWLEDGE_BASE_CONNECTOR`と`DataDeletionPolicy=DELETE`、Knowledge resourceのDelete方針、Retrieve限定IAM、RuntimeのGateway限定権限を確認した。Node.js 20の非推奨警告は出たが事前検証の成否には影響していない

- [x] T135 `us-east-1`へ新stackをdeployして基盤状態を確認する
  - 対象: `OpenAiAgentCoreBaseStack`、CloudFormation、S3、stack Output
  - 実施内容: 確認済みprofileで`cdk deploy OpenAiAgentCoreBaseStack --require-approval broadening`相当を実行する。stackが正常状態であること、S3に5 Markdown＋5 metadataが相対keyで配置されたこと、Knowledge Base IDとData Source IDをOutputから取得できることを確認する
  - 完了条件: `us-east-1`の新stackが正常で、10 objectと同期用IDを確認できる。deploy失敗時は旧`us-east-2` stackを保持し、後続へ進んでいない
  - 依存: T134
  - 対応: AC-003、AC-004、AC-005、AC-007、AC-009
  - 実施結果: account `338456725408`、profile `default`、region `us-east-1`で、IAM broadeningの内容を確認して`cdk deploy OpenAiAgentCoreBaseStack --require-approval broadening`を実行した。RuntimeのLinux／arm64 imageおよびfile assetを新regionのbootstrap基盤へ公開し、stack ARN `arn:aws:cloudformation:us-east-1:338456725408:stack/OpenAiAgentCoreBaseStack/1888add0-9afd-11f1-a2c8-0e37afc4c625`が`CREATE_COMPLETE`になった。OutputからKnowledge Base ID `VHSORZ3CDD`とData Source ID `FOK03YSKVP`を取得し、Knowledge bucketに相対pathの5 Markdown＋5 metadata、合計10 objectがあることを確認した。旧`us-east-2` stackは`UPDATE_COMPLETE`で保持している

- [x] T136 Managed Knowledge Baseの初回同期を完了する
  - 対象: `us-east-1`のManaged Knowledge Base、Data Source、S3文書
  - 実施内容: OutputのIDを使用してingestion jobを一度開始し、同じjob IDを監視する。`COMPLETE`を成功とし、`FAILED`／`STOPPED`時は`failureReasons`、statistics、S3配置を記録して無条件再実行しない
  - 完了条件: ingestion jobが`COMPLETE`で5文書とsidecar metadataを検索可能な状態にしている。成功前にGateway Tool／Runtime E2Eまたは旧環境削除へ進んでいない
  - 依存: T135
  - 対応: AC-003、AC-007、AC-009
  - 実施結果: Data Source `FOK03YSKVP`が`AVAILABLE`かつ既存ingestion jobが0件であることを確認し、Knowledge Base `VHSORZ3CDD`にclient token `feature06-initial-ingestion-00000001`で初回job `OTXDVIO8B6`を一度だけ開始した。同じjob IDを監視して`COMPLETE`を確認し、5文書と5 metadataをscan、5文書を新規index、失敗0件、failure reasonなしだった。完了前にGateway／Runtime E2Eや旧環境削除へ進んでいない

- [x] T137 Knowledge GatewayとRetrieve ToolをE2E検証する
  - 対象: `us-east-1`の`OpenAiKnowledgeGateway`、`KnowledgeRetrieve`、SigV4 MCP
  - 実施内容: GatewayとTargetの状態を確認し、SigV4 MCP `initialize`、`tools/list`、`tools/call`を実行する。`KnowledgeRetrieve___Retrieve`だけが対象connectorから公開され、仕様固有値、source、`document_type`／`environment`／`service` filter、空結果が期待どおりであることを確認する
  - 完了条件: Targetが`READY`でRetrieveとmetadata filterが成功し、利用者またはモデル可視結果へbucket名、Knowledge Base ID、Gateway URL、ARN、内部例外が漏れていない。失敗時は旧環境を保持している
  - 依存: T136
  - 対応: AC-002、AC-005、AC-007、AC-009
  - 実施結果: `OpenAiKnowledgeGateway`とTarget `KnowledgeRetrieve`が`READY`であることを確認し、profile `default`の標準AWS認証情報チェーンによるSigV4 MCPで`initialize`のprotocol `2025-11-25`、`tools/list`の`KnowledgeRetrieve___Retrieve` 1件だけを確認した。初回callでCloudFormation resource providerが`parameterValues.numberOfResults`の数値5を文字列`"5"`へ変換しBedrock型検証に失敗することを実resourceで特定したため、Bedrock既定の5件を使いモデルへのoverrideを非公開のままにする互換修正を実装し、Targetをin-place更新した。また、Managed Knowledge Base実応答のS3 locationがvirtual-hosted HTTPS URIであることを確認し、S3 hostだけを許可してbucket名を除く正規化と回帰テストを追加した。関連53テスト成功後、通常検索、`document_type`／`environment`／`service` filter、空結果が成功し、固有値と許可された相対sourceを確認した。canonical結果にbucket名、Knowledge Base ID、Gateway URL、ARN、内部例外がないこともassertしている

- [x] T138 AgentCore RuntimeのWeather／Knowledge／複合質問をE2E検証する
  - 対象: `us-east-1`のAgentCore Runtime、Memory、Weather／Knowledge Gateway
  - 実施内容: Runtimeへ社内標準、見積、過去案件、Weather、Knowledge＋Weather複合質問、空検索相当を送り、Manager最終回答、根拠文書、計算、捏造なし、独立障害、HTTP／SSE／Memory境界を確認する
  - 完了条件: Weather、Knowledge、複合質問を含むE2Eが成功し、検索結果にない社内値を補完せず、認証情報や内部AWS識別子を応答へ含めない。失敗時は旧環境を保持している
  - 依存: T137
  - 対応: AC-001、AC-002、AC-006、AC-007、AC-009
  - 実施結果: Runtime version 5、Memory `ACTIVE`、Weather／Knowledge Gatewayと両Target `READY`を確認した。実モデルの初回Knowledge呼び出しで、任意の`retrievalConfiguration`／`managedSearchConfiguration`を空objectとして生成する場合にadapterが拒否することを値や例外を記録しない障害分類ログで特定し、空表現だけを設定なしへ正規化する互換修正と回帰テストを追加した。最終Runtimeへ標準、見積、過去案件、Weather、複合、該当なし、同一actor／sessionのMemory継続を送信し、全8応答がHTTP 200、1件以上の`text_delta`、`completed` 1件、`error` 0件で成功した。標準回答はCPU 80%／90%・5分継続、ログ90日と`standards/monitoring_standard.md`、見積は`4台×0.5人日 + 1DB×1.0人日 = 3.0人日`と`estimation/estimation_guideline.md`、過去案件は構成・8.0人日と`projects/sample_project_alpha.md`、Weatherは晴れ・72°Fを固定モックと明示し、複合回答は両経路を統合した。存在しない`document_type`は「該当情報なし」として補完せず、Memoryは検証名「ミズキ」を復元した。応答を連結してaccount ID、ARN、Gateway URL／ID、Knowledge Base ID、bucket名、`s3://`、credential文字列がないことを機械確認した。独立障害とHTTP／SSE／Memoryの失敗境界は関連71テストで成功しており、旧`us-east-2` stackはこの成功判定まで保持した

- [x] T139 旧`us-east-2` stack削除の成功ゲートと対象を確定する
  - 対象: 新`us-east-1`検証結果、旧`us-east-2`の`OpenAiAgentCoreBaseStack`
  - 実施内容: T134からT138の全成功結果を保存し、その成功前に旧stackが削除されていないことを確認する。削除直前にSTS account、profile、region=`us-east-2`、stack名、stack ID、stack resource一覧、復旧不能な旧Memory／S3／ログを再確認する
  - 完了条件: 新環境の全ゲートが成功し、削除対象が旧CloudFormation stackとその管理下resourceだけに限定され、現行`us-east-1`の`CDKToolkit`とstack外resourceが対象外である。未達時はT140へ進んでいない
  - 依存: T138
  - 対応: AC-009
  - 実施結果: T134からT138がすべて`[x]`で、新`us-east-1` stackが`UPDATE_COMPLETE`であることを確認した。削除直前のidentityはprofile `default`、account `338456725408`で、明示region `us-east-2`の旧stack ID `arn:aws:cloudformation:us-east-2:338456725408:stack/OpenAiAgentCoreBaseStack/1401af00-914d-11f1-9f5f-02599aa9ffb9`が`UPDATE_COMPLETE`かつ未削除だった。旧stackの14 resourceを保存し、対象が旧Runtime `OpenAiAgentRuntime-1W1kQJAk2k`、旧Memory `OpenAiAgentMemory-vPJfxm4pIb`、旧Weather Gateway `openaiweathergateway-jop2ukvmqg`／Target `J5URDCC6D9`、Lambda `OpenAiWeatherTimeMock`、log group、関連IAMとmetadataに限定されること、Knowledge／S3 resourceは旧stackにないことを確認した。旧Memory履歴、Runtime／Lambdaログは移行・バックアップせず削除後に復旧不能であることを再確認し、`us-east-1`／`us-east-2`の`CDKToolkit`はいずれも`CREATE_COMPLETE`で削除対象外、stack外resourceも対象外とした

- [x] T140 旧`us-east-2`のPoC stackを削除する
  - 対象: `us-east-2`の`OpenAiAgentCoreBaseStack`
  - 実施内容: `app.py`のsynth結果に依存せず、確認済みprofileと`--region us-east-2`を明示したCloudFormation `delete-stack`で旧stackだけを削除し、`wait stack-delete-complete`で完了を確認する。削除失敗時はeventsを確認し、stack外resourceを自動削除しない
  - 完了条件: 旧stackがCloudFormation上で存在せず、`us-east-1`の新stackと同リージョンの`CDKToolkit`を削除していない。削除失敗時は未完了のまま原因が記録されている
  - 依存: T139
  - 対応: AC-009
  - 実施結果: 確認済みの旧stack ARNだけをprofile `default`、`--region us-east-2`指定の`aws cloudformation delete-stack`で削除し、同じARNに対する`wait stack-delete-complete`が成功した。削除履歴は`DELETE_COMPLETE`で、stack名による`describe-stacks`は「does not exist」を返した。削除中にMemoryが最後まで`DELETE_IN_PROGRESS`だったが最終的にstack全体が正常完了し、削除失敗eventはなかった。新`us-east-1` stackは`UPDATE_COMPLETE`、両regionの`CDKToolkit`は`CREATE_COMPLETE`のままで、stack外resourceを削除していない

- [x] T141 旧リージョンの残存resourceとCDK基盤を監査する
  - 対象: `us-east-2`のCloudFormation、AgentCore Runtime／Memory／Gateway／GatewayTarget、Lambda、Bedrock Knowledge Base／Data Source、`us-east-1`の新stack／`CDKToolkit`、`us-east-2`の`CDKToolkit`存在有無
  - 実施内容: CloudFormation `describe-stacks`、AgentCore control planeの`list-agent-runtimes`／`list-memories`／`list-gateways`／`list-gateway-targets`、Lambda `get-function`または`list-functions`、Bedrock Agentの`list-knowledge-bases`／`list-data-sources`をread-onlyで実行する。削除前に保存したIDと`OpenAiAgentRuntime`、`OpenAiAgentMemory`、`OpenAiWeatherGateway`、`OpenAiKnowledgeGateway`、`WeatherTimeMock`、`KnowledgeRetrieve`、`OpenAiWeatherTimeMock`、`OpenAiKnowledgeBase`、`OpenAiKnowledgeDataSource`で識別する
  - 完了条件: 旧PoC resourceが残っておらず、`us-east-1`の新stackと同リージョンの`CDKToolkit`が正常である。`us-east-2`の`CDKToolkit`は不存在でも失敗扱いにせず復元していない。名前だけが一致してownershipを確認できないresourceを自動削除していない
  - 依存: T140
  - 対応: AC-009
  - 実施結果: 2026-08-19にprofile `default`、account `338456725408`、region `us-east-2`を明示してread-only再監査した。旧stack名はCloudFormation上で不存在、AgentCore Runtime／Memory／Gatewayの一覧は空、旧Lambda `OpenAiWeatherTimeMock`は不存在、Knowledge Base一覧は空、旧Runtime／Lambda log groupも空である。旧Gatewayが存在しないためGatewayTarget、旧Knowledge Baseが存在しないためData Sourceの親resourceも存在しない。新`us-east-1` stackは`UPDATE_COMPLETE`、同regionの`CDKToolkit`は`CREATE_COMPLETE`で正常だった。`us-east-2`の`CDKToolkit`は「does not exist」だが、承認済み仕様、plan、ADR-0006に従い許容結果とし、再bootstrapしていない。名前だけが一致するstack外resourceへの削除操作も行っていない

- [x] T142 リージョン移行の全検証結果と未実施理由を記録する
  - 対象: T124、T132、T134からT141までの実行結果
  - 実施内容: 実行コマンド、account／profile／region、resource状態、成功・失敗、旧環境保持または削除、残存監査を区別して記録する。認証情報は記録せず、実行していない検証を成功扱いしない
  - 完了条件: ローカル再検証、bootstrap、CloudFormation事前検証、deploy、同期、Gateway／Runtime E2E、旧stack削除、残存監査の証跡がレビュー可能で、未実施または失敗項目には理由がある
  - 依存: T124、T132（T134からT141までは到達した範囲の結果または未実施理由を記録する）
  - 対応: AC-007、AC-008、AC-009
  - 実施結果: profile `default`、account `338456725408`をSTSで確認し、互換修正前のローカル全242テスト、最終互換修正後の関連71テスト、Rancher DesktopによるLinux／arm64 image、`us-east-1` bootstrap version 32、CloudFormation read-only change setを伴う`cdk diff`、新stack deploy、S3の5文書＋5 metadata、初回ingestion job `OTXDVIO8B6`の`COMPLETE`（5文書index、失敗0）、Knowledge Gateway SigV4 MCP、Runtime version 5のWeather／Knowledge／複合／空結果／Memory E2Eまで成功を各taskへ記録した。旧`us-east-2` stackは新環境の全E2E成功まで保持し、削除直前に14 resourceを保存してCloudFormation削除を実行、waiter成功と`DELETE_COMPLETE`／stack名不存在を確認した。初回残存監査で見つかったstack外の旧Runtime log groupは2026-08-19の手動削除後に不存在を確認し、旧AgentCore、Lambda、Knowledge、IAM、Lambda log groupも残っていない。再監査では新`us-east-1` stackが`UPDATE_COMPLETE`、同regionの`CDKToolkit`が`CREATE_COMPLETE`であり、`us-east-2`の`CDKToolkit`不存在は承認済み完了条件に従って許容した。認証情報は記録しておらず、旧GatewayTargetとData Sourceは親resource自体が存在しないため個別一覧の対象がないことを明記している

## 完了確認

- [x] T300 `specs.md`の全受け入れ条件と証跡を対応付ける
  - 実施内容: AC-001からAC-009までを実装、テスト、文書、AWS移行結果へ対応付け、各結果を確認する
  - 完了条件: すべての受け入れ条件に確認可能な証跡があり、未確認項目は理由とともに未完了のまま残っている
  - 依存: T100、T101、T102、T103、T104、T110、T111、T112、T113、T120、T121、T122、T123、T124、T130、T131、T133、T200、T201、T202、T203、T204、T205、T142
  - 実施結果: AC-001／AC-002はAgent単体・統合テストとGateway／Runtime E2E、AC-003は文書テスト・asset・S3 10 object・同期、AC-004／AC-005はCDK assertion・CloudFormation事前検証・deploy・Gateway MCP、AC-006はservice／runtime回帰・独立障害テスト・E2E、AC-007は同期・AWS E2E・運用文書、AC-008は全テスト・synth・Linux／arm64 build・文書、AC-009は`us-east-1` bootstrap・移行ゲート・旧stack削除・T141の残存監査へ対応付けた。承認済みAC-009では`us-east-2`の`CDKToolkit`不存在を許容し、新stackと現行Toolkitの正常性を確認済みであるため、AC-001からAC-009まですべて確認可能な証跡がある

- [x] T301 `plan.md`の実装方針、変更対象、順序および対象外に沿っていることを確認する
  - 完了条件: 実装が責務別Construct、専門Agent境界、複数Gatewayライフサイクル、同期分離、`us-east-1`単一stack、新環境先行検証、旧環境廃止順序に従い、変更しない契約や対象外機能を変更していない
  - 依存: T300
  - 実施結果: 実装と検証証跡をplanの変更対象・実施順序へ照合し、責務別Construct、Manager／Weather／KnowledgeのAgent境界、2 Gatewayの独立ライフサイクル、deploy後同期、`us-east-1`単一stack、新環境先行検証、旧PoC stack削除と残存監査に沿っていることを確認した。既存HTTP／SSE／Memory／Weather契約と対象外機能は変更せず、旧`us-east-2` `CDKToolkit`の不存在だけを承認済みplanどおり許容している

- [x] T302 SDD成果物、ADR、実装、テストおよび文書の整合性を確認する
  - 完了条件: 固定名、`us-east-1`、環境変数、Tool名、IAM、filter、結果契約、bootstrap、削除方針、同期・E2E・旧環境廃止手順、検証状態に矛盾がなく、ADR-0004／0005の判断本文を改変せずADR-0006のAccepted判断と整合している
  - 依存: T203、T204、T205、T301
  - 実施結果: `specs.md`、`plan.md`、tasks、ADR、実装、テスト、README／Agent／CDK文書を照合し、固定名、`us-east-1`、環境変数、Tool名、IAM、filter、結果契約、同期・E2E・旧環境廃止手順が一致することを確認した。ADR-0004／0005は判断本文とStatusを変更せずRelated plan／tasksだけを接続し、ADR-0006は移行順序を維持したまま旧`us-east-2` `CDKToolkit`を維持対象外とする決定・運用・完了条件へ更新した。ADR-0006の完了チェックもT134からT141の証跡に基づき完了へ更新した

- [x] T303 feature対象外の変更が差分へ混在していないことを確認する
  - 完了条件: `spec-draft.md`、`discuss.md`、`prompts.md`、既存Weather／Memory／Runtime公開契約、依存version、stack外AWS resource等に本featureによる依頼外の変更がなく、承認済みの`specs.md`／`plan.md`／ADR-0006だけを上流根拠としている。作業開始前から存在する利用者所有の差分は本featureの変更と区別され、変更・破棄されていない
  - 依存: T302
  - 実施結果: staged／unstaged／untrackedのパスを再確認し、本featureの実装・検証・SDD・ADR・文書変更が承認済み範囲に収まることを確認した。作業開始前から存在する`specs/03-agent-base-01/prompts.md`、`specs/06-rag-knowledge-agent-01/prompts.md`、`.DS_Store`、`.idea/`等は利用者所有の既存差分として識別し、この対応では変更、破棄、追加stageを行っていない。既存Weather／Memory／Runtimeの公開契約と依存versionにも対象外変更を追加していない

- [x] T304 シークレット、認証情報、state、一時ファイル、生成物およびローカル設定を確認する
  - 完了条件: `.env`実値、鍵、token、不要なaccount固有情報、state、`cdk.out/`、cache、`.DS_Store`、`.idea/`等が差分やコミット対象に含まれていない。AWS検証に必要なaccount／resource識別情報は最小限で、認証情報を含まない
  - 依存: T303
  - 実施結果: feature対象ファイルをアクセスキー形式、秘密鍵ヘッダー、AWS credential設定形式で検索し、該当がないことを確認した。`cdk.out/`、`.cdk.staging/`、`__pycache__/`、`.pytest_cache/`、`.DS_Store`、`.idea/`は追跡対象に含まれていない。AWS実行証跡のaccount／resource IDは対象環境と監査対象を特定するための非秘密情報に限定され、token、秘密鍵、一時認証情報は記録していない。未追跡のローカル`.DS_Store`と`.idea/`は既存利用者ファイルとして変更・stageしていない

- [x] T305 実行した検証結果と未実施理由が正確に記録されていることを確認する
  - 完了条件: コマンド、成否、旧`us-east-2`失敗、新`us-east-1`結果、環境差、bootstrap、deploy、同期、E2E、削除、監査が区別され、実行していない検証を成功または完了として扱っていない
  - 依存: T133、T142、T304
  - 実施結果: 各タスクの実施結果を再確認し、旧`us-east-2`でのresource schema rejection、新`us-east-1`でのローカル／コンテナ検証、bootstrap、CloudFormation事前検証、deploy、同期、Gateway／Runtime E2E、旧stack削除、手動削除後のread-only再監査を区別して記録している。`us-east-2`の`CDKToolkit`は復元しておらず、不存在を承認済み仕様上の許容結果として記録した。旧GatewayTargetとData Sourceの個別照会は親resourceが存在しないため対象がないことも、実行済み照会と区別した

- [x] T306 `tasks.md`のチェック状態と残課題を実態へ合わせる
  - 完了条件: 完了条件を満たしたタスクだけが`[x]`で、未完了タスクは`[ ]`のまま理由と後続作業が記録され、依存関係と並列可否が実態と一致する
  - 依存: T305
  - 実施結果: T141の完了条件を承認済み仕様へ合わせ、read-only再監査の成功後に`[x]`へ更新した。依存順にT300からT305までを再評価し、完了条件を満たした直後に`[x]`へ更新して旧`CDKToolkit`復元を要求する未実施理由を削除した。T307以外に未完了タスクや有効な未実施理由が残っていないことを確認した

- [x] T307 最終差分と完了条件をレビュー可能な状態へ整える
  - 完了条件: `git status --short`と差分を確認し、本featureの変更と作業開始前から存在する利用者所有の差分が区別され、AC-001からAC-009、ローカル／コンテナ／AWSの検証範囲、`us-east-1` bootstrap、新環境E2E、旧`us-east-2`削除・監査、未解決事項をPull Requestで説明できる
  - 依存: T306
  - 実施結果: `git status --short`、全差分の`git diff --check`、`uv lock --check`、ADR関連リンク、未完了チェックボックス、機密情報・生成物の各監査を実行し、いずれも本featureの完了を妨げる問題がないことを確認した。AC-001からAC-009、ローカル全242テスト、関連71テスト、Linux／arm64 container、`us-east-1` bootstrap／deploy／同期／Gateway／Runtime E2E、旧`us-east-2` stack削除・残存監査をPull Requestで説明できる。利用者所有の既存差分と未追跡ローカルファイルは識別済みで、この対応では変更・破棄・stageしていない。現時点で未完了タスクと未解決事項はない
