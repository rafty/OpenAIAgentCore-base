```text
OpenAI Agent SDKで作成したas ToolのマルチエージェントをAmazon Bedrock AgentCoreで動作させるPoCを作成しています。
マネージャーAgentがおり、as Tool型のAgentとして、Weather Agentがあります。
Weather Agentは、Bedrock AgentCore GatewayのMCPターゲットとしてLambda関数を使用しています。

このPoCの目的は、将来的には、AWSシステム構築案件の見積もりするAgentを作成するためのもので、
AWSでAgentを構築するために色々なシステムを組み込む検証をしています。

現在は、Weather Agentに、Bedrock AgentCore GatewayのMCPターゲットを持たせて、天気情報を返すAgentを作成しています。

次に検証したいのは、S3を使ったAmazon Bedrock Managed Knowledge Baseです。
Amazon Bedrock Managed Knowledge BaseをRAGとして使うAgentをas Tool型で追加するということを想定しています。

そこで質問があります。

- RAGを検証するために新たなas Tool型のAgentを追加する考えでよいですか？
- RAGの検証につかうためにS3に置くドキュメントはどんなものがよいですか？
- 新たなAgentは、どんな役割で、どんな名前のAgentが良いでしょうか？
```

はい。今回のPoCの目的を考えると、**RAG専用のas Tool型Agentを1つ追加する**進め方がよいと思います。

特に現在のAgentCore Gatewayは、**Amazon Bedrock Managed Knowledge BasesをConnector Targetとして直接追加でき、MCPツールとして `Retrieve` と `AgenticRetrieveStream` を公開できます**。そのため、Weather Agentと似た形で「専門Agent → AgentCore Gateway → AWSサービス」という構造を作れます。([AWS ドキュメント][1])

私なら、まず次の形にします。

```text
User
  |
  v
Manager Agent
  |
  +-- Weather Agent        [as_tool]
  |      |
  |      v
  |   AgentCore Gateway
  |      |
  |      v
  |   Lambda
  |      |
  |      v
  |   Weather API
  |
  +-- AWS Knowledge Agent  [as_tool]
         |
         v
      AgentCore Gateway
         |
         v
      Managed Knowledge Bases Connector
         |
         v
      Bedrock Managed Knowledge Base
         |
         v
         S3
```

OpenAI Agents SDKでも、`Agent.as_tool()` は「Managerが会話の制御を維持したまま、専門Agentに限定された仕事を任せる」パターンとして位置付けられています。
今回のManager + Weather Agent + Knowledge Agentは、かなり素直な適用例です。([OpenAI GitHub Pages][2])

## 1. RAG検証のために新しいas Tool型Agentを追加してよいか

**はい。PoCとしては追加することをおすすめします。**

ただし、「RAGだから必ずAgentを分ける必要がある」という意味ではありません。

例えば本番システムで単純にKnowledge Baseを1回検索するだけなら、

```text
Manager Agent
    |
    +-- Knowledge Base MCP Tool
```

として、Manager自身から `Retrieve` を直接呼ばせる方がシンプルな場合もあります。

今回あえて

```text
Manager
   ↓ as_tool
Knowledge Agent
   ↓ MCP
Knowledge Base
```

とするメリットは、**マルチエージェント構成そのものを検証できること**です。

Weather AgentとKnowledge Agentで性質が明確に違います。

| Agent           | 主な役割      | 情報源                 |
| --------------- | --------- | ------------------- |
| Weather Agent   | 外部の最新情報取得 | API / Lambda        |
| Knowledge Agent | 蓄積済み知識の検索 | S3 / Knowledge Base |

Managerに、

* 「東京の天気を教えて」→ Weather Agent
* 「当社標準では本番環境のバックアップ保持期間は？」→ Knowledge Agent
* 「明日の東京の天気を考慮して、当社の屋外作業ルールを確認して」→ **両方のAgent**

という振り分けをさせられます。

この最後のケースまで試すと、**Managerが複数のas Tool Agentを選択・組み合わせられるか**の検証にもなります。

---

## 2. S3にはどんなドキュメントを置くのがよいか

将来的な「AWSシステム構築案件の見積Agent」を意識するなら、**AWS公式ドキュメントをコピーして入れるより、架空の「社内AWS構築標準・見積基準」を作る**ことをおすすめします。

理由はかなり重要です。

例えば、

> EC2とは何ですか？

という情報をKnowledge Baseに入れてテストすると、モデル自身がEC2を知っているため、**本当にRAGから回答したのか判定しにくくなります**。

逆に、

> 当社の標準では、本番環境のEC2は原則2AZ構成とする。
> CloudWatch Logsの保持期間は標準90日とする。
> 詳細設計はEC2 1台につき0.5人日として見積もる。

という**架空の社内ルール**なら、Knowledge Baseを検索しない限り答えられません。

RAGの検証にはこちらの方が適しています。

