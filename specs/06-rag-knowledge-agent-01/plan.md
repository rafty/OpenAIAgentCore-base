# Plan: Managed Knowledge Baseを利用するAWS Knowledge Agent

## 実装方針

本featureは、ナレッジ文書、AWS CDK、IAM、AgentCore Runtime上のAgentアプリケーション、テストおよび運用文書にまたがる複数領域の変更として実装する。

承認済みの`specs.md`と、ADR-0002からADR-0005までの設計判断およびADR-0006の`us-east-1`先行移行判断に従い、既存のManager＋Weather構成へ`AWS Knowledge Agent`をAgent-as-Toolとして追加する。ADR-0006の旧`us-east-2` `CDKToolkit`維持条件は、承認済み仕様に合わせて後続の文書更新で修正する。AWS Knowledge AgentだけがKnowledge専用AgentCore GatewayへSigV4 MCP接続し、Managed Knowledge Bases Connectorの`Retrieve`を利用する。マネージャーAgentは利用者との会話と最終回答を引き続き所有し、質問に応じてWeather Agent、AWS Knowledge Agent、または両方を利用する。

主な実装方針は次のとおりとする。

- `knowledge-base-s3/`の5つのMarkdownと5つのsidecar metadataを検索データの正本とし、synth時の検証とCDK assetの検査で登録対象を10ファイルへ限定する。
- S3バケット、文書配置、Managed Knowledge Base、S3データソース、Knowledge専用Gateway、Connector Targetを責務別Constructへ分け、既存の`AgentCoreStack`では参照と作成順だけを接続する。
- Managed Knowledge BaseはCloudFormationの`AWS::Bedrock::KnowledgeBase`をtype `MANAGED`、embedding model type `MANAGED`で作成し、顧客管理Vector StoreとカスタムEmbeddingモデルを作成しない。
- S3データソースはManaged Knowledge Base用の`MANAGED_KNOWLEDGE_BASE_CONNECTOR`として構成し、同一アカウント・`us-east-1`の専用General Purpose S3バケットだけを参照させる。
- Knowledge専用Gatewayは既存Weather Gatewayと別リソースにし、Managed Knowledge Bases Connector Targetには`Retrieve`だけを設定する。Knowledge Base ID、取得件数および検索方式は管理者設定として固定し、モデルへ変更権限を渡さない。
- 既存のWeather用Runtime環境変数は互換性のため維持し、Knowledge用Gateway URLとTarget名を別の非秘密環境変数として追加する。Gatewayごとの設定、MCP接続、Tool一覧、利用可否およびcleanupを独立して管理する。
- MCP serverとAgent bundleはRuntime呼び出しごとに生成する。WeatherとKnowledgeを個別に接続・検証し、一方の接続失敗が他方の利用を止めない。接続済みresourceを解放できない場合はMemoryへcommitせず、既存SSEエラー契約へfail-closedする。
- AWS Knowledge Agentへ渡す検索結果は、テキスト、リポジトリ相対の文書パス、許可したmetadataへ正規化する。S3バケット名、Knowledge Base ID、Gateway URL、ARN、内部例外はモデル可視の結果や利用者向けエラーへ渡さない。
- 初回同期はADR-0005どおり`cdk deploy`へ組み込まず、CloudFormation OutputからIDを解決してAWS CLIで明示的に開始・確認する手順を文書化する。
- `app.py`、Runtime設定、Gateway URL検証、テストおよび文書の固定リージョンを`us-east-1`へ統一し、Runtime、Memory、Weather／Knowledge Gateway、Lambda、Managed Knowledge Base、S3および関連IAMを単一stackへ配置する。
- 初回`cdk diff`より前に、対象profile、AWSアカウント、リージョンを個別に確認して`us-east-1`をCDK bootstrapし、`CDKToolkit`とasset基盤が正常であることを検証する。
- `us-east-1`のCloudFormation事前検証、deploy、文書配置、初回同期、Gateway ToolおよびRuntime E2Eがすべて成功するまで旧`us-east-2` stackを保持する。成功結果を保存した後だけ旧stackを削除し、CloudFormationと各サービスの残存を監査する。
- 実モデル、実Gateway、実Managed Knowledge Base、実S3、実Memoryを呼び出さない決定的なテストダブルを追加し、仕様固有値、metadata filter、空検索、独立障害、cleanupおよび既存回帰を自動検証する。

## 変更対象

### ナレッジ文書

| パス | 変更内容 |
| --- | --- |
| `knowledge-base-s3/standards/*.md` | AWSアーキテクチャ、セキュリティ、監視の架空社内標準を検索対象として維持し、実装時の自動テストでUTF-8、固有値、秘密情報非混入を確認する |
| `knowledge-base-s3/estimation/estimation_guideline.md` | 見積基準と簡単な工数計算の検索テストデータとして維持する |
| `knowledge-base-s3/projects/sample_project_alpha.md` | 過去案件の構成と実績工数の検索テストデータとして維持する |
| `knowledge-base-s3/**/*.metadata.json` | 各Markdownと一対一のsidecar metadataとして、`document_type`、`version`、`system_type`、`environment`、`service`、必要な`project_name`を提供する |

既存文書の内容は仕様で定義済みの検証値と一致しているため、実装中に都合のよい値へ変更しない。文書またはmetadataの不整合が判明した場合は、受け入れ条件との整合を確認してから最小差分で修正する。

### AWS CDK、S3、Managed Knowledge Base、GatewayおよびIAM

| パス | 変更内容 |
| --- | --- |
| `app.py` | `OpenAiAgentCoreBaseStack`の固定デプロイ先を`us-east-1`へ変更し、PoC全体を同一リージョンの単一stackとしてsynthする |
| `agent_core_cdk_stack/constructs/knowledge_document_bucket_construct.py` | 専用S3バケット、登録対象ファイルのsynth時検証、`BucketDeployment`による相対パス維持、更新・削除反映および文書配置resourceを定義する新規Construct |
| `agent_core_cdk_stack/constructs/managed_knowledge_base_construct.py` | Managed Knowledge Base、専用Bedrock service role、type `MANAGED`、service-managed embeddingおよびRemoval Policyを定義する新規Construct |
| `agent_core_cdk_stack/constructs/knowledge_data_source_construct.py` | S3のManaged Knowledge Base connector、削除保護、データ削除方針、文書配置との依存関係およびData Source IDを定義する新規Construct |
| `agent_core_cdk_stack/constructs/agent_core_knowledge_gateway_construct.py` | 条件付き信頼を持つ専用Gateway実行ロール、IAM受信認証・MCP protocolのKnowledge専用Gateway、対象Knowledge Baseだけの`GetKnowledgeBase`／`Retrieve`権限を定義する新規Construct |
| `agent_core_cdk_stack/constructs/knowledge_retrieve_gateway_target_construct.py` | `bedrock-knowledge-bases` Connector、`Retrieve`だけのconfiguration、管理者固定値、限定parameter override、`GATEWAY_IAM_ROLE`および作成順をCloudFormation L1で定義する新規Construct |
| `agent_core_cdk_stack/constructs/agent_core_runtime_construct.py` | Knowledge Gateway URL／Target名を非秘密環境変数として追加し、Runtime roleへKnowledge専用Gatewayだけの`InvokeGateway`を追加する。既存Weather設定と権限は維持する |
| `agent_core_cdk_stack/agent_core_stack.py` | 文書bucket／deployment、Managed Knowledge Base、data source、Knowledge Gateway／Target、既存Weather経路、Memory、Runtimeの参照と依存関係を接続する。同期用IDをCloudFormation Outputへ公開する |

### Agentアプリケーション

