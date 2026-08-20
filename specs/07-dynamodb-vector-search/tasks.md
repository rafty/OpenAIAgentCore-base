# Tasks: DynamoDB Vector Searchを利用するEstimation Agent PoC

## 前提確認

- [x] T001 対象featureに適用される規約と既存成果物を確認する
  - 対象: `AGENTS.md`、`README.md`、`specs/07-dynamodb-vector-search/`、関連する `docs/`、既存コード、既存テスト、既存ADR、Gitブランチおよび作業ツリー
  - 実施内容: 適用規約、承認済みの仕様・計画、既存のWeather／Knowledge Gateway実装パターン、既存差分を確認し、依頼範囲外の変更を混在させない作業基準を記録する。
  - 完了条件: 参照した規約・成果物、現在のブランチ、既存差分、変更時に保護すべき既存契約が明確になっている
  - 依存: なし

- [x] T002 `specs.md`の要求と受け入れ条件を実装対象へ対応付ける
  - 対象: `specs/07-dynamodb-vector-search/specs.md`
  - 実施内容: スコープ、対象外、FR-001〜FR-013、非機能要件、AC-001〜AC-008、制約、依存関係を確認し、各条件を本タスクリストの実装または検証タスクへ対応付ける。
  - 完了条件: すべての受け入れ条件に確認先があり、対象外のRFP全文解析、帳票生成、承認ワークフロー、汎用DB Toolなどが実装対象へ混入していない
  - 依存: T001

- [x] T003 `plan.md`の実装方針と実施順序を確認する
  - 対象: `specs/07-dynamodb-vector-search/plan.md`
  - 実施内容: 変更対象、変更しないもの、技術方針、リスク、検証方針、ドキュメント更新方針、実施順序、未解決事項を確認する。
  - 完了条件: 実装単位、依存関係、変更しない既存契約、およびAWS E2Eの運用入力が実装開始の未解決事項ではないことが明確になっている
  - 依存: T002

- [x] T004 [P] Vector Index管理方式のADRを作成してレビューする
  - 対象: `docs/ADR/` 配下の新規ADR
  - 実施内容: DynamoDBテーブルは通常のCDK／CloudFormationリソース、Vector Indexは専用Custom Resource Providerで管理し、Sample Dataは明示実行CLIで投入する判断、理由、代替案、影響を記録する。
  - 完了条件: ADRが `plan.md` およびADR-0007と整合し、人のレビューで承認され、実装方式の判断根拠として参照できる
  - 依存: T003

- [x] T005 [P] 単一テーブルと安全な参照・保存境界のADRを作成してレビューする
  - 対象: `docs/ADR/` 配下の新規ADR
  - 実施内容: 単一テーブルのItem境界、30分の検索コンテキスト、不透明な `result_ref`、actor／session束縛、明示保存、冪等なDraft保存境界を記録する。
  - 完了条件: ADRが `plan.md` と整合し、人のレビューで承認され、任意キーをAgentへ公開しない境界が明確である
  - 依存: T003

- [x] T006 [P] Estimation Gateway Target集約とIAM分離のADRを作成してレビューする
  - 対象: `docs/ADR/` 配下の新規ADR
  - 実施内容: 4業務Toolを1つのEstimation Gateway Target／Lambdaへ集約し、Runtime、Gateway、Tool、Vector Index Provider、Seed、後片付けの権限を分離する判断を記録する。
  - 完了条件: ADRがADR-0002〜ADR-0004および `plan.md` と整合し、人のレビューで承認され、各実行主体の権限境界が明確である
  - 依存: T003

- [x] T007 3件のADRレビューゲートを完了する
  - 対象: T004〜T006で作成したADR、`docs/ADR/adr-0007-use-bedrock-cohere-multilingual-embeddings-for-dynamodb-vector-search.md`
  - 実施内容: 4件のADR間、および `specs.md`、`plan.md`との矛盾がないことを確認し、コード実装へ進める状態を確定する。
  - 完了条件: T004〜T006が承認済みで、Vector Index管理、データ・保存境界、Gateway／IAM境界、Embedding契約に未決定事項がない
  - 依存: T004、T005、T006

## 実装タスク

### Sample Dataとローカル検証契約

- [x] T010 Sample DataのJSON Schemaと相互参照規則を定義する
  - 対象: `dynamodb-seed/` 配下の新規JSON Schema、Sample Data検証用モジュール
  - 実施内容: 過去案件サマリー、正式実績、標準工数、単価、価格ポリシー、検索品質ケース、利用者入力について、必須属性、型、列挙値、長さ、ID一意性、参照整合性、禁止属性を検証できる契約を定義する。Vector本体と実案件・秘密情報を正本JSONへ含めない規則も実装する。
  - コメント（コードを変更する場合）: Schemaだけでは表現しにくい相互参照、Decimal、禁止データの検証理由を日本語コメントで説明する
  - 完了条件: 全成果物を機械検証でき、相互参照違反や正本JSON内の `embedding` 数値Listを拒否する。コードを変更した場合は、日本語コメントが非自明な検証理由を説明し、自明な処理の読み替えになっていない
  - 依存: T007

- [x] T011 Sample Data一式を作成する
  - 対象: `dynamodb-seed/projects/project-summaries.json`、`dynamodb-seed/projects/project-actuals.json`、`dynamodb-seed/masters/effort-standards.json`、`dynamodb-seed/masters/rate-cards.json`、`dynamodb-seed/masters/pricing-policies.json`、`dynamodb-seed/evaluation/search-quality-cases.json`、`dynamodb-seed/sample-inputs/sample-project-delta.json`
  - 実施内容: FR-003で定義した `HIST-001`〜`HIST-003`、承認済みマスター、自然言語promptと正規化済み入力を持つSample Project Delta、各HISTを期待第1位とする日本語質問を2件以上ずつ含む6件以上の評価ケースを作成する。
  - 完了条件: T010の契約を満たし、Sample Project Deltaの構成、作業範囲、前提、対象外、基準日、保存意思と、期待結果15.7人日、役割別5.0／10.7人日、原価1,356,000円、提示価格1,695,000円を再現できる入力・マスターが揃っている
  - 依存: T010

- [x] T012 Sample Dataの読み込みと正規化済みドメイン変換を実装する
  - 対象: `lambda_tools/estimation/` 配下の新規Sample Data／Schemaモジュール
  - 実施内容: UTF-8 JSONを読み込み、Schemaと相互参照を検証し、JSON境界の数値を計算用 `decimal.Decimal` へ安全に変換する共通処理を実装する。
  - コメント（コードを変更する場合）: JSON数値を計算の正本にしない理由、検証順序、エラー位置を保持する意図を日本語コメントで説明する
  - 完了条件: 各ファイルの妥当なデータを型付きドメイン値へ変換し、不正な型・参照・Decimalを具体的な検証エラーにできる。日本語コメントが境界変換の設計意図を説明し、自明な処理の読み替えになっていない
  - 依存: T011

