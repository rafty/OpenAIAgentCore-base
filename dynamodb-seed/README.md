# Estimation DynamoDB Sample Data

このディレクトリは、AWSインフラ構築見積PoCでDynamoDBへ事前登録する架空データと、利用時入力・検索品質評価ケースの正本です。`knowledge-base-s3/`と同様に、人がレビューできるJSONとJSON Schemaを成果物として管理します。生成したEmbedding、AWSから取得した値、認証情報は保存しません。

## ファイル構成

```text
dynamodb-seed/
├── projects/
│   ├── project-summaries.json
│   └── project-actuals.json
├── masters/
│   ├── effort-standards.json
│   ├── rate-cards.json
│   └── pricing-policies.json
├── evaluation/search-quality-cases.json
├── sample-inputs/sample-project-delta.json
└── schemas/*.schema.json
```

| 正本 | DynamoDB Item／用途 |
| --- | --- |
| `project-summaries.json` | `PK=PROJECT#<project_id>`、`SK=SUMMARY`。Vector検索対象の案件概要と固定filterを保持 |
| `project-actuals.json` | `PK=PROJECT#<project_id>`、`SK=ACTUAL#FINAL`。正式な工数、工期、役割別実績を保持 |
| `effort-standards.json` | `MASTER#EFFORT#<service>#<task_type>`。承認済み標準工数 |
| `rate-cards.json` | `MASTER#RATE#<role>`。承認済み日額単価 |
| `pricing-policies.json` | `MASTER#PRICING#<policy_id>`。リスク、粗利、丸め規則 |
| `search-quality-cases.json` | 期待top-1を持つ6件のSample Data回帰ケース。DynamoDBへ投入しない |
| `sample-project-delta.json` | 利用者プロンプトと正規化入力。事前登録せず、Runtime E2Eと自動テストに使用 |

各ファイルは`schemas/`の同名Schemaで型、必須属性、列挙値、追加属性を検証します。さらに、案件IDの一意性、サマリーと実績の対応、評価ケースの参照先、各HISTを期待第1位とするケース数をコードで相互検証します。

## Embedding生成対象

Embedding生成元は、過去案件サマリーItemの文字列属性`search_summary`だけです。`project_id`、案件名、filter属性、正式実績、標準工数、単価、価格、Sample Project Deltaの全文を連結しません。

Seed CLIは`search_summary`をNFKCと空白規則で正規化し、Amazon Bedrockの`cohere.embed-multilingual-v3`へ`input_type=search_document`で渡します。1024次元VectorはDynamoDB Itemの`embedding`へ実行時に追加し、モデル、次元、正規化version、source hash、生成日時も同じItemへ記録します。検索時は同じアダプターを`input_type=search_query`で使用します。詳細な固定条件は[ADR-0007](../docs/ADR/adr-0007-use-bedrock-cohere-multilingual-embeddings-for-dynamodb-vector-search.md)を参照してください。

生成Vectorを正本JSONへ書かない理由は、レビュー可能な入力とモデル依存の生成値を分離し、モデル変更時に正本へ巨大な機械差分を混ぜないためです。

## 検証と投入

AWSへ接続せず、正本一式を検証します。引数なしでもvalidate-onlyです。

```bash
uv run python scripts/estimation_seed.py validate --source dynamodb-seed
```

AWSへの投入は、対象アカウント、profile、`us-east-1`、予算通知、デプロイ済みstackを確認し、明示承認を得た場合だけ行います。`--apply`なしでは書き込みません。

```bash
uv run python scripts/estimation_seed.py apply --apply
```

CLIはCloudFormationの`EstimationTableName`と`EstimationVectorIndexName`を解決し、Indexの`ACTIVE`を待ってから投入します。同じモデル条件と`embedding_source_hash`が既存Itemに一致する案件サマリーは、Bedrock呼び出しと書き込みをskipします。実績とマスターは同じ完全キーへ冪等upsertします。CDK deployからは自動投入しません。

評価は正本6件とSample Project Deltaの計7件を実Vector検索へ渡します。

```bash
uv run python scripts/estimation_vector_e2e.py evaluate \
  --output /tmp/estimation-vector-evaluation.json
```

これは架空のSample Data内で期待top-1を確認する回帰評価であり、本番検索品質の証明ではありません。COSINE scoreの絶対値は合否条件にしません。

## 更新時の注意

- 実案件、顧客名、個人情報、秘密情報、account ID、ARN、URL、認証情報を追加しない。
- `embedding`、Vector、生成日時、AWS応答をJSONへ追加しない。
- `HIST-001`～`HIST-003`のサマリーと正式実績を同時に保守する。
- 各HISTを期待top-1とする評価ケースを2件以上維持する。
- 標準工数、単価、価格は架空値であり、`approval_status`、有効期間、versionを明示する。
- 変更後はvalidate-onlyと自動テストを実行し、実投入は別途明示承認を得る。