| パス | 変更内容 |
| --- | --- |
| `agents/src/agent_app/config.py` | Gateway単位の非秘密設定を表す構造を追加する。既存Weather環境変数を維持し、Knowledge用URL／Target名を追加して、全URLとTarget名をstream開始前に検証する。固定AWSリージョンとGateway host suffixは`us-east-1`へ更新する |
| `agents/src/agent_app/gateway_tools.py` | 共通SigV4 transportと有限timeoutを再利用しつつ、WeatherとKnowledgeでTool allowlist、引数検証、結果正規化、利用不能結果を分離する。Knowledge結果から内部S3 bucket名を除き、文書相対パスと許可metadataだけを返す |
| `agents/src/agent_app/agent_factory.py` | AWS Knowledge AgentとAgent-as-Toolを追加し、Manager、Weather、Knowledgeの日本語instructions、Tool説明、独立利用可否、ルーティング、結果統合、根拠提示、捏造禁止、検索結果内命令の非実行を定義する |
| `agents/src/agent_app/service.py` | 2つのMCP接続を独立してconnect／listし、利用可能なserverだけを対応Agentへ渡す。正常、部分障害、全障害、timeout、例外、キャンセルで全接続のcleanupとMemory commit／rollback順序を制御する |
| `agents/src/agent_app/runtime.py` | Weather／KnowledgeのMCP factoryと更新後のAgent factoryをserviceへ注入し、既存HTTP／SSE境界を維持する |

`agents/requirements.txt`、`pyproject.toml`および`uv.lock`は、既存の固定依存で必要なAPIを利用できる限り変更しない。実装開始時の公開API probeで不足が確認された場合だけ、仕様と互換性を確認して`uv`で依存を変更する。

### テスト

| パス | 変更内容 |
| --- | --- |
| `tests/unit/test_knowledge_documents.py` | 5 Markdown＋5 metadata、UTF-8、JSON shape、型、許可値、一対一対応、固有値、登録対象外ファイル、秘密情報らしき値の非混入を検証する新規テスト |
| `tests/unit/test_knowledge_base_gateway_stack.py` | S3、BucketDeployment、Managed Knowledge Base、data source、Knowledge Gateway／Target、IAM、Removal Policy、削除保護、asset内容、依存関係および同期Custom Resourceなしを検証する新規CDKテスト |
| `tests/unit/test_open_ai_agent_core_base_stack.py` | `us-east-1`のstack synth、Runtime環境変数、2 Gatewayへの限定InvokeGateway、Target依存、CloudFormation Output、既存Memory／Runtime／Docker asset契約を更新検証する |
| `tests/unit/agent/test_config.py` | `us-east-1`のWeather／Knowledge URLとTarget名、他リージョンURLの拒否、欠落、不正値、安全な設定エラーおよび既存環境変数互換性を検証する |
| `tests/unit/agent/test_gateway_tools.py` | KnowledgeのTool allowlist、Retrieve引数・filter検証、空／正常／不正結果、文書名とmetadataの正規化、S3 bucket名除去、Tool障害、timeoutおよびSigV4設定を追加検証する |
| `tests/unit/agent/test_agent_factory.py` | Managerの直接ToolがWeatherとKnowledgeだけであること、各AgentのMCP境界、Handoffなし、4通りのGateway利用可否、根拠提示、捏造禁止および複合ルーティングinstructionsを検証する |
| `tests/unit/agent/test_service.py` | 2 Gatewayのconnect／list／run／cleanup順序、片系障害、両系障害、cleanup失敗、キャンセル、commit／rollbackおよび接続リークなしを検証する |
| `tests/unit/agent/test_runtime.py` | 更新後のfactory注入、モデル再利用、MCP／Agentのリクエスト単位生成および既存HTTPエラー境界を検証する |
| `tests/integration/agent/test_multi_agent.py` | 決定的ModelとFake MCPで、標準、監視、見積、過去案件、工数計算、metadata filter、空結果、命令形式データ、Weather＋Knowledge統合、独立障害を検証する |
| `tests/integration/agent/test_runtime_http.py` | Knowledge統合後も入力、SSE、Memory、エラー終端および依存初期化境界が変わらないことを検証する |
| `tests/container/harness_main.py`、`tests/container/test_harness.py` | 更新後のfactory signatureへ追従し、実AWSへ接続せずコンテナ起動とHTTP／SSE契約を維持する |

### ドキュメント

| パス | 変更内容 |
| --- | --- |
| `README.md` | Manager、Weather、AWS Knowledge Agent、2 Gateway、Managed Knowledge BaseのPoC概要、`us-east-1`配置、bootstrapと主要検証コマンドを更新する |
| `docs/Agent/README.md` | Agent構成、`us-east-1`のKnowledge設定、Retrieve契約、metadata filter、結果正規化、複数MCPライフサイクル、独立障害、ローカル検証およびRuntime E2Eを記載する |
| `docs/CDK/README.md` | Knowledge関連Construct、固定名、S3配置、Managed Knowledge Base、data source、Gateway Connector、IAM、Removal Policy、synth確認、`us-east-1` bootstrap、初回同期、AWS E2E、旧`us-east-2` stack削除、旧`CDKToolkit`を維持対象外とする方針および残存監査を記載する |
| `docs/ADR/adr-0004-use-managed-knowledge-base-retrieve-via-dedicated-gateway.md` | 判断本文は変更せず、実装段階で`Related plan`を本ファイルへ更新する |
| `docs/ADR/adr-0005-deploy-knowledge-documents-with-cdk-and-sync-after-deploy.md` | 判断本文は変更せず、実装段階で`Related plan`を本ファイルへ更新する |
| `docs/ADR/adr-0006-migrate-poc-to-us-east-1-before-decommissioning-us-east-2.md` | リージョン移行と新環境先行検証の判断を維持しつつ、移行完了後の`us-east-2` `CDKToolkit`を維持対象外とする承認済み仕様へ判断本文と完了条件を更新する |

### AWS移行作業

| 対象 | 変更内容 |
| --- | --- |
| `us-east-1` CDK bootstrap | 対象profileとSTSのAWSアカウントを確認し、`aws://<確認済みaccount>/us-east-1`をbootstrapする。`CDKToolkit`の正常状態とtemplate／file asset／container image assetの利用可否を確認する |
| `us-east-1` 新stack | CloudFormation事前検証を伴う`cdk diff`、`cdk deploy`、S3文書配置、初回同期、Gateway Tool、Runtime E2Eを順に実施し、各結果を保存する |
| `us-east-2` 旧stack | 新環境の全検証成功後だけ、リージョンとstack名を固定したCloudFormation削除で`OpenAiAgentCoreBaseStack`を削除し、完了までwaitする |
| 移行後監査 | 旧stackと旧リージョンの本PoC Runtime、Memory、Gateway、GatewayTarget、Lambda、Knowledge関連リソースが存在しないこと、新`us-east-1` stackと同リージョンの`CDKToolkit`が正常であることをread-only APIで確認する。`us-east-2`の`CDKToolkit`不存在は失敗扱いにしない |

## 変更しないもの

- `specs/06-rag-knowledge-agent-01/spec-draft.md`、`specs/06-rag-knowledge-agent-01/specs.md`、`specs/06-rag-knowledge-agent-01/discuss.md`および`specs/06-rag-knowledge-agent-01/prompts.md`は参照のみとし、この計画では変更しない。
- ADR-0001からADR-0005までの既存設計判断は変更しない。ADR-0001、ADR-0003、ADR-0005の`us-east-2`記載は、AcceptedのADR-0006が定める範囲で`us-east-1`へ読み替える。ADR-0006は、承認済み仕様に合わせて移行完了後の旧`CDKToolkit`維持要件だけを更新する。
- 既存Weather Gateway、WeatherTimeMock Target、Weather／Time Lambda、固定モック出力およびIAM境界の論理構成は変更しない。PoC全体のリージョン移行として同じ構成を`us-east-1`へ新規配置し、検証後に旧`us-east-2`実体を削除する。
- AgentCore Memory resource、Session operation envelope、30日保持、actor／session分離、commit／rollback方式の論理契約は変更しない。ただし旧Memoryの履歴を新Memoryへ移行せず、旧stack削除後の復旧は保証しない。
- Runtimeの`POST /invocations`入力、`GET /ping`、HTTP 4xx／5xx、SSE `text_delta`／`completed`／`error`、モデルID、Bedrock Mantle接続、IAM受信認証、Public network、トレース無効化および`DEFAULT` endpointは変更しない。
- マネージャーAgentによる会話・最終回答所有、Weather AgentのAgent-as-Tool名、Handoffを使用しない構成は変更しない。
- `AgenticRetrieveStream`、AWS Pricing API、Estimation Agent、実在文書、S3以外のデータソース、複数Knowledge Base、`userContext`、文書ACL、カスタムEmbedding／Reranking／Vector Store、定期同期は追加しない。
- VPC、PrivateLink、利用者認証、監視アラーム、バックアップ、DR、SLA、コスト予算などの本番運用対応は追加しない。
- DBスキーマ、外部HTTP API、アプリケーションイベント契約およびデータマイグレーションは追加・変更しない。
- 本featureで明示承認されたAWS操作は、確認済みアカウントに対する`us-east-1` bootstrap、新stackのdeploy／同期／E2E、および成功後の旧`us-east-2` stack削除に限定する。新環境の検証失敗時は旧環境を保持し、stack外リソースや`us-east-1`の`CDKToolkit`を削除しない。移行完了後の`us-east-2` `CDKToolkit`は維持対象外であり、その不存在を復元対象にしない。
- `cdk.out/`、`.cdk.staging/`、`__pycache__/`、`.pytest_cache/`、`.DS_Store`、`.idea/`などの生成物・ローカル設定、および本featureと無関係な既存差分は変更またはコミットしない。