### Estimation共通契約とドメイン処理

- [x] T020 AWS SDK依存版とEstimation実行パッケージを固定する
  - 対象: `pyproject.toml`、`uv.lock`、`lambda_tools/estimation/`、`lambda_tools/dynamodb_vector_index/`、関連するLambdaビルド定義
  - 実施内容: `boto3==1.43.65` と `botocore==1.43.65` をCDKテスト、Estimation Tool、Vector Index Provider、Seed／E2E CLIで一致させ、`SearchVectors` とVector Index更新APIを利用できるパッケージ境界を作る。
  - コメント（コードを変更する場合）: ランタイム同梱SDKへ依存せず版を固定する理由と、複数実行主体で版を揃える意図を日本語コメントで説明する
  - 完了条件: 依存宣言とlockが同じ固定版を解決し、各実行パッケージが対象APIモデルを読み込める構成である。日本語コメントがSDK固定の判断理由を説明し、自明な設定の言い換えになっていない
  - 依存: T007

- [x] T021 Tool DTO、入力制限、共通結果envelope、エラー契約を実装する
  - 対象: `lambda_tools/estimation/` 配下の新規contracts／validationモジュール
  - 実施内容: 4 Toolの入力DTO、`status`／`data`／`warnings`／`correlation_id`、canonical status、文字列・配列・数量・IDの上限、64 KiB出力上限、物理キーとVectorの出力禁止を実装する。
  - コメント（コードを変更する場合）: 二重検証、canonical statusへの変換、64 KiB制限、内部引数を利用者入力と分離する理由を日本語コメントで説明する
  - 完了条件: 仕様の許可値と上限だけを受け入れ、未知フィールド、未知status、禁止属性、過大な結果を安全に拒否できる。日本語コメントが契約境界の意図を説明し、自明な処理の読み替えになっていない
  - 依存: T020

- [x] T022 [P] 共通Embeddingアダプターを実装する
  - 対象: `lambda_tools/estimation/` 配下の新規normalization／embeddingモジュール
  - 実施内容: ADR-0007のNFKC・改行・空白・固定フィールド順による正規化、SHA-256、`cohere.embed-multilingual-v3`、用途別 `search_document`／`search_query`、1024次元、`truncate=NONE`、有限値検証、一時障害だけ最大3回・各15秒・総45秒の再試行、機微情報を含めないEMFを実装する。アダプター自身はDynamoDBへ書き込まない。
  - コメント（コードを変更する場合）: 保存用と検索用でinput typeを分ける理由、再試行対象の判定、正規化・ハッシュの再現性、ログ抑止の意図を日本語コメントで説明する
  - 完了条件: Seed CLIと検索Toolから同じ実装を再利用でき、モデル・input type・次元・上限違反をBedrock呼び出し前後で安全に失敗させられる。日本語コメントがEmbedding境界の非自明な判断を説明し、自明な処理の読み替えになっていない
  - 依存: T021

- [x] T023 [P] DynamoDB Item契約とRepositoryを実装する
  - 対象: `lambda_tools/estimation/` 配下の新規items／repositoryモジュール
  - 実施内容: `plan.md`のPK／SK、TTL、`schema_version`、Decimalシリアライズ、既知Partition Keyへの `Query`／完全キー `GetItem`、条件付き書き込み、`SearchVectors`の固定scope・許可filter・top-3・COSINE順、projection検証を実装し、`Scan`と任意キー操作を提供しない。
  - コメント（コードを変更する場合）: 論理Item境界、Scanを禁止する理由、正式数値をベーステーブルから再取得する理由、検索結果の物理キー検証を日本語コメントで説明する
  - 完了条件: 過去案件、実績、各マスター、検索コンテキスト、Draft、冪等性Itemを許可されたキー操作だけで扱い、不正scope／entity／projectionを拒否できる。日本語コメントがデータ境界の意図を説明し、自明な処理の読み替えになっていない
  - 依存: T021

- [x] T024 [P] 決定的な見積計算を実装する
  - 対象: `lambda_tools/estimation/` 配下の新規calculationモジュール
  - 実施内容: 承認済み標準工数・単価・価格ポリシーの基準日選択、0件／複数件の不整合検出、Decimalによる役割別工数、原価、リスク、利益、最終1000円単位丸め、根拠と未反映条件の生成を実装する。過去案件実績は根拠表示に限定し、自動補正へ使わない。
  - コメント（コードを変更する場合）: 計算順序、丸めを最終段階だけで行う理由、複数マスターを推測選択しない理由、類似実績を補正に使わない境界を日本語コメントで説明する
  - 完了条件: 同じ入力とマスターから同じ結果を返し、Sample Project Deltaの期待値を導出でき、Multi-AZ等の未反映条件を警告として保持できる。日本語コメントが計算上の判断を説明し、自明な式の読み替えになっていない
  - 依存: T021

- [x] T025 検索コンテキストと冪等なDraft保存サービスを実装する
  - 対象: `lambda_tools/estimation/` 配下の新規context／draftサービス
  - 実施内容: `secrets.token_urlsafe(32)`相当の `search_context_id`／`result_ref`、actor／session／scope束縛、30分TTLとアプリ側期限判定、UUIDv4 Draft ID、`V0001`、350 KiB事前検査、冪等性ItemとDraftの条件付き `TransactWriteItems`、同一要求再取得、競合拒否、保存後 `GetItem` 再読を実装する。
  - コメント（コードを変更する場合）: DynamoDB TTL削除を認可判定に使わない理由、opaque ref、トランザクション境界、保存後再読、同一キー競合の判断を日本語コメントで説明する
  - 完了条件: 改変・別actor・別session・期限切れ・未知refを拒否し、同じ要求の再試行は同じDraft、異なる要求は競合となり、再読できない保存を成功扱いしない。日本語コメントが安全性と冪等性の意図を説明し、自明な分岐の読み替えになっていない
  - 依存: T023、T024

### Estimation Tools Lambda

- [x] T030 Estimation Gatewayの4 Tool Schemaを定義する
  - 対象: `lambda_tools/estimation/tools.json`、関連するschema生成・読込コード
  - 実施内容: `search_similar_projects`、`get_estimation_reference_data`、`create_estimate_draft`、`get_estimate_draft`だけを公開し、JSON Schemaで入力上限、列挙値、`PREVIEW|SAVE`、内部予約引数を定義する。汎用DynamoDB操作、任意テーブル・キー・filter・`top_k`は公開しない。
  - コメント（コードを変更する場合）: Agent向け入力とアダプター注入の内部引数を分ける理由、公開Toolを4つに限定する理由を日本語コメントで説明する
  - 完了条件: SchemaとT021のLambda側検証が同じ契約を表し、Estimation以外へ公開すべきでないDB操作が存在しない。日本語コメントが公開境界の判断を説明し、自明なSchemaの読み替えになっていない
  - 依存: T021