### 私なら最初は5ファイル程度作ります

```text
s3://poc-knowledge-base/

  standards/
    aws_architecture_standard.md
    security_standard.md
    monitoring_standard.md

  estimation/
    estimation_guideline.md

  projects/
    sample_project_alpha.md
```

内容は例えばこうします。

**`aws_architecture_standard.md`**

```text
# AWS標準アーキテクチャ

## EC2

本番環境では原則として2つ以上のAvailability Zoneを利用する。

WebサーバーはApplication Load Balancer配下に配置する。

EC2への直接SSH接続は禁止し、
AWS Systems Manager Session Managerを使用する。

## RDS

本番環境のRDSは原則Multi-AZ構成とする。

バックアップ保持期間は14日間とする。
```

**`monitoring_standard.md`**

```text
# 監視標準

## CloudWatch Logs

本番環境のログ保持期間は90日とする。
開発環境は30日とする。

## アラーム

CPU使用率80%以上が5分間継続した場合、
Warningアラームを発報する。

CPU使用率90%以上が5分間継続した場合、
Criticalアラームを発報する。
```

そして将来の目的に一番つながるのが、次です。

**`estimation_guideline.md`**

```text
# AWS構築見積ガイドライン

## EC2

EC2の基本設計:
1システムあたり 1.0人日

EC2の詳細設計:
1サーバーあたり 0.5人日

EC2の構築:
1サーバーあたり 0.5人日

単体テスト:
1サーバーあたり 0.3人日


## RDS

RDS基本設計:
1DBあたり 1.5人日

RDS詳細設計:
1DBあたり 1.0人日

RDS構築:
1DBあたり 0.5人日


## CloudWatch

監視設計:
1システムあたり 1.0人日

アラーム設定:
1アラームあたり 0.1人日
```

例えばユーザーが、

> EC2 4台、RDS 1台のシステムを構築するとき、当社標準の詳細設計工数を教えて

と聞いたとします。

Knowledge Agentが、

```text
EC2:
0.5人日 × 4台 = 2.0人日

RDS:
1.0人日 × 1DB = 1.0人日

合計:
3.0人日
```

と回答できれば、**将来作ろうとしている見積Agentにかなり近いPoC**になります。

ただし将来的には、「見積基準を検索すること」と「数量×単価を計算すること」は分離した方が設計しやすいです。

---

## 3. 新しいAgentの役割と名前

私なら、最初は **`AWS Knowledge Agent`** にします。

役割は、

> AWSシステム構築に関する社内標準、設計基準、見積基準、過去案件情報などをKnowledge Baseから検索し、根拠となる情報をManager Agentへ返す専門Agent

です。

つまり、このAgent自身には「見積を完成させる責任」は持たせません。

```text
AWS Knowledge Agent

責務:
  Knowledge Baseを検索する
       ↓
  関連する情報を取り出す
       ↓
  根拠とともにManagerへ返す
```

くらいに限定します。

名前の候補を比較すると、

| 名前                         |    評価 | コメント             |
| -------------------------- | ----: | ---------------- |
| `KnowledgeAgent`           |     ○ | シンプルだが少し抽象的      |
| `RAGAgent`                 |     △ | 実装方式が名前になってしまう   |
| `AWSKnowledgeAgent`        | **◎** | 今回のPoCに分かりやすい    |
| `EstimationAgent`          |     △ | 現段階では見積Agentではない |
| `EstimationKnowledgeAgent` |     ○ | 将来用途を強く意識するならあり  |
| `ProjectKnowledgeAgent`    |     ○ | 過去案件も扱うならよい      |

現段階では **`AWSKnowledgeAgent`** が一番扱いやすいと思います。

例えばAgentのinstructionsは概念的には、

```text
あなたはAWSナレッジエージェントです。

あなたの役割は、管理されたナレッジベースから、AWSのアーキテクチャ標準、セキュリティ標準、監視標準、および見積もりガイドラインに関する情報を取得することです。

社内標準や見積もりルールに関する質問に回答する際は、必ずナレッジベースを検索してください。

ナレッジベースに含まれていない情報を独自に作成（捏造）しないでください。

関連情報が見つからない場合は、その旨を明確に伝えてください。

マネージャーエージェントが最終的な回答に利用できるよう、該当するソース情報を提示してください。
```

くらいにしておくと、RAGの挙動を観察しやすいと思います。

---

## 4. AgentCore GatewayはLambdaを挟まなくてよい

ここは今回のPoCで特に試す価値があります。

Weather Agentでは、

```text
Weather Agent
    ↓ MCP
AgentCore Gateway
    ↓
Lambda
```

ですが、Managed Knowledge Baseについては現在、AgentCore Gatewayに**Managed Knowledge Bases用の組み込みConnector Target**があります。`Retrieve` と `AgenticRetrieveStream` の2つをMCPツールとして公開できます。([AWS ドキュメント][1])

したがってRAG側は、