## 技術方針

### 1. 固定名、Tool名およびRuntime設定

公開Tool名と運用手順を安定させるため、次の名前を固定する。IAM Role、S3バケットおよびCDK assetの物理名は環境間の衝突を避けるため固定せず、CDKに生成を任せる。

| 対象 | 値 |
| --- | --- |
| Managed Knowledge Base名 | `OpenAiKnowledgeBase` |
| Data Source名 | `OpenAiKnowledgeDataSource` |
| Knowledge Gateway名 | `OpenAiKnowledgeGateway` |
| Knowledge GatewayTarget名 | `KnowledgeRetrieve` |
| RetrieveのMCP公開名 | `KnowledgeRetrieve___Retrieve` |
| 既存Weather Gateway URL環境変数 | `AGENTCORE_GATEWAY_URL` |
| 既存Weather Target名環境変数 | `AGENTCORE_GATEWAY_TARGET_NAME` |
| Knowledge Gateway URL環境変数 | `AGENTCORE_KNOWLEDGE_GATEWAY_URL` |
| Knowledge Target名環境変数 | `AGENTCORE_KNOWLEDGE_GATEWAY_TARGET_NAME` |

既存Weather環境変数はrenameせず、後方互換性を維持する。Knowledge Gateway URLはCDKの`GatewayUrl`参照、Target名はTargetとRuntimeで共有する同一定数から供給し、生成ID、URLまたはアカウントIDをAgentコードへ固定しない。

同一AWSアカウント／`us-east-1`へこのstackを1つだけデプロイするPoC前提へ変更する。`app.py`の`cdk.Environment.region`を`us-east-1`へ固定し、RuntimeまたはKnowledge経路だけを別リージョンへ分割しない。移行中はリージョンごとに同名stackが一時併存するため、すべてのAWSコマンドでprofile、account、region、stack名を明示・確認する。固定名を持つGateway、Knowledge BaseまたはData Sourceを同一リージョンの複数stackで並行利用する要件が生じた場合は、suffixを推測で導入せず、公開Tool名互換性を含めて仕様へ戻る。

### 2. S3バケット、assetおよび文書削除

- 専用S3バケットは`BlockPublicAccess.BLOCK_ALL`、S3管理暗号化、`enforce_ssl=True`を設定し、ACL、Web hosting、CORS、外部bucket policyおよびcustomer-managed KMS keyを追加しない。
- `knowledge-base-s3/`からの相対パスをそのままobject keyとし、`standards/`、`estimation/`、`projects/`の下に10ファイルを配置する。`knowledge-base-s3/`という追加prefixは付けない。
- synth前に`Path`で通常ファイルを列挙し、仕様の5 Markdownと対応する5 metadataの完全一致を確認する。`.DS_Store`、cache、一時ファイル、未知拡張子または追加ファイルがあれば、asset生成前にfail-fastする。
- `s3_deployment.Source.asset()`と`BucketDeployment`を使用し、`prune=True`でローカルから削除した登録対象をS3からも削除する。bucketはこのdeployment専用であるため、rootでのprune対象に他用途のobjectを混在させない。
- `retain_on_delete=False`とし、明示承認されたstack削除時はdeployment objectを残さない。bucketも`auto_delete_objects=True`と`RemovalPolicy.DESTROY`を設定する。これは短期PoCの削除方針であり、`cdk destroy`の実行権限を拡張しない。
- asset manifestまたはstaged assetを`tmp_path`配下で検査し、相対パス、10ファイルだけ、内容hashによる更新検知、生成物非混入を自動テストする。

### 3. Managed Knowledge BaseとS3 Data Source

- `aws_bedrock.CfnKnowledgeBase`を使用し、`KnowledgeBaseConfiguration.Type`を`MANAGED`、`ManagedKnowledgeBaseConfiguration.EmbeddingModelType`を`MANAGED`にする。`StorageConfiguration`、custom embedding ARN、custom reranking、customer-managed vector storeおよびcustomer-managed KMS keyは設定しない。
- Managed Knowledge Base service roleは`bedrock.amazonaws.com`だけを信頼し、`aws:SourceAccount`をstack account、`aws:SourceArn`を同一partition／region／accountの`knowledge-base/*`へ限定する。resource生成前に個別IDを参照できないためwildcardはKnowledge Base resource type内だけに限定する。
- service-managed embeddingを使うため、service roleへEmbeddingモデルの`InvokeModel`権限は追加しない。S3データソース用に、専用bucketの`ListBucket`と全objectの`GetObject`だけを許可し、書込、削除、他bucket、Secrets Manager、KMS権限を付与しない。
- `aws_bedrock.CfnDataSource`のtypeは`MANAGED_KNOWLEDGE_BASE_CONNECTOR`とし、`ManagedKnowledgeBaseConnectorConfiguration.ConnectorParameters`へS3 type/version、生成bucket名、同一account IDを設定する。self-managed Knowledge Base向けの`S3Configuration`は使用しない。
- 専用bucketの全objectが登録対象として検証済みであるため、connector側に文書とmetadataを分離する追加prefixは設定しない。sidecar metadataはMarkdownと同じdirectory・basenameの`<文書名>.metadata.json`として取り込ませる。
- `DeletionProtectionStatus`を`ENABLED`、`DeletionProtectionThreshold`を`20`にする。登録文書は5件であるため、1件の意図的削除（20%）は許容し、2件以上を同一同期で削除する変更はdelete phaseを止めてレビューを要求する。
- Data Sourceの`DataDeletionPolicy`は`DELETE`、Knowledge BaseとData SourceのL1 resourceは`RemovalPolicy.DESTROY`にする。明示承認されたstack削除時にPoC索引データを残さず、既存MemoryやWeather resourceの削除方針は変更しない。
- Data SourceはManaged Knowledge BaseとBucketDeploymentの両方へ依存させ、文書配置resourceが完了する前にData Sourceを作成しない。初回同期Custom Resource、EventBridge schedule、Lambda同期処理は作成しない。

### 4. Knowledge Gateway、Connector TargetおよびIAM