- [x] T031 [P] `search_similar_projects`を実装する
  - 対象: `lambda_tools/estimation/` 配下の検索Toolモジュール
  - 実施内容: 入力正規化、検索ごとに1回の `search_query` Embedding、固定 `search_scope` と許可filterによる1回の `SearchVectors`、上位3件のキー検証、正式実績の再取得、検索コンテキスト発行、候補DTO化を実装する。0件でも有効なコンテキストと空配列を返す。
  - コメント（コードを変更する場合）: Vector検索結果を正規の案件参照として直接信頼しない理由、検索回数、0件継続、距離値の扱いを日本語コメントで説明する
  - 完了条件: 正常時は順位・距離・opaque refだけを安全に返し、0件時は `NO_RESULTS` と `no_similar_projects=true` を返して後続処理を継続できる。日本語コメントが検索境界の意図を説明し、自明な呼出順の読み替えになっていない
  - 依存: T022、T023、T025、T030

- [x] T032 [P] `get_estimation_reference_data`を実装する
  - 対象: `lambda_tools/estimation/` 配下の参照Toolモジュール
  - 実施内容: 案件種別、サービス、作業種別、役割、基準日を検証し、標準工数・単価・価格ポリシーを既知キーで参照する。類似案件は `search_context_id` と `result_ref` をサーバー側で解決し、参照マスターのID、版、有効日、出典種別を返す。
  - コメント（コードを変更する場合）: Agent生成の案件IDを信頼しない理由、承認済みマスターの選択条件、0件／複数件を不整合とする理由を日本語コメントで説明する
  - 完了条件: `Scan`や任意案件IDを使わず、妥当なrefだけで正式データを取得し、Draftへ引き継げる版情報を返せる。日本語コメントが構造化参照の信頼境界を説明し、自明な処理の読み替えになっていない
  - 依存: T023、T025、T030

- [x] T033 `create_estimate_draft`のPREVIEW／SAVEを実装する
  - 対象: `lambda_tools/estimation/` 配下の見積作成Toolモジュール
  - 実施内容: 入力、検索ref、マスター版を再検証し、Agent入力の合計を信頼せず再計算する。PREVIEWでは無書き込み、SAVEではT025のトランザクション保存・冪等再取得・保存後再読を行い、類似案件0件では標準マスターのみで継続して `STANDARD_MASTERS_ONLY` を明記する。
  - コメント（コードを変更する場合）: PREVIEWとSAVEの副作用境界、サーバー再計算、明示保存だけを永続化する理由、0件継続の根拠を日本語コメントで説明する
  - 完了条件: PREVIEWとSAVEを混同せず、保存成功・既存Draft・保存失敗を区別し、Sample Project Deltaの根拠、版、計算内訳、警告を返せる。日本語コメントが保存判断の意図を説明し、自明な条件分岐の読み替えになっていない
  - 依存: T024、T025、T030、T031、T032

- [x] T034 [P] `get_estimate_draft`を実装する
  - 対象: `lambda_tools/estimation/` 配下のDraft参照Toolモジュール
  - 実施内容: `project_id`、`estimate_id`、`version`を形式検証し、組み立てた完全キーの `GetItem` だけでDraftを取得して、作成者、根拠、マスター版、内訳、金額、警告を表示用DTOへ変換する。
  - コメント（コードを変更する場合）: 一覧・任意検索を提供せず完全キー参照に限定する理由と、保存Itemをそのまま返さない理由を日本語コメントで説明する
  - 完了条件: 完全キーで既存Draftを再取得でき、不正IDと未存在Draftをcanonical statusで区別し、物理キーや内部属性を返さない。日本語コメントが参照境界の意図を説明し、自明な取得処理の読み替えになっていない
  - 依存: T023、T030

- [x] T035 Lambdaハンドラーへ4 Toolを統合する
  - 対象: `lambda_tools/estimation/handler.py` および関連するcomposition／loggingモジュール
  - 実施内容: Tool名ルーティング、依存クライアント注入、共通入力・結果検証、canonical error変換、correlation ID、60秒Lambda制限内の処理、機微情報を含めない構造化ログを実装する。
  - コメント（コードを変更する場合）: ハンドラーをルーティングと境界処理へ限定する理由、AWS例外を公開契約へ変換する基準、ログへ本文・Vector・単価・金額を出さない理由を日本語コメントで説明する
  - 完了条件: 4 Toolだけを共通envelopeで実行でき、未知Toolと依存障害を安全に返し、RFP本文、検索全文、Vector、単価、金額をログへ出さない。日本語コメントが例外・ログ境界の意図を説明し、自明な処理の読み替えになっていない
  - 依存: T031、T032、T033、T034

### DynamoDB、Vector Index、GatewayのCDK構成

- [x] T040 [P] Estimation用DynamoDBテーブルConstructを実装する
  - 対象: `agent_core_cdk_stack/` 配下の新規EstimationデータConstruct
  - 実施内容: 物理名 `OpenAiEstimationData`、文字列PK／SK、オンデマンド、TTL `expires_at_epoch`、AWS所有キー暗号化、PITR無効、PoC削除ポリシーを持つ単一テーブルと必要なCloudFormation出力を定義する。
  - コメント（コードを変更する場合）: 単一テーブル、PITR初期無効、PoC削除ポリシー、出力値をCLIへ渡す意図を日本語コメントで説明する
  - 完了条件: 計画どおりのテーブル属性とライフサイクルをCDKで表現し、他の既存テーブルやKnowledge Baseへ影響しない。日本語コメントがインフラ判断を説明し、自明なプロパティの読み替えになっていない
  - 依存: T007

- [x] T041 [P] Vector Index Custom Resource Providerを実装する
  - 対象: `lambda_tools/dynamodb_vector_index/`
  - 実施内容: CloudFormation Create／Update／DeleteをDynamoDB APIへ変換し、同一設定の再実行、非同期状態確認、ACTIVE／失敗、version付きIndex置換、対象Indexだけの削除、既削除成功、意味のある失敗応答、安全なログを実装する。
  - コメント（コードを変更する場合）: CloudFormation未対応を補うProviderの責務、冪等性、非同期待機、置換、削除範囲を限定する理由を日本語コメントで説明する
  - 完了条件: 対象テーブル／Index以外を操作せず、本文やVectorをログへ出さずに全ライフサイクルを処理できる。日本語コメントがProvider固有の非自明な状態遷移を説明し、自明なAPI呼出の読み替えになっていない
  - 依存: T020

