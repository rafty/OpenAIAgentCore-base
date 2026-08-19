# for spec-draft.md

specs/07-dynamodb-vector-search/discuss.mdに記載のように、最終的なシステム方針が見えてきました。
しかし、現プロジェクトはAgentCoreのPoCなので、AgentがDynamoDBを使う例をPoC実装したいと思います。

discuss.mdの中で、Estimation AgentがDynamoDBの情報取得、入力、Vector検索を含むユースケースを一つ実装したいです。
そのユースケースを一つ考えてください。
さらに、そのユースケースにおいて、ユーザが利用時に入れる情報、事前にDynamoDBに入れておく情報などを
サンプルデータとして作りたいので、どういうものが必要か考えてください。

その結果を、`specs/07-dynamodb-vector-search/spec-draft.md`に記載してください。


# for specs.md
skillのcreate-sdd-specを使って、spec-draft.mdを参照し、specs/07-dynamodb-vector-search/specs.mdを作成してください。
また、specs.mdには、追加したユースケースに関する`手動確認`の手順をdocs/ManualTesting/README.mdに記載するという要件も追加してください。