- Knowledge Gatewayは既存Weather Gateway ConstructのIAM認証・MCP version・条件付きtrustパターンを再利用し、別のGatewayと別のservice roleとして作成する。
- Gateway service roleのPrincipalは`bedrock-agentcore.amazonaws.com`、`aws:SourceAccount`はstack account、`aws:SourceArn`は`OpenAiKnowledgeGateway`から導く小文字Gateway ARN prefixへ限定する。
- Gateway service roleへ付与するbackend権限は、対象Knowledge Base ARNの`bedrock:GetKnowledgeBase`と`bedrock:Retrieve`だけにする。`bedrock:AgenticRetrieveStream`、S3、Lambda、Secrets Manager、KMSおよびwildcard resourceへの取得権限を付与しない。
- 現在固定されている`aws-cdk-lib`ではConnector用L2 convenience APIがないため、`aws_bedrockagentcore.CfnGatewayTarget`のConnector propertyを限定的に使用する。L1利用範囲をこのConstructへ閉じ込め、CloudFormation assertionでshapeを固定する。
- Connector sourceは`bedrock-knowledge-bases`、`enabled`は`Retrieve`だけ、credential providerは`GATEWAY_IAM_ROLE`にする。configurationに`AgenticRetrieveStream`を含めない。
- `Retrieve.parameterValues`へ対象Knowledge Base ID、`numberOfResults=5`、`overrideSearchType=HYBRID`を設定する。Knowledge Base ID、取得件数、検索方式、reranking設定をモデルへoverrideさせない。
- `parameterOverrides`は`$.retrievalQuery.text`と`$.retrievalConfiguration.managedSearchConfiguration.filter`だけをvisibleにする。`userContext`、`numberOfResults`、Knowledge Base IDおよびその他の検索設定は公開しない。
- Target作成前にGateway roleの対象Knowledge Base権限が存在するよう、IAM PolicyをTargetの依存先にする。RuntimeもWeather TargetとKnowledge Targetの両方へ依存させ、CDKが表現できる範囲で作成順を固定する。
- Runtime roleへKnowledge関連で追加する権限は、Knowledge Gateway ARNへの`bedrock-agentcore:InvokeGateway`だけにする。Managed Knowledge Base、S3、Data SourceおよびKnowledge Gateway roleを直接操作する権限は付与しない。

### 5. Retrieve入力、metadata filterおよび結果契約

- AWS Knowledge Agentからの通常検索入力は、空白だけでない`retrievalQuery.text`とする。`knowledgeBaseId`はAgent入力に含めない。
- metadata filterは、属性`document_type`、`environment`、`service`だけを許可する。`document_type`は`equals`、配列属性の`environment`と`service`は`listContains`を使用する。
- 複数条件には`andAll`と`orAll`を許可するが、leafは上記属性・演算子だけ、最大nest 2段、最大8条件に制限する。`project_name`、`version`、`system_type`は結果metadataとして返せるが、Agentが指定する検索filterには公開しない。
- Gatewayが返すTool schemaに加え、MCP adapterの`call_tool()`で引数shapeと上記filter allowlistを再検証する。未知field、型不正、空query、上限超過、公開していないparameterを含む呼び出しはbackendへ送らず、安全な取得不能結果へ変換する。
- `CallToolResult`は`isError=false`かつ単一TextContentのJSON objectを正本として扱い、最上位`retrievalResults`が配列であることを確認する。空配列は「関連情報なし」として正常に区別する。
- 非空結果はMarkdown由来の`content.type=TEXT`、非空`content.text`、`location.type=S3`、非空`s3Location.uri`を必須とする。形式不正、非TEXT、sourceなし、競合した結果表現はfail-closedにする。
- モデルへ渡すcanonical結果は、取得chunk本文、`standards/...`等のbucket名を含まない相対文書パス、任意のscore、許可metadataだけに再構成する。metadataは`document_type`、`version`、`system_type`、`environment`、`service`、`project_name`へ限定し、内部AWS metadataは除外する。
- Tool例外、`isError`、不正結果、timeoutは内部詳細を含まない固定のKnowledge取得不能結果へ変換する。キャンセルは握りつぶさず再送出し、serviceでcleanupとrollbackを実施する。

### 6. 複数Gatewayの設定と接続ライフサイクル

- `AppConfig`内ではWeatherとKnowledgeを別のGateway設定として保持し、URL、region、Target名をGateway単位で参照できるようにする。既存のbase設定と6つの既存環境変数の意味は維持する。
- URL検証は既存のHTTPS、`us-east-1`のAgentCore Gateway host、`/mcp`、userinfo／port／query／fragmentなしを両Gatewayへ適用する。Target名も既存の文字種・長さ制約を再利用し、旧`us-east-2`またはその他リージョンのGateway URLは設定エラーとして拒否する。
- CDKが両Gateway設定を必ず供給する構成とし、設定欠落・不正は既存どおりstream開始前の安全なHTTP 5xxとする。接続後の利用可否はGatewayごとに独立させ、片系の通信障害を他系へ波及させない。
- SigV4 transport、transport timeout 30秒、ClientSession timeout 10秒、cleanup timeout 5秒、`terminate_on_close=True`、リクエスト単位cache、`max_retry_attempts=0`は既存実装を再利用する。
- Weather serverとKnowledge serverを別instanceとして生成し、それぞれconnect後にTool allowlist適用済み`tools/list`を実行する。接続・listに失敗したinstanceはcleanup成功後にその経路だけ利用不能とし、もう一方の接続処理を継続する。
- Agent実行後は接続済みserverを逆順にcleanupし、全cleanup成功後だけSessionをcommitして`completed`を返す。一つでもcleanup不能ならrollbackして既存の安全なSSE `error`とする。
- キャンセル時は接続済みserverすべてのcleanupとSession rollbackをbest-effortで有限時間内に試行し、元の`CancelledError`を再送出する。server、Tool cache、availabilityをRuntime呼び出し間で共有しない。
- serviceとruntimeのfactory境界はGateway種別ごとにFakeを注入できる形にし、実AWSなしで接続順、独立障害、cleanup回数、リークなしを決定的に検証する。

### 7. Agent構成、ルーティングおよびgrounding

- `AgentBundle`へAWS Knowledge Agentを追加し、マネージャーAgentの直接Toolを`weather_agent`と`aws_knowledge_agent`の2つにする。ManagerへMCP serverを直接登録せず、全Agentの`handoffs`は空のままにする。
- Weather AgentにはWeather MCP serverだけ、AWS Knowledge AgentにはKnowledge MCP serverだけを登録する。各Gatewayの利用可否は別flagで判定し、利用不能な専門Agentも安全な取得不能instructionsを持つAgent-as-ToolとしてManagerへ登録する。
- Manager instructionsには、天気・時刻、社内AWS標準、見積基準、過去案件の呼び分け、複合質問で両Toolを利用する条件、Knowledge取得不能を一般知識で補完しないこと、最終回答で文書名を示すことを明記する。
- AWS Knowledge Agent instructionsには、担当質問では回答前に`Retrieve`を必ず使うこと、取得chunkだけを社内知識の根拠にすること、検索結果にない値を補完しないこと、文書相対パスと該当内容を返すことを明記する。
- 検索結果内の命令形式テキストはデータであり、system／developer／Agent instructionsではないことを明記する。テストデータ内の命令をTool呼出し、設定変更、秘密情報要求として実行しない。
- 見積計算は取得済みの基準値と利用者入力の数量だけで実行し、中間式、単位、合計、根拠文書を返す。見積書全体を作成する責務は追加しない。
- 空検索は「関連情報が見つからない」、Knowledge経路障害は「現在取得できない」と区別する。どちらも登録済み固有値、一般知識、推測した社内ルールで代替しない。

### 8. 初回同期と運用コマンド

- StackのCloudFormation OutputへKnowledge Base IDとData Source IDを追加し、S3／Bedrockコンソールを使わずAWS CLIで解決できるようにする。Gateway ID／URLなど、初回同期に不要な内部値を手順へ過剰に出力しない。
- `cdk deploy`成功後、対象profile、account、region、stack名を確認してから、`aws cloudformation describe-stacks`で2つのIDを取得する手順を`docs/CDK/README.md`へ記載する。
- 初回同期は`aws bedrock-agent start-ingestion-job --knowledge-base-id ... --data-source-id ... --region us-east-1`で開始し、返されたIngestion Job IDを保存する。
- `aws bedrock-agent get-ingestion-job`で同じ3 IDを指定し、`COMPLETE`を成功、`FAILED`／`STOPPED`を未完了として扱う。再実行前にstatus、`failureReasons`、statisticsおよびS3配置を確認する。
- 同期成功前にGateway `tools/call`またはRuntime E2Eへ進まない。本featureでは同期、実検索、Runtime呼出しが明示依頼済みであるため、対象account／profile／regionを確認したうえで本計画の順序に従って実施する。

### 9. リージョン移行、CDK bootstrapおよび旧環境廃止