- [x] T042 Vector Index管理Constructを実装する
  - 対象: `agent_core_cdk_stack/` 配下の新規Vector Index Provider／Custom Resource Construct
  - 実施内容: `EstimationProjectVectorIndexV1`、`embedding`、1024次元、COSINE、HASH `search_scope`、4つのINLINE_FILTER、最小projectionをCustom Resource propertiesとして定義し、Provider Lambda、1週間ログ、対象テーブルのDescribe／UpdateTableだけのIAMを構成する。
  - コメント（コードを変更する場合）: テーブルとIndexの管理方式を分ける理由、固定Index契約、限定IAM、replacement triggerを日本語コメントで説明する
  - 完了条件: テーブル作成後にIndexを管理し、設定変更は置換として扱い、Sample Data投入Custom Resourceを作成しない。日本語コメントがCustom Resource境界の意図を説明し、自明な設定の読み替えになっていない
  - 依存: T040、T041

- [x] T043 Estimation Tools Lambda、Gateway、Target、IAM、ログを実装する
  - 対象: `agent_core_cdk_stack/` 配下の新規Estimation Gateway／Target／Lambda Construct、Estimation Lambdaビルド定義
  - 実施内容: `OpenAiEstimationGateway`、Target `EstimationTools`、Lambda `OpenAiEstimationTools`、4 Tool Schema、60秒timeout、1週間ログを定義する。GatewayはLambda invokeだけ、Tool Lambdaは対象テーブルの限定Get／Query／書き込み、対象IndexのSearchVectors、固定Bedrockモデルinvokeだけを許可し、書き込みPKを `dynamodb:LeadingKeys` で制限する。
  - コメント（コードを変更する場合）: 4 Tool集約、Runtime／Gateway／Toolの権限分離、LeadingKeys、固定モデル・Indexへ限定する理由を日本語コメントで説明する
  - 完了条件: Estimation専用Gateway経由で4 Toolだけを呼べ、RuntimeへDynamoDB／Embedding直接権限を付けず、Tool Lambdaから過去案件・マスターを書き換えられない。日本語コメントが最小権限の判断を説明し、自明なIAM定義の読み替えになっていない
  - 依存: T035、T040、T042

- [x] T044 Estimationインフラを既存CDKスタックへ統合する
  - 対象: `agent_core_cdk_stack/agent_core_stack.py`、既存Runtime Construct、CloudFormation outputs
  - 実施内容: テーブル、Vector Index、Estimation Gateway／Target／Lambdaを依存順に組み込み、Runtimeへ `AGENTCORE_ESTIMATION_GATEWAY_URL` と `AGENTCORE_ESTIMATION_GATEWAY_TARGET_NAME` を注入する。Seed／E2E CLIがテーブル名とIndex名を解決できる出力を追加する。
  - コメント（コードを変更する場合）: Construct間の依存順、既存Gatewayから独立させる理由、Seedをデプロイから分離する意図を日本語コメントで説明する
  - 完了条件: 既存Weather／Knowledge／HTTP／SSE／Cognito／Memory契約を変えず、新規リソースと出力だけをスタックへ統合できる。日本語コメントが構成上の依存と分離理由を説明し、自明な組み込み処理の読み替えになっていない
  - 依存: T043

### Estimation AgentとRuntime統合

- [x] T050 [P] Estimation Gateway設定を追加する
  - 対象: `agents/src/agent_app/config.py`、必要な設定モデル
  - 実施内容: Estimation Gateway URLとTarget名を独立した任意設定として追加し、両方が有効な場合だけEstimation機能を有効化し、不完全な設定では既存Agentを起動可能なままEstimationだけを無効化する。
  - コメント（コードを変更する場合）: Gateway単位で設定を独立させる理由と、不完全設定を全体障害にしない判断を日本語コメントで説明する
  - 完了条件: 従来環境との後方互換性を保ち、完全・未設定・片側欠落を区別できる。日本語コメントが部分有効化の意図を説明し、自明な条件分岐の読み替えになっていない
  - 依存: T007

- [x] T051 Estimation MCPアダプターを実装する
  - 対象: `agents/src/agent_app/gateway_tools.py`、必要な契約モジュール
  - 実施内容: Estimation 4 Toolのallowlist、Tool別結果Schemaと64 KiB・禁止属性検証、接続／一覧10秒・Tool 60秒・cleanup 5秒・transport 75秒、request-local検索上限3回を追加する。検証済みactor／sessionを予約引数へ上書きし、保存時の冪等性キーを決定的に生成する。
  - コメント（コードを変更する場合）: モデル指定の内部値を破棄する理由、検索回数とtimeoutの境界、結果をAgentへ渡す前に再検証する理由、冪等キーをモデルに作らせない理由を日本語コメントで説明する
  - 完了条件: Estimation Gatewayだけへ接続し、許可Tool・安全な結果だけをAgentへ渡し、任意actor／session／idempotency値と4回目の検索を拒否できる。日本語コメントが信頼境界を説明し、自明な処理の読み替えになっていない
  - 依存: T030、T050

- [x] T052 Estimation AgentとManager Agent連携を実装する
  - 対象: `agents/src/agent_app/agent_factory.py`
  - 実施内容: Estimation Agentへ4 Toolだけを登録し、Managerへ `Agent.as_tool()` として追加する。handoffは追加しない。指示へ `EXPLICIT_SAVE`／`PREVIEW_ONLY`／`AMBIGUOUS`、0件継続、根拠・版・内訳・警告・信頼度、保存済みIDの返却、保存不能時の表現を追加する。
  - コメント（コードを変更する場合）: Managerが最終回答を担う理由、Handoffを使わない理由、保存意図3状態と0件継続をAgent指示で明示する理由を日本語コメントで説明する
  - 完了条件: Estimation Toolが他AgentやManagerへ直接登録されず、明示保存は同一turn、previewは非保存、曖昧時はpreview後確認となり、最終回答はManagerが日本語で返す構成である。日本語コメントがAgent分担の設計意図を説明し、自明な登録処理の読み替えになっていない
  - 依存: T051

- [x] T053 Runtimeサービスへ独立したEstimation lifecycleと部分障害処理を実装する
  - 対象: `agents/src/agent_app/service.py`、`agents/src/agent_app/runtime.py`
  - 実施内容: Weather、Knowledge、EstimationのMCP生成、接続、Tool一覧、cleanupを互いに独立して扱い、利用可能な専門Agentの組合せでManagerを構成する。Estimation接続／cleanup失敗や保存失敗を既存Agent、一般会話、Memory commit／rollbackの不必要な全体停止へ波及させない。
  - コメント（コードを変更する場合）: 3 Gatewayを独立ライフサイクルにする理由、部分障害時の継続条件、保存状態とMemory状態を混同しない理由を日本語コメントで説明する
  - 完了条件: Estimationだけの障害時も利用可能な既存Agentで応答でき、保存できていない処理を保存済みと表現せず、すべての生成済みMCP資源を安全にcleanupできる。日本語コメントが部分障害と後片付けの判断を説明し、自明な例外処理の読み替えになっていない
  - 依存: T052