```text
AWS Knowledge Agent
        |
        | MCP
        v
AgentCore Gateway
        |
        | Managed KB Connector
        v
Bedrock Managed Knowledge Base
        |
        v
       S3
```

にできます。

個人的には、PoCではこちらを試す価値が高いと思います。

Weather側では、

> Gateway → Lambdaというカスタムツール連携

RAG側では、

> Gateway → AWS Managed Serviceの組み込みConnector

という**2種類のGateway利用方法を同じマルチエージェントで検証できる**からです。

---

## 5. 最初は `Retrieve` から試すのがおすすめ

AgentCore GatewayのManaged Knowledge Base Connectorには、

* `Retrieve`
* `AgenticRetrieveStream`

があります。AWSの現在のドキュメントでは、`Retrieve` は単一検索、`AgenticRetrieveStream` は複数ステップのagentic retrievalとして説明されています。([AWS ドキュメント][1])

最初は、

```text
AWS Knowledge Agent
    ↓
Retrieve
    ↓
関連chunk取得
    ↓
Knowledge AgentのLLMで回答生成
```

がよいと思います。

これなら、

1. S3文書が正しくIngestionされたか
2. Embeddingされたか
3. 検索クエリが正しいか
4. どのchunkが返ったか
5. Agentが取得結果から回答できたか
6. Managerが正しくAWS Knowledge Agentを選択したか

を比較的切り分けやすくなります。

その後、

```text
Retrieve
        ↓
AgenticRetrieveStream
```

へ進めれば、「普通のRAG」と「Agentic RAG」の違いもPoCできます。

---

## 6. RAG検証ではMarkdown + metadataをおすすめします

S3 Knowledge Baseの入力には、TXT、Markdown、HTML、Word、CSV、Excel、PDFなどが現在サポートされています。([AWS ドキュメント][3])

最初は **Markdown** が扱いやすいです。

```text
aws_architecture_standard.md
security_standard.md
monitoring_standard.md
estimation_guideline.md
sample_project_alpha.md
```

次のステップでmetadataを追加します。

Bedrock Knowledge BasesのS3データソースでは、各ドキュメントにsidecarの `.metadata.json` を付与でき、検索時のフィルタリングにも利用できます。([AWS ドキュメント][4])

例えば、

```text
estimation_guideline.md
estimation_guideline.md.metadata.json
```

として、

```json
{
  "metadataAttributes": {
    "document_type": "estimation",
    "version": "1.0",
    "system_type": "aws"
  }
}
```

といった分類を持たせるイメージです。

さらに、

```text
document_type:
  architecture
  security
  monitoring
  estimation
  past_project

environment:
  production
  staging
  development

service:
  ec2
  rds
  cloudwatch
  vpc
```

などを試すと、**単純なVector Searchだけでなくmetadata filterの検証**へ発展させられます。

---

## 最終的に目指す形も見えてきます

今回のPoCから見積Agentへ発展させるなら、私は最終的にはこう分けます。

```text
                     Manager Agent
                           |
          +----------------+----------------+
          |                |                |
          v                v                v
   Knowledge Agent   Pricing Agent    Estimation Agent
          |                |                |
          v                v                |
    Knowledge Base     AWS Pricing          |
          |             API等               |
          |                |                |
          +----------------+----------------+
                           |
                           v
                    見積結果を生成
```

**Knowledge Baseには「変わりにくい社内知識」を置く**のがよいと思います。

例えば、

* 標準アーキテクチャ
* 社内設計ルール
* セキュリティ基準
* 見積工数基準
* 作業項目
* 過去案件
* 見積前提条件
* 除外事項

です。

一方、**AWSサービスの現在価格のように頻繁に変わるデータは、将来的にはKnowledge BaseではなくPricing APIなどのToolから取得する**という責務分離がしやすくなります。

なので、今回の次の一手としては、

```text
Manager Agent
│
├── Weather Agent
│      └── AgentCore Gateway
│             └── Lambda
│
└── AWS Knowledge Agent
       └── AgentCore Gateway
              └── Managed Knowledge Bases Connector
                     └── Bedrock Managed KB
                            └── S3
```

**この構成をかなりおすすめします。**

そしてS3には、一般的なAWS説明資料ではなく、**「架空の社内AWS構築標準＋架空の見積基準」**を入れるのがポイントです。これなら「RAGを使わなければ回答できない問い」を意図的に作れるので、検証結果が非常に分かりやすくなります。

[1]: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-api-target-config.html "Define the gateway target configuration - Amazon Bedrock AgentCore"
[2]: https://openai.github.io/openai-agents-python/multi_agent/ "Agent orchestration - OpenAI Agents SDK"
[3]: https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-ds.html "Prerequisites for your Amazon Bedrock knowledge base data - Amazon Bedrock"
[4]: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-metadata.html "Include metadata in a data source to improve knowledge base query - Amazon Bedrock"