- `us-east-1`の初回`cdk diff`より前に、使用profileを明示してSTS caller identityを取得し、想定AWSアカウントと一致することを確認する。環境変数やprofileの暗黙regionには依存せず、bootstrap対象を`aws://<確認済みaccount>/us-east-1`として指定する。
- `us-east-1`の`CDKToolkit`をCloudFormationで確認し、存在しない場合は`cdk bootstrap aws://<確認済みaccount>/us-east-1 --profile <確認済みprofile>`を実行する。存在する場合も正常状態とbootstrap versionを確認し、現在のCDKが要求するtemplate、file asset、Linux ARM64 container image assetを扱える場合だけ再利用する。
- bootstrap後は`CDKToolkit`が`CREATE_COMPLETE`または`UPDATE_COMPLETE`であること、bootstrap version parameterを取得できること、およびasset publish先が利用可能であることを確認してから`cdk diff`へ進む。bootstrap失敗または更新不能の場合はdeployへ進まない。
- `us-east-1`の`cdk diff`ではCloudFormation read-only change setによる事前検証を有効にし、Managed Knowledge Baseの`MANAGED`とData Sourceの`MANAGED_KNOWLEDGE_BASE_CONNECTOR`が同リージョンのresource schemaに受理されることを必須ゲートとする。`us-east-2`で確認済みのschema rejectionは移行理由として記録し、同リージョンへのdeployを再試行しない。
- `app.py`で`us-east-1`を固定したことをsynth templateで確認し、`cdk deploy OpenAiAgentCoreBaseStack --profile <確認済みprofile> --require-approval broadening`相当の明示コマンドで新環境を作成する。deploy後はCloudFormation stack状態、Output、S3の10 object、初回同期`COMPLETE`、Knowledge Target `READY`、Gateway MCP、RuntimeのWeather／Knowledge／複合質問を順に検証し、成功結果を保存する。
- 上記ゲートが一つでも失敗した場合は旧`us-east-2` stackを保持する。新環境がすべて成功した場合だけ、削除直前にSTS account、profile、region=`us-east-2`、stack名=`OpenAiAgentCoreBaseStack`、旧stack IDとresource一覧を再確認する。
- `app.py`は移行後に`us-east-1`を固定するため、旧stackの削除にはCDK appのsynth結果へ依存しない`aws cloudformation delete-stack --stack-name OpenAiAgentCoreBaseStack --region us-east-2 --profile <確認済みprofile>`を使用し、`aws cloudformation wait stack-delete-complete`で完了を確認する。対象は旧CloudFormation stackとその管理下resourceに限定し、名前が似ているstack外resourceを自動削除しない。
- 削除後はCloudFormationで旧stackが存在しないことを確認し、AgentCore control plane、Lambda、Bedrock Knowledge Base関連のlist／get APIを`us-east-2`へ明示して、本PoCの固定名・prefix・旧stack resource IDに一致するRuntime、Memory、Gateway、GatewayTarget、Lambda、Knowledge関連resourceが残っていないことをread-onlyで監査する。残存が見つかった場合は自動削除せず、旧stackの削除イベントとresource ownershipを調査する。
- 最後に`us-east-1`の新stackと同リージョンの`CDKToolkit`が正常であることを再確認する。`us-east-2`の`CDKToolkit`は移行後の維持対象外とし、不存在でも失敗扱いにしない。旧Memory履歴、旧S3 object、旧ログなど`DESTROY`対象データは移行・バックアップせず、旧stack削除後の復旧を保証しない。

旧リージョンの残存監査には、次のAPIと識別条件を使用する。CloudFormation削除が失敗している場合は、残存監査を削除完了として扱わない。

| サービス | read-only確認 | 本PoCの識別条件 |
| --- | --- | --- |
| CloudFormation | `describe-stacks`、削除失敗時の`describe-stack-events`／`list-stack-resources` | stack名`OpenAiAgentCoreBaseStack`と削除前に保存したstack ID／physical resource ID |
| AgentCore Runtime | `bedrock-agentcore-control list-agent-runtimes` | runtime名`OpenAiAgentRuntime`または削除前に保存したruntime ID |
| AgentCore Memory | `bedrock-agentcore-control list-memories` | memory名`OpenAiAgentMemory`または削除前に保存したmemory ID |
| AgentCore Gateway／Target | `bedrock-agentcore-control list-gateways`、各該当Gatewayへの`list-gateway-targets` | Gateway名`OpenAiWeatherGateway`／`OpenAiKnowledgeGateway`、Target名`WeatherTimeMock`／`KnowledgeRetrieve`、または削除前に保存したID |
| Lambda | `lambda get-function`または`list-functions` | function名`OpenAiWeatherTimeMock`または削除前に保存したfunction ARN |
| Bedrock Knowledge Base／Data Source | `bedrock-agent list-knowledge-bases`、該当KBへの`list-data-sources` | KB名`OpenAiKnowledgeBase`、Data Source名`OpenAiKnowledgeDataSource`、または削除前に保存したID |

旧`us-east-2`にはManaged Knowledge Baseを含むtemplateがdeployされていない可能性があるため、対象resourceが最初から存在しない結果も正常として記録する。一方、名前だけが一致しても旧stack ID／physical IDとの関連を確認できないresourceは削除対象へ自動昇格しない。

### 10. 依存関係と実装APIの確認

- 現在固定されている`aws-cdk-lib>=2.252.0,<3.0.0`にはManaged Knowledge Base、Managed Knowledge Base connector data source、Gateway Connector TargetのCloudFormation L1型があるため、まず既存依存で実装する。
- Agent側は既存の`openai-agents==0.19.4`、`mcp-proxy-for-aws==1.6.4`、`mcp==1.29.0`のSigV4 MCP実装を再利用し、新しいRuntime依存を追加しない。
- 実装開始時に最小のimport／synth probeでL1 property名、tokenの受渡し、asset APIおよび生成CloudFormation shapeを確認する。固定versionで成立しない場合は、コードで曖昧なdictやescape hatchを拡大せず、planへ戻って依存更新または限定的な代替を検討する。

## データや契約への影響

### HTTP、SSE、Memory、DBおよびイベント

- `POST /invocations`、Runtime contextのsession ID、`GET /ping`、HTTP statusおよびSSE event shapeは変更しない。
- Memoryの保存形式、schema version、operation、retention、commit／rollback境界は変更しない。`us-east-1`には新しいMemory resourceを作成し、旧`us-east-2` Memoryの既存履歴は移行しないため、DB migrationと既存履歴の変換は行わない。
- 外部HTTP APIおよびアプリケーションevent contractは追加しない。新しい外部通信はAWS Knowledge AgentからKnowledge GatewayへのSigV4 MCPと、GatewayからManaged Knowledge BaseへのAWS service callだけである。

### AgentおよびTool契約

| 契約 | 変更内容 |
| --- | --- |
| Managerの直接Tool | `weather_agent`に`aws_knowledge_agent`を追加する |
| AWS Knowledge Agent | 社内AWS標準、見積基準、過去案件を担当し、回答前にRetrieveを利用する |
| MCP公開Tool | `KnowledgeRetrieve___Retrieve`を追加し、`AgenticRetrieveStream`は公開しない |
| Retrieve入力 | 非空queryと、許可したmetadata filterだけを受理する。Knowledge Base ID、件数、検索方式は管理者固定 |
| Retrieve正常結果 | chunk本文、bucket名なしの相対文書パス、許可metadata、任意score |
| Retrieve空結果 | 正常な空配列としてAgentへ渡し、関連情報なしを回答する |
| Retrieve失敗 | 内部値を含まない固定の取得不能結果 |

Agent-as-Tool名とMCP公開Tool名は導入後の互換性がある契約としてテストで固定する。

### 環境変数とSecret

| 変数 | 供給元 | 取扱い |
| --- | --- | --- |
| 既存base／Memory／Weather変数 | 既存Runtime Construct | 値と意味を維持する |
| `AGENTCORE_KNOWLEDGE_GATEWAY_URL` | Knowledge Gatewayの`GatewayUrl`参照 | 非秘密、AgentCore hostと`/mcp`を検証、コードへ固定しない |
| `AGENTCORE_KNOWLEDGE_GATEWAY_TARGET_NAME` | CDKのTarget名定数 | 非秘密、Retrieve Tool allowlistの接頭辞に使用する |