### Seed、検索品質評価、後片付けCLI

- [x] T060 `EstimationSeedCli`を実装する
  - 対象: `scripts/estimation_seed.py`、T012・T022・T023の共通モジュール
  - 実施内容: `validate`、`wait-index`、`apply --apply`、完全なDraft IDを要求する `cleanup-draft --apply` を実装する。CloudFormation出力または明示引数を解決し、Index準備確認、`search_summary`だけのEmbedding生成、hash一致skip、変更分と構造化データの冪等upsert、件数要約を行う。既定はvalidate-onlyとし、Scan・一括削除・管理外Item削除を実装しない。
  - コメント（コードを変更する場合）: `--apply`を要求する理由、hash一致時にBedrockと書き込みをskipする理由、Seedとcleanupの削除範囲、Index結果整合を待つ理由を日本語コメントで説明する
  - 完了条件: Vectorを正本JSONへ保存せず、過去案件サマリーだけへ生成Vectorとメタデータを登録し、同一Seed再実行をskip中心で完了でき、管理対象外データを変更しない。日本語コメントが明示実行と冪等性の意図を説明し、自明なCLI処理の読み替えになっていない
  - 依存: T012、T022、T023、T044

- [x] T061 検索品質評価CLIを実装する
  - 対象: `scripts/estimation_vector_e2e.py`
  - 実施内容: `evaluate`で正本の評価質問を順に `search_query` Embeddingと実Vector Searchへ渡し、top-3と期待top-1を判定する。実行日時、リージョン、モデル、次元、正規化version、Seed hash、Index、各順位・合否を指定ファイルへ出力し、距離値の完全一致は判定しない。
  - コメント（コードを変更する場合）: 期待順位をSample Data内の回帰基準に限定する理由、距離絶対値を固定しない理由、実行メタデータを残す理由を日本語コメントで説明する
  - 完了条件: 6件以上の全ケースとSample Project Deltaを評価し、各HISTの期待top-1を機械判定でき、本番検索品質の証明とは表現しない。日本語コメントが評価境界の意図を説明し、自明な順位比較の読み替えになっていない
  - 依存: T060

## テスト / 検証タスク

### 単体検証

- [x] T100 [P] Sample DataとSchemaの自動テストを作成する
  - 対象: `tests/unit/` 配下の新規Sample Dataテスト、`dynamodb-seed/`
  - 実施内容: 全JSONのUTF-8解析、必須属性・型・一意性・相互参照、禁止Vector、Sample Project Delta、評価ケース数とHIST別期待件数、実案件・秘密情報の不在を検証する。
  - 完了条件: 正常な成果物が通り、代表的な欠落・型違反・重複・参照切れ・Vector混入が失敗する（AC-002、AC-007）
  - 依存: T012

- [x] T101 [P] Embeddingアダプターの単体テストを作成する
  - 対象: `tests/unit/` 配下の新規normalization／embeddingテスト
  - 実施内容: fake Bedrock clientでNFKC、固定順、改行・空白、hash、用途別input type、1024次元、有限値、上限超過、固定モデル拒否、一時障害最大3回、恒久障害無再試行、EMFとログ抑止を検証する。
  - 完了条件: ADR-0007の保存・検索Embedding契約と失敗境界を決定的に確認できる（AC-002、AC-006、AC-007）
  - 依存: T022

- [x] T102 [P] Repository、検索コンテキスト、冪等性の単体テストを作成する
  - 対象: `tests/unit/` 配下の新規repository／context／draftテスト
  - 実施内容: fake／StubberでGetItem、Query、SearchVectors、条件付き書き込み、transaction cancellationを再現し、固定scope／filter／top-3、検索1回、Scan不使用、不正projection、0件context、ref改変、別actor／session、期限切れ、同一要求再試行、競合、350 KiB、保存後再読を検証する。
  - 完了条件: 安全なID引き継ぎとDraft保存境界の正常・異常系を決定的に確認できる（AC-002〜AC-004、AC-006、AC-007）
  - 依存: T023、T025

- [x] T103 [P] 見積計算の単体テストを作成する
  - 対象: `tests/unit/` 配下の新規calculationテスト
  - 実施内容: Decimal、承認済みマスター0件／複数件、基準日、境界数量、リスク・利益、1000円丸め、未反映条件、類似実績非補正を検証する。
  - 完了条件: Sample Project Deltaで15.7人日、5.0／10.7人日、1,356,000円、1,695,000円となり、HIST-001の26.0人日を自動補正しない（AC-003、AC-007）
  - 依存: T024、T011

- [x] T104 [P] 4 ToolとLambdaハンドラーの契約テストを作成する
  - 対象: `tests/unit/` 配下の新規Estimation Tool handlerテスト
  - 実施内容: 各Toolの正常系、入力不足、列挙違反、長さ超過、未知Tool、AWS例外、0件継続、PREVIEW無書き込み、SAVE、保存後再読失敗、完全キー参照、64 KiB・禁止属性を検証する。
  - 完了条件: 4 Toolがcanonical envelopeだけを返し、preview／保存済み／保存失敗を混同せず、汎用DB操作を公開しない（AC-003、AC-004、AC-006、AC-007）
  - 依存: T035

- [x] T105 [P] Vector Index Providerのライフサイクル単体テストを作成する
  - 対象: `tests/unit/` 配下の新規Vector Index Providerテスト
  - 実施内容: fake control-plane clientでCreate、同一再Create、作成中、ACTIVE、失敗、Update置換、Delete、既削除を再現し、対象外テーブル／Indexを操作せず、意味のある失敗と安全なログを返すことを検証する。
  - 完了条件: CloudFormationイベントごとの冪等性、非同期状態遷移、置換、限定削除を決定的に確認できる（AC-005〜AC-007）
  - 依存: T041

### 結合検証 / 動作確認

- [x] T110 [P] CDKテンプレート契約テストを作成する
  - 対象: `tests/unit/` 配下の新規Estimation stackテスト、既存CDKテスト
  - 実施内容: テーブル、TTL、Vector Index properties、Provider、Estimation Gateway／Target／Lambda、ログ、Runtime環境変数、各IAM境界、LeadingKeys、Sample Data Custom Resource不在を `aws_cdk.assertions.Template` で検証する。
  - 完了条件: RuntimeにDynamoDB／Bedrock直接権限がなく、Gateway・Tool・Providerの最小権限と固定Index契約をテンプレートで確認できる（AC-005、AC-007）
  - 依存: T044