API key、Bearer token、静的AWSアクセスキー、Secret key、Session token、Knowledge Base IDおよびS3 bucket名をRuntime環境変数へ追加しない。Knowledge Base IDはConnector Targetの管理者設定にだけ置き、Agentから変更できないようにする。

### インフラ、デプロイ、データライフサイクル

- `app.py`の固定リージョンを`us-east-1`へ変更し、同リージョンの単一stackへRuntime、Memory、Weather／Knowledge Gateway、Lambda、S3 bucket、BucketDeployment、Managed Knowledge Base、Data Source、Connector Target、Bedrock service role、Gateway service role、限定IAM policyおよびCloudFormation Outputを配置する。
- 文書更新はCDK再deployでS3へ反映されるが、検索indexへ反映するにはその後の明示同期が必要である。deploy成功だけをRAG更新完了として扱わない。
- ローカル文書削除はS3へpruneし、同期時の20%削除保護を通過した場合だけindexから削除する。複数文書の一括削除は保護動作と運用確認の対象になる。
- `us-east-1` bootstrapにより`CDKToolkit`とasset基盤が作成され、移行中は新旧PoC resourceが一時的に併存する。新環境の全E2E成功後、旧`us-east-2`のPoC stack管理下resourceを破棄する。現行の`us-east-1` `CDKToolkit`は保持し、旧`us-east-2` `CDKToolkit`は維持対象に含めない。
- 旧Memory履歴、旧S3 object、旧ログは新環境へデータ移行せず、旧stack削除後に復旧できない。削除前に保存するのは新環境の検証結果と旧stackの対象確認情報であり、PoCデータのバックアップは本featureの対象外とする。
- Runtime imageはAgentコード変更により新しいassetになる。新しいPython依存を追加しない限り、manifestとlockfileの変更はない。

### 後方互換性

- HTTP／SSE／Memory、モデル接続、Weather／Time Toolおよび既存Weather環境変数は後方互換とする。
- Gateway URL、ARN、resource IDおよびAWS endpointのリージョンは`us-east-1`へ変わる。これらはデプロイ時に解決する運用・インフラ識別子であり、HTTP／SSE契約には含めない。
- ManagerのTool集合と社内知識に関する回答動作は、本featureで承認された意図的な追加変更である。
- 片方のGateway障害時も、もう一方の専門Agentと一般会話を継続する。設定全体が不正でRuntimeを開始できない場合だけ既存stream前5xx契約を使用する。

## リスク

| リスク | 影響 | 対策・確認方法 |
| --- | --- | --- |
| Managed Knowledge Base向けData Sourceでself-managed用`S3Configuration`を誤用する | deploy時にData Source作成が失敗する | type `MANAGED_KNOWLEDGE_BASE_CONNECTOR`とS3 connector parametersをCloudFormation assertionで固定し、AWS公式shapeと照合する |
| Gateway Connector用L2 APIがなくL1 propertyを誤構成する | Targetが`FAILED`になりToolを発見できない | L1利用を専用Constructへ限定し、source、enabled、configuration、credential provider、parameter overrideのtemplateを厳密にテストする。AWS E2EではTarget `READY`を確認する |
| Data Sourceが文書配置前に作成される | 初回状態が空またはmetadata欠落になる | Data SourceをBucketDeploymentへ明示依存させ、DependsOnをtemplateで確認する |
| assetへ`.DS_Store`、cache、SDD文書などが混入する | 不要データや内部文書が検索対象になる | 許可10ファイルの完全一致をsynth前に検証し、staged assetとS3 object keyを自動テストする |
| `prune=True`が別用途objectを削除する | S3データ損失 | 専用bucketをKnowledge文書以外に使わず、root object集合を10ファイルへ限定する。共有bucketへ変更する場合は計画へ戻る |
| 削除保護閾値が厳しすぎる／緩すぎる | 意図的削除が反映されない、または大量削除が通る | 5文書の1件削除に対応する20%を固定し、2件以上の削除が保護されることを設定テストと条件付きAWS検証で確認する |
| Managed Knowledge Base service roleが過大になる | S3やモデルへの不要アクセス | service-managed embeddingを使い、対象bucketのList/Getだけを付与する。Role／Policyをtemplate全体から検査する |
| Gateway roleへ`AgenticRetrieveStream`やwildcard権限が入る | 対象外機能や過大権限を利用できる | `GetKnowledgeBase`／`Retrieve`と対象Knowledge Base ARNだけをassertし、Agentic action、S3、Lambda、Secrets、KMSがないことを検査する |
| Runtime roleがKnowledge BaseやS3へ直接アクセスする | Gateway境界を迂回する | RuntimeのKnowledge権限が対象GatewayのInvokeGatewayだけであることをCloudFormationテストで固定する |
| metadata filterの自由入力で想定外属性や複雑な式が送られる | 検索境界の逸脱、巨大入力、予期しない結果 | Gateway schemaに加えてMCP adapterで属性、演算子、深さ、条件数をallowlist検証し、不正入力はbackendへ送らない |
| 検索結果にprompt injectionが含まれる | Agentがデータ内命令を実行する | instructionsで検索結果をデータとして扱い、命令形式chunkを含む決定的テストで追加Tool呼出しや指示変更が起きないことを確認する |
| S3 URIやmetadataからbucket名・内部IDが回答へ漏れる | 内部resource情報の露出 | adapterでsourceを相対文書パスへ正規化し、許可metadata以外を除外する。正常／異常応答とログを検査する |
| WeatherとKnowledgeの可用性を一つのflagで扱う | 片系障害が両専門Agentを停止させる | server、factory、availability、Agent MCP登録をGateway単位へ分離し、4通りの可用性と片系障害をテストする |
| 2接続の一方をcleanupし忘れる | session leak、Memoryの誤commit、Runtime不安定化 | 接続済みserverを追跡し逆順cleanupする。正常、connect失敗、list失敗、Runner失敗、timeout、キャンセルのcleanup回数を検証する |
| リクエスト単位で2 Gatewayを初期化して応答開始が遅れる | latencyと利用料金が増える | 各リクエスト内でTool一覧をcacheし、有限timeoutを維持する。PoCでは独立性を優先し、process共有sessionは導入しない |
| 初回同期忘れ、失敗状態の無条件再実行 | 検索不能、原因不明の反復実行 | deployと同期を分離し、ID解決、status、failureReasons、statistics、再実行前確認を手順化する |
| ローカルテストだけでAWS上のManaged KB／Connector挙動を保証したと誤認する | 実環境固有の失敗を見逃す | 承認済み移行手順で`us-east-1`のCloudFormation事前検証、deploy、同期、Gateway、Runtime E2Eを実施し、ローカル結果と区別して保存する |
| 固定物理名が同一account／regionの別stackと衝突する | deploy失敗 | 既存の単一PoC stack前提を明記し、複数stack要件が生じたら命名とTool互換性を仕様へ戻す |
| bootstrap対象のaccount／regionを誤る | 別環境への基盤作成、asset publish失敗 | STS caller identity、profile、account、regionを別々に確認し、`aws://<確認済みaccount>/us-east-1`を明示する。`CDKToolkit`正常確認前はdiff／deployへ進まない |
| 移行中の同名stackでリージョンを取り違える | 新環境の誤削除または旧環境の未削除 | すべてのAWSコマンドへprofileとregionを明示し、削除直前に旧stack ID、resource一覧、region=`us-east-2`を再確認する |
| 新環境の検証前に旧stackを削除する | 利用可能な環境とPoCデータを同時に失う | CloudFormation事前検証、deploy、S3、同期、Gateway、Runtime E2Eの全成功を削除ゲートにし、一つでも失敗すれば旧stackを保持する |
| 旧stack削除でMemory履歴、S3 object、ログを失う | 旧PoCデータを復旧できない | 復旧不能対象を削除前に確認し、新環境の検証結果を保存する。データ移行やバックアップが必要になった場合は削除せず仕様へ戻る |
| stack削除後に一部PoC resourceが残る | 継続課金、誤接続、権限残存 | CloudFormation delete完了後にAgentCore、Lambda、Bedrock Knowledge Base関連APIで旧stack IDと固定名／prefixをread-only監査し、残存時はownershipを調査して自動削除しない |
| 現行`us-east-1`の`CDKToolkit`をPoC stackと一緒に削除する | 現行CDK deployやasset基盤へ影響する | 旧PoC stackの削除対象を`us-east-2`の`OpenAiAgentCoreBaseStack`へ限定し、前後で`us-east-1`の`CDKToolkit`が維持されていることを確認する。旧`us-east-2`の`CDKToolkit`不存在は復元対象にしない |
| 新旧環境の併存が長期化する | AWS利用料金が重複する | 新環境E2E成功後は結果保存、旧stack削除、残存監査を連続して実施し、失敗時だけ旧環境を保持して原因を記録する |