- [x] T111 [P] Agent、MCPアダプター、Runtimeの単体・結合テストを作成する
  - 対象: `tests/unit/agent/`、`tests/integration/agent/`
  - 実施内容: scripted modelとfake MCPを拡張し、EstimationのAgent-as-Tool登録、handoff不在、4 Tool限定、内部context上書き、最大3検索、timeout、全Gateway利用可否組合せ、接続／cleanup部分障害、保存意図3状態、0件継続、保存状態の表現を検証する。
  - 完了条件: Estimation障害がWeather、Knowledge、一般会話を不必要に停止せず、明示保存は同一turn、previewは非保存、曖昧依頼は確認前に保存しない（AC-001、AC-004、AC-006、AC-007）
  - 依存: T053

- [x] T112 Sample Project Deltaの決定的なAgentワークフローテストを作成する
  - 対象: `tests/integration/agent/` 配下の新規Estimation workflowテスト
  - 実施内容: fake Embedding、fake SearchVectors、fake Item API、scripted modelを用い、Delta入力からHIST-001参照、構造化マスター取得、計算preview、明示SAVE、再取得、Managerの日本語最終回答までを固定する。別ケースで0件時の標準マスター継続と `STANDARD_MASTERS_ONLY` を確認する。
  - 完了条件: 最終回答に15.7人日、役割別工数、1,356,000円、1,695,000円、マスターversion、保存ID、類似実績非補正、未反映条件が含まれ、0件時は「類似案件なし」が明記される（AC-001〜AC-004、AC-006、AC-007）
  - 依存: T104、T111

- [x] T113 既存AgentCore公開契約の回帰テストを拡張する
  - 対象: 既存の `tests/unit/agent/`、`tests/integration/agent/test_runtime_http.py`、Weather／Knowledge／Memory関連テスト
  - 実施内容: HTTP／SSE、Cognito前提、Memory commit／rollback、Weather、Knowledge、Estimation未設定時の起動、既存Tool公開境界が変わらないことを検証する。
  - 完了条件: 既存公開契約と既存Agentの正常・異常系が回帰せず、Estimation追加が任意構成として機能する（AC-001、AC-006、AC-007）
  - 依存: T053、T110

### 静的検証 / ビルド

- [x] T120 依存lock、全自動テスト、CDK synthを実行する
  - 対象: `uv lock --check`、プロジェクト既定のlint／type-check（定義されている場合）、`uv run pytest`、`uv run python app.py`
  - 実施内容: lock整合、全テスト、CDK synthを実行し、生成CloudFormationテンプレートの主要リソース・依存・IAMを確認する。生成物はソースとして編集またはコミットしない。
  - 完了条件: 定義済みコマンドがエラーなく完了し、結果と生成テンプレートの確認内容を記録している（AC-005、AC-007）
  - 依存: T100〜T105、T110〜T113

- [x] T121 Agent RuntimeとLambdaコンテナを対象アーキテクチャでbuildする
  - 対象: `agents/Dockerfile`、Estimation Tool／Vector Index ProviderのLambdaビルド定義
  - 実施内容: 各コンテナを対象アーキテクチャでbuildし、固定したboto3／botocore、`SearchVectors`、Vector Index APIモデル、ハンドラーimportを確認する。
  - 完了条件: すべての対象イメージがbuildでき、実行環境に必要な固定SDKとハンドラーが含まれている（AC-005、AC-007）
  - 依存: T120

- [x] T122 Lambdaハンドラーのローカル入出力とSeed validate-onlyを確認する
  - 対象: Estimation Lambdaのローカルハーネス、`uv run python scripts/estimation_seed.py validate --source dynamodb-seed`
  - 実施内容: fake AWS clientでGateway相当イベントをLambdaへ渡し、共通envelopeを確認する。Seed CLIをAWS書き込みなしでSample Data一式へ実行する。
  - 完了条件: ローカルハンドラーが期待契約を返し、validate-onlyが全Sample Dataを検証してAWS APIの書き込みを行わない（AC-002、AC-003、AC-007）
  - 依存: T060、T104、T121

- [x] T123 未実施または失敗した検証を記録する
  - 対象: 本featureの実装記録、`tasks.md`の該当タスク
  - 実施内容: 実行できなかったコマンド、失敗内容、影響範囲、再実行条件を記録し、未確認事項を成功扱いしない。
  - 完了条件: すべてのローカル検証について結果または未実施理由が追跡可能である
  - 依存: T120、T121、T122

### AWS E2E / 手動確認

- [x] T130 AWS E2Eの実行前提と明示承認を確認する
  - 対象: 対象AWSアカウント、プロファイル、`us-east-1`、Bedrockモデルアクセス、DynamoDB Vector Search利用可否・quota、AWS Budgets
  - 実施内容: ユーザーからAWS書き込み・deployの明示依頼を得たうえで、PoC責任者が月額予算額と通知先を指定し、50%／80%／100%通知を設定できることを確認する。固定account ID、ARN、URL、認証情報をリポジトリへ記録しない。
  - 完了条件: 明示承認と全運用入力が揃っている。または未実施の場合、その理由を記録してローカル実装の失敗とは扱わない
  - 依存: T123
  - 確認結果: ユーザーからAWS deploy／書き込み／cleanupの明示承認を取得し、対象profile `default`、region `us-east-1`、Bedrock Cohereモデルの利用可能状態を確認した。既存の月次Cost Budget「月別予算」（15 USD）と既存subscriberを再利用し、実績コスト50%／80%／100%通知を設定・確認した。account ID、ARN、通知先実値はリポジトリへ記録していない

- [x] T131 AWS E2Eの実施可否を判定し、承認時だけ手動シナリオを実施する
  - 対象: deploy済みPoC環境、`scripts/estimation_seed.py`、`scripts/estimation_vector_e2e.py`、`docs/ManualTesting/README.md`
  - 実施内容: 承認済みの場合だけdeploy、Index ACTIVE確認、Seed `--apply` と冪等再実行、全検索品質ケース、Sample Project Deltaのpreview／明示保存／曖昧保存確認／0件検索／Draft再参照、不正・期限切れref、DynamoDB Item、CloudWatch Logs／EMF、完全キーcleanupを手順どおり確認する。
  - 完了条件: 承認時はHIST-001を含む全期待top-1、Deltaの期待計算・保存・再取得、安全なref、0件継続、禁止データのログ不在を確認し、結果を記録している。未承認時は未実施理由と再実行条件を記録し、AWS E2E成功とは扱っていない（AC-002〜AC-008）
  - 依存: T061、T130、T204
  - 確認結果: deploy、Index ACTIVE、Seed初回と冪等再実行、7件の実Vector評価、Delta preview／明示SAVE／再取得、曖昧依頼の非保存、0件時の標準マスター継続、安全なopaque ref、DynamoDB Item、Logs／EMF、完全キーcleanupを確認した。期限切れrefは実時間で30分待機せずfake clock単体テストを証跡とした