## 検証方針

### 受け入れ条件との対応

| 受け入れ条件 | 検証方法 |
| --- | --- |
| AC-001: Agent構成とルーティング | Agent factoryテストでManagerの直接ToolがWeather／Knowledgeだけ、各MCPが対応Agentだけ、Handoffなしを確認する。決定的Modelで社内標準、見積、過去案件、天気／時刻、複合質問を入力し、期待する専門AgentとManager最終回答を確認する |
| AC-002: RAG回答と安全性 | Fake Retrieve結果でRDS 14日、Logs 90日、EC2 0.5人日、Alpha 26.0人日、EC2 4台＋RDS 1DBの3.0人日とsourceを確認する。空結果、Gateway／Tool障害、命令形式chunkでは捏造・命令実行・内部情報露出がないことを確認する |
| AC-003: 文書とmetadata | 5 Markdown＋5 metadataの存在、UTF-8、JSON、属性型／値、内容との一致、一対一対応、固有値、登録対象外ファイルと秘密情報非混入を単体テストする |
| AC-004: CDK構成とS3配置 | CloudFormation assertionとasset検査でManaged KB type、service-managed embedding、S3 security、10 objectの相対パス、BucketDeployment、Data Source依存、Removal Policy、同期Custom Resourceなしを確認し、synthを実行する |
| AC-005: Gateway ConnectorとIAM | 2 Gatewayの分離、AWS_IAM、MCP version、connector ID、Retrieveのみ、Knowledge Base ID固定、filter override、GATEWAY_IAM_ROLE、Runtime／Gateway／KB roleのaction・resource・trust、禁止権限・秘密情報なしをtemplateで確認する |
| AC-006: 独立障害と回帰 | Weatherのみ利用可、Knowledgeのみ利用可、両方利用可、両方利用不可をFake MCPで確認する。正常、失敗、timeout、キャンセルで全server cleanupを確認し、既存model、Memory、SSE、Weather／Timeテストを全実行する |
| AC-007: デプロイ後同期とAWS E2E | ドキュメントにID解決、同期開始、状態確認、成功・失敗判定、再実行前確認を記載する。`us-east-1`でS3 10 object、同期COMPLETE、metadata filter、tools/list／call、Runtime最終回答を確認する |
| AC-008: 自動検証とドキュメント | 下記ローカル検証、Linux ARM64 build、README／Agent／CDK／ADR／仕様／実装／テストの差分レビューを行う。未実施項目は理由とともに明記する |
| AC-009: リージョン移行と旧環境削除 | STS account／profile／region確認、`us-east-1` bootstrapと`CDKToolkit`正常状態、template／file／container asset、CloudFormation事前検証、deploy、同期、Gateway／Runtime E2Eを順に確認する。全成功前に旧stackが存在すること、成功後に旧`us-east-2` stackと旧PoC resourceが存在しないこと、新`us-east-1` stackと同リージョンの`CDKToolkit`が正常であることを確認する。`us-east-2`の`CDKToolkit`不存在は移行失敗にしない |

### ローカル自動検証

実装後、少なくとも次を実行する。

1. `uv lock --check`で`pyproject.toml`と`uv.lock`の整合を確認する。
2. `uv run pytest tests/unit/test_knowledge_documents.py tests/unit/test_knowledge_base_gateway_stack.py`で文書、metadata、Managed Knowledge Base、S3、Gateway Connector、IAMおよびasset契約を確認する。
3. Agent関連のunit／integration testでRetrieve入力、metadata filter、結果正規化、Agent routing、仕様固有値、見積計算、空結果、命令形式データ、独立障害およびcleanupを確認する。
4. `uv run pytest`で既存Memory、HTTP／SSE、Weather／Time、CDK、container harnessを含む全回帰テストを実行する。
5. `uv run python app.py`または小文字の`cdk synth`でsynthし、生成CloudFormation templateのresource数、property、IAM、DependsOn、Output、禁止要素を確認する。
6. `tmp_path`へ生成したasset manifest／staged assetを検査し、Knowledge assetが10ファイルだけ、相対パス維持、`.DS_Store`／cache／SDD文書なしであることを確認する。
7. `docker build --platform linux/arm64 -t openai-agentcore-poc:local agents`でRuntime containerをbuildする。
8. 既存container harnessで`/ping`、入力エラー、正常SSE、安全なstream errorを確認し、Knowledge統合がHTTP契約を変えていないことを確認する。
9. `git diff --check`と`git status --short`を実行し、feature外差分、Secret、credential、state、生成物、一時ファイルが成果物へ混入していないことを確認する。

Dockerを利用できない場合は、未実施の検証と理由を完了報告に明記し、成功扱いにしない。

### AWS移行・E2E・旧環境廃止

ユーザーが承認した移行範囲として次を順番どおりに実施し、前段が失敗した場合は後段、特に旧環境削除へ進まない。

1. 使用profileでSTS caller identityを取得し、対象AWSアカウントを確認する。`us-east-1`の新stackと`us-east-2`の旧stack／`CDKToolkit`の初期状態をread-onlyで記録する。
2. `us-east-1`の`CDKToolkit`が未作成であることを再確認し、確認済みaccountとregionを指定してCDK bootstrapする。stack状態、bootstrap version、file asset／container image asset基盤を確認する。
3. `us-east-1`を固定したtemplateとLinux ARM64 container imageを準備し、CloudFormation read-only change setを伴う`cdk diff`でManaged Knowledge BaseとManaged connectorのresource schema、IAM拡張、S3削除設定、Removal Policyおよび意図しない削除がないことを確認する。
4. `us-east-1`へdeployし、`OpenAiAgentCoreBaseStack`が正常状態であること、専用S3 bucketに5 Markdown＋5 metadataが期待する相対keyで存在すること、CloudFormation OutputからKnowledge Base IDとData Source IDを解決できることを確認する。
5. 初回Ingestion Jobを開始してstatusが`COMPLETE`になるまで確認する。失敗時は`failureReasons`とstatisticsを保存し、無条件再実行や旧stack削除を行わない。
6. Knowledge GatewayとConnector Targetが`READY`であることを確認し、SigV4 MCP `initialize`と`tools/list`で`KnowledgeRetrieve___Retrieve`だけが対象connectorから公開されることを確認する。
7. `tools/call`で各固有値とsourceを検索し、`document_type`、`environment`、`service` filterで結果を絞り込めることを確認する。
8. Runtimeへ社内標準、見積、過去案件、Weather＋Knowledge複合質問、空検索相当を送り、Manager最終回答、根拠文書、捏造なし、片系障害時の独立継続を確認する。利用者向け応答に認証情報、内部例外、不要なGateway URL、Knowledge Base ID、bucket名またはIAM ARNが含まれないことも確認する。
9. 手順3から8の成功結果を保存し、この時点まで旧`us-east-2` stackが存在することを確認する。いずれかが失敗した場合は旧環境を保持する。
10. 削除直前にSTS account、profile、region=`us-east-2`、stack名、旧stack ID、旧stack resource一覧、復旧不能データを再確認し、CloudFormation `delete-stack`と`wait stack-delete-complete`で旧stackだけを削除する。
11. CloudFormationで旧stackが存在しないことを確認し、`us-east-2`のAgentCore Runtime、Memory、Gateway、GatewayTarget、Lambda、Knowledge Base／Data Sourceを各サービスのlist／get APIで照会する。旧stack resource IDと本PoCの固定名／prefixに一致する残存がないことを確認する。
12. `us-east-1`の新stackと同リージョンの`CDKToolkit`が正常であることを最終確認する。`us-east-2`の`CDKToolkit`は存在確認結果を記録するが、不存在でも失敗扱いにしない。

各結果は実行コマンド、対象account／region、resource状態、成功・失敗を区別して記録し、認証情報は保存しない。

## ドキュメント更新方針

- `README.md`にはPoC全体のManager／Weather／Knowledge構成、`us-east-1`配置、bootstrap前提と、Agent／CDK文書への短い導線を記載する。詳細手順は重複させない。
- `docs/Agent/README.md`をAgent利用・接続ライフサイクルの主文書とし、2つの専門Agent、2 Gateway、`us-east-1`の環境変数、Retrieve入力／結果、metadata filter、grounding、独立障害、ローカル検証およびRuntime E2Eを記載する。
- `docs/CDK/README.md`をresource・IAM・デプロイ後同期・リージョン移行の主文書とし、Knowledge関連Construct、固定名、S3 asset、Managed KB／Data Source、Connector Target、Removal Policy、削除保護、synth確認、`us-east-1` bootstrap、ID解決、初回同期、E2E、旧`us-east-2` stack削除、旧`CDKToolkit`の維持不要、残存監査、復旧不能データを記載する。
- ADR-0004はKnowledge専用Gateway、Retrieve限定、IAM境界、Agent責務を、ADR-0005はCDK S3配置とdeploy後同期を記録している。ADR-0006の`us-east-1`先行移行とE2E成功後の旧環境廃止判断は維持し、移行後の`us-east-2` `CDKToolkit`を維持対象外とする承認済み仕様に合わせて影響、運用方針、完了条件を更新する。新しい設計判断ではないため追加ADRは作成しない。
- ADR-0001、ADR-0003、ADR-0005の`us-east-2`前提はADR-0006の範囲で読み替え、過去の判断本文は改変しない。ADR-0004とADR-0005の`Related plan`更新、およびADR-0006の判断更新は、承認済みtasksの文書更新タスクで扱う。

## 実施順序

1. 固定済み`aws-cdk-lib`のManaged Knowledge Base、Managed connector Data Source、Gateway Connector L1 propertyと、既存MCP依存の公開APIを最小import／synth probeで確認する。
2. ナレッジMarkdownとsidecar metadataの存在、UTF-8、JSON shape、属性型、固有値、一対一対応、秘密情報非混入を自動テストで固定する。
3. 専用S3 bucket、許可10ファイルのsynth時検証、BucketDeployment、prune／retention／Removal Policyを実装し、assetとobject keyのCDKテストを追加する。
4. Managed Knowledge Base service role、type `MANAGED`のKnowledge Base、S3 Managed connector Data Source、削除保護20%、Data Sourceと文書配置の依存関係を実装し、IAMとtemplateを検証する。
5. Knowledge Gateway、条件付きservice role、対象KB限定policy、RetrieveだけのConnector Target、管理者固定値、filter overrideおよびGATEWAY_IAM_ROLEを実装し、CloudFormation shapeと禁止権限を検証する。
6. Runtime ConstructとStackへKnowledge Gateway設定、対象Gateway invoke grant、Target依存および同期用Outputを接続し、既存Weather／Memory／Runtime契約を回帰検証する。
7. `AppConfig`をGateway単位の設定へ拡張し、既存Weather環境変数互換、新規Knowledge設定、URL／Target検証および安全なstream前エラーをテストする。
8. Knowledge MCP adapterへRetrieve Tool allowlist、入力／filter検証、結果正規化、source／metadata sanitization、空結果、有限timeout、安全な利用不能結果を実装する。
9. service／runtimeを2 Gatewayの独立したリクエスト単位接続へ拡張し、4通りの可用性、片系障害、cleanup失敗、timeout、キャンセル、Memory確定順序をテストする。
10. AWS Knowledge Agent、Agent-as-Tool、Manager instructions／routing／結果統合を実装し、仕様固有値、工数計算、source提示、空検索、命令形式データ、独立障害を決定的統合テストで確認する。
11. `app.py`、Agent設定、Gateway URL検証、region固定値、テスト期待値を`us-east-1`へ更新し、PoC全体が単一リージョンの単一stackとしてsynthされることを確認する。
12. 全pytest、synth、CloudFormation／asset検査、Linux ARM64 Docker build、container harness、差分・Secret検査を実行する。
13. README、Agent文書、CDK文書およびADR-0006を、`us-east-1` bootstrap、実装結果、E2E、旧環境削除、旧`CDKToolkit`維持不要および監査手順へ合わせる。
14. STS account／profileと新旧stackの初期状態を確認し、旧`us-east-2` stackを保持したまま`us-east-1`の`CDKToolkit`をbootstrapして正常状態とasset基盤を確認する。
15. `us-east-1`のCloudFormation事前検証を伴う`cdk diff`を実施し、Managed Knowledge BaseとManaged connectorのschemaが受理されること、意図しない削除がないことを確認する。失敗時はdeployへ進まない。
16. `us-east-1`へdeployし、stack、S3 10 object、Output、Data Source、初回同期`COMPLETE`、Knowledge Target `READY`、MCP Retrieve、RuntimeのWeather／Knowledge／複合質問を順にE2E確認する。
17. 全E2E結果を保存し、削除前ゲートを満たすことと旧stackの存在を確認する。未達時は旧環境を保持する。
18. 対象account、profile、旧stack ID、region=`us-east-2`、stack名、resource一覧を再確認し、CloudFormation `delete-stack`とwaitで旧`OpenAiAgentCoreBaseStack`だけを削除する。
19. CloudFormationとAgentCore／Lambda／Bedrockのread-only APIで旧PoC resourceが残っていないことを監査し、新`us-east-1` stackと同リージョンの`CDKToolkit`が維持されていることを確認する。旧`us-east-2` `CDKToolkit`の不存在は許容結果として記録する。
20. `git diff --check`、`git status --short`、SDD／ADR／実装／テスト／文書の整合性、未実施項目と理由を最終確認する。

## 未解決事項

要件を変更する未解決事項と、`tasks.md`作成のために新たなユーザー選択が必要な項目はない。

ただし、次は実装開始時または明示承認後のAWS環境で確認する技術的検証項目であり、現時点では未検証とする。

- 固定済み`aws-cdk-lib`が生成するManaged Knowledge Base S3 connectorのCloudFormation payloadを、対応リージョンである`us-east-1`のAWS serviceが受理すること。`us-east-2`ではresource schema rejectionを確認済みであり、同リージョンへのdeployは行わない。
- `us-east-1`のCDK bootstrapを実行する権限があり、作成された`CDKToolkit`のbootstrap versionとasset基盤が現在のCDK Toolkitおよびfile／Linux ARM64 container image assetに適合すること。
- `CfnGatewayTarget`のConnector configuration、`enabled=["Retrieve"]`、parameter value／overrideおよびCloudFormation tokenで参照するKnowledge Base IDが、実AWSでTarget `READY`になること。
- Managed Knowledge Baseが同じdirectoryの`<文書名>.metadata.json`をsidecarとして取り込み、配列metadataと指定filter演算子を期待どおり評価すること。
- 削除保護20%が5文書中1件の削除を許容し、2件以上の同時削除でdelete phaseを保護すること。
- Knowledge Gatewayの実MCP Tool名、Retrieve response shape、SigV4 protocol交渉が、AWS公式契約と固定依存で一致すること。
- Managed Knowledge Base、Data Source、Gateway Connector、S3配置および追加Agent呼び出しの実測時間・料金。仕様どおり本PoCではSLA、予算、上限値を確定しない。
- 新環境の全検証後に旧`us-east-2` stackのCloudFormation削除が完了し、AgentCore、Lambda、Bedrock Knowledge Base関連APIの識別条件で旧PoC resourceの残存がないこと。

これらが移行実施前に成立しない場合は、要件を推測で変更したり対象外のサービスへ置き換えたりせず、旧`us-east-2`環境を保持してplan段階へ戻り、限定的な代替を検討する。移行完了後の監査で旧`us-east-2` `CDKToolkit`が存在しない場合は、復元せず許容結果として記録する。ADR-0006の移行順序と新環境先行検証の安全条件は変更せず、旧`CDKToolkit`維持条件だけを承認済み仕様に合わせて更新する。