## ドキュメント更新タスク

- [x] T200 `dynamodb-seed/README.md`を作成する
  - 対象: `dynamodb-seed/README.md`
  - 実施内容: ファイル構成、各Schema、Itemとの関係、Sample Project Delta、評価質問、`search_summary`だけがEmbedding生成元であること、生成Vectorを正本へ含めないこと、更新・validate・apply方法、禁止データ、ADR-0007へのリンクを記載する。
  - 完了条件: Sample Dataのレビュー・更新・検証・投入方法とEmbedding対象を、実装と矛盾なく理解できる（AC-002、AC-008）
  - 依存: T060

- [x] T201 [P] Agentドキュメントを更新する
  - 対象: `docs/Agent/README.md`
  - 実施内容: Manager／Estimation Agent／Estimation MCP Adapter／4 Toolの関係、Agent-as-Tool、保存意図3状態、0件継続、部分障害、環境変数、返却根拠を記載する。関係を説明するMermaid図を既存記法に合わせて追加または更新する。
  - 完了条件: 図がAgentとToolの公開境界および処理の委譲関係を説明し、本文・実装・ADRと整合し、Mermaid構文が正しく表示できる（AC-001、AC-006、AC-008）
  - 依存: T053

- [x] T202 [P] CDKドキュメントを更新する
  - 対象: `docs/CDK/README.md`
  - 実施内容: 単一テーブル、CloudFormation未対応のVector IndexをCustom Resource Providerで管理する理由、Gateway／Target／Lambda、IAM境界、ログ、CloudFormation出力、Seedをdeployから分離する理由を記載する。インフラ構成とProviderライフサイクルを説明するMermaid図を追加または更新する。
  - 完了条件: 図がRuntimeからGateway／Tool／DynamoDB／Bedrockまでの権限境界と、CloudFormationからProviderへのIndex管理フローを説明し、本文・実装・ADRと整合し、Mermaid構文が正しく表示できる（AC-005、AC-008）
  - 依存: T044

- [x] T203 [P] ルートREADMEへEstimation機能の導線を追加する
  - 対象: `README.md`
  - 実施内容: 利用可能なAgentへEstimation Agentを追加し、Sample Data、Agent、CDK、手動テスト、関連ADRへの主要リンクを追加する。公開HTTP／SSE契約を変更したように記載しない。
  - 完了条件: 初見の利用者が本PoCの目的と詳細文書へ到達でき、既存機能の説明と矛盾しない（AC-008）
  - 依存: T200、T201、T202

- [x] T204 手動確認手順を更新する
  - 対象: `docs/ManualTesting/README.md`
  - 実施内容: 環境前提、Budget 50%／80%／100%、deploy、Index確認、Seed、冪等再実行、評価質問、Sample Project Deltaのpreview／明示保存／曖昧保存、0件継続、安全なref、不正・別session・期限切れref、Draft再取得、Item、ログ・EMF、完全キーcleanup、期待値、注意点を記載する。主要シーケンスを説明するMermaid図を既存記法に合わせて追加または更新する。
  - 完了条件: 図が利用者、Manager、Estimation、Gateway／Tool、Bedrock、DynamoDB間の検索・参照・preview／SAVE・再取得を説明し、本文・実装・ADRと整合し、Mermaid構文が正しく表示できる。HIST-001 top-1、15.7人日、5.0／10.7人日、1,356,000円、1,695,000円、明示保存の同一turn保存、0件継続、評価範囲の限定、固定認証情報を記載しない注意が明記されている（AC-008）
  - 依存: T060、T061、T112、T200、T201、T202

## 完了確認

- [x] T300 `specs.md`の全受け入れ条件との対応を確認する
  - 対象: AC-001〜AC-008、T100〜T131の検証結果
  - 完了条件: 各受け入れ条件に成功した自動検証、手動検証、または明示された未実施理由が対応し、未確認条件を完了扱いしていない
  - 依存: T123、T131
  - 確認結果: AC-001〜AC-008へ、278件の自動テスト、CDK deploy、7件の検索品質評価、Runtime／Lambda／DynamoDB／CloudWatchの手動確認、および関連文書を対応付け、未確認条件がないことを確認した

- [x] T301 `plan.md`の実装方針と変更対象への適合を確認する
  - 対象: 実装差分、テスト、README、ADR、`specs/07-dynamodb-vector-search/plan.md`
  - 完了条件: 単一テーブル、固定Embedding、4 Tool、Custom Resource Provider、安全なref、明示保存、限定IAM、明示Seedの方針と実装が一致している
  - 依存: T300
  - 確認結果: 単一テーブル、Cohere固定Embedding、4 Tool、Custom Resource Provider、opaque ref、明示保存、権限分離、明示Seedの方針と実装・AWS構成が一致することを確認した

- [x] T302 対象外と既存公開契約への影響を確認する
  - 対象: feature全差分、既存回帰テスト
  - 完了条件: RFP全文解析、帳票、承認ワークフロー、汎用DB Tool、自動Seed、OpenAI Embeddings、Knowledge Base変更が含まれず、HTTP／SSE、Cognito、Memory、Weather、Knowledge契約を維持している
  - 依存: T301
  - 確認結果: 対象外機能やOpenAI Embeddings、Knowledge Base変更、汎用DB Tool、自動Seedを含まず、既存HTTP／SSE、Cognito、Memory、Weather、Knowledge契約を回帰テストで維持した

- [x] T303 差分の安全性とリポジトリ衛生を確認する
  - 対象: `git diff`、`git status --short`、Sample Data、生成物
  - 完了条件: シークレット、認証情報、実account ID／ARN／URLの固定値、実案件情報、生成Vector、AWS取得データ、state、一時ファイル、`cdk.out/`等の生成物、無関係な既存差分が成果物へ含まれていない
  - 依存: T302
  - 確認結果: AWS E2E出力を`/private/tmp`だけへ保存し、生成Vector、AWS取得データ、account ID、ARN、URL、通知先、opaque token、認証情報、state、`cdk.out/`を成果物へ含めていない。既存の未追跡`.DS_Store`と`.idea/`は変更していない

- [x] T304 実装・検証・文書の最終結果を記録する
  - 対象: `tasks.md`、テスト結果、AWS E2E結果、変更ファイル一覧
  - 完了条件: 完了タスク、実行コマンドと結果、未実施項目と理由、AWS操作の有無、レビューが必要な判断、残課題が追跡可能である
  - 依存: T303
  - 確認結果: 下記へローカル実装、AWS操作、失敗と修正、再検証、cleanup、残課題を記録し、全タスクの完了状態と実結果が追跡可能であることを確認した

## 実装・検証記録

### 2026-08-20 ローカル実装

- `uv lock --check`: 成功、102 packageのlock整合を確認。
- `uv run pytest -q`: 成功、276 passed。既知のStarlette、Pydantic、AgentCore SDK由来のdeprecation warningのみ。
- `uv run python app.py`: 成功。明示した一時`CDK_OUTDIR`へsynthし、テーブル、TTL、固定Vector Index、Provider、Estimation Gateway／Target／Lambda、LeadingKeys、固定Cohereモデル、Runtime環境変数を確認。Node 20 EOL warningがあるため開発環境はNode 22以上へ更新が必要。
- `uv run python scripts/estimation_seed.py validate --source dynamodb-seed`: 成功、AWS API書き込みなしで`VALID`。
- ローカルLambda fake入力: `NO_RESULTS`のcanonical envelopeを確認。
- Linux ARM64 build: Agent Runtime、Estimation Tools Lambda、Vector Index Providerの3 imageが成功。
- コンテナ内確認: Runtime import成功。両Lambdaはboto3／botocore `1.43.65`、`SearchVectors`、`UpdateTable.VectorIndexUpdates`、各handler importを確認。
- botocore service modelで`SearchVectors.SearchVector`がAttributeValue配列であることを確認し、Repositoryが1024個の`N`へ変換する契約と、Seedが生成VectorをDynamoDB保存前に`Decimal`へ変換する契約を自動テストへ追加。変更後のEstimation Tools ARM64 imageを再buildし、固定SDK、`SearchVectors`、Repository importを再確認。
- Lambda DTOでトップレベル、filter、project、componentの未知フィールドと不正な基準日を拒否し、SAVE応答が64 KiBを超える場合はDynamoDB書き込み前に拒否する回帰テストを追加。保存済みなのに応答だけ失敗する状態を作らないことを確認。
- 初回の全pytestはsandbox外のjsii cacheへ触れてcollection errorとなったため、`JSII_RUNTIME_PACKAGE_CACHE=/private/tmp/openaiagentcore-jsii-cache`を指定して再実行し成功。
- 初回Docker buildはcredential helperのPATH不足、その次はsandboxからDocker socketへ接続できず失敗した。Rancher DesktopのhelperをPATHへ追加し、許可されたDocker socketアクセスで再実行して3 imageとも成功。
- AWS APIによるdeploy、Seed、実Vector検索、Runtime呼び出し、Draft保存、Budget作成、cleanupは実行していない。

### 2026-08-20 AWS E2Eと最終確認

- ユーザーの明示承認後、対象profile `default`、region `us-east-1`でAWS E2Eを実施した。既存Cost Budget「月別予算」（15 USD）と既存subscriberを再利用し、`ACTUAL` 50%／80%／100%通知を確認した。通知先実値とaccount IDは記録していない。
- `cdk diff`でEstimation用テーブル、Vector Index Provider、Lambda、Gateway／Target、IAM、Runtime更新だけを確認した。
- 初回deployはVector IndexのSearchSchema属性定義不足、2回目はCreateTableへ非キー属性定義を追加したため失敗し、いずれもCloudFormation rollback完了を確認した。DynamoDB TableはPK／SKだけを`AttributeDefinitions`へ持たせ、Vector Index作成時の`UpdateTable`へSearchSchema属性定義を同時指定する形へ修正した。
- 修正後のdeployは`UPDATE_COMPLETE`。テーブル`ACTIVE`、Vector Index `ACTIVE`／1024次元／`COSINE`、Gateway／Target／Lambda／Runtimeの利用可能状態を確認した。
- Seed初回は`embedded=3`、`structured_upserted=15`。同一Seed再実行は`embedded=0`、`summary_skipped=3`となり、hash一致時のEmbeddingとSummary書き込みskipを確認した。
- 実Vector評価は正本6件とSample Project Deltaの計7件がすべて`passed=true`。各HISTの期待top-1と、Deltaの`HIST-001` top-1を確認した。評価範囲は`POC_SAMPLE_DATA_REGRESSION_ONLY`であり、本番検索品質の保証ではない。
- 初回Runtime previewで実モデルが予約引数と業務コード値を誤生成したため、モデル向けTool Schemaから内部予約引数を除去し、Tool descriptionとEstimation Agent指示へ固定コードの正規化規則を追加して再deployした。
- 修正後のDelta previewは非保存で、`HIST-001`、15.7人日、AWS_ARCHITECT 5.0人日、INFRA_ENGINEER 10.7人日、原価1,356,000円、価格1,695,000円、類似実績を自動補正しないこと、Multi-AZ追加工数未反映を確認した。
- Deltaの明示保存は追加確認なしの同一turnで`DRAFT`、version 1を保存した。初回再取得でDynamoDB Numberのversionが文字列化されRuntime Adapterに拒否されたため、公開DTOのversionだけを整数へ正規化し再deployした。修正後は同一actor/sessionと完全キーで保存時と同じ内訳・根拠・警告を再取得できた。
- 曖昧な「見積を作って」はpreviewのみで保存確認を求め、保存済み表現と保存IDを返さなかった。
- `MIGRATION`かつ`EC2_RDS_WEB`の0件ケースは同一turn保存を継続し、Itemで`similar_project_ids=[]`、`similar_project_search_status=NO_RESULTS`、`calculation_basis=STANDARD_MASTERS_ONLY`を確認した。
- opaque refは同一actor/sessionの未改変値で`OK`、1文字改変と別sessionで`CONTEXT_INVALID`、任意`project_id`追加で`VALIDATION_ERROR`を確認した。30分期限切れはDynamoDB Itemを改変せずfake clock単体テストで`ContextExpiredError`を確認した。
- CloudWatch LogsでEmbedding成功EMF、`EmbeddingCalls=1`、retry／throttle 0を確認した。入力案件名、`search_summary`、小文字`embedding`、`SearchVector`、単価、価格、認証情報形式の禁止文字列は0件だった。
- 確認用に保存したDeltaと0件ケースのDraftは、完全なproject／estimate／versionを指定して個別cleanupし、各`DELETED`を確認した。BatchGetで両Draftが消え、Seedの`PROJECT#HIST-001`／`SUMMARY`が残ることを確認した。
- 最終自動検証は通常275件が成功した。CDK asset stagingの一時パス競合で同時実行時に失敗した3件は、`/private/tmp`の独立basetempで再実行して3件すべて成功し、合計278件の成功を確認した。既知の95 deprecation warningのみ。
- `uv lock --check`、`git diff --check`は成功。途中で生成したignored `cdk.out/`は削除し、リポジトリへAWS E2E一時出力や生成Vectorを残していない。
