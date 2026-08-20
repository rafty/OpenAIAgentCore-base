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


# for plan.md
specs.mdが完成したので、skillのcreate-sdd-planを使って、specs/07-dynamodb-vector-search/plan.mdを作成してください。


# for tasks.md
plan.mdが完成したので、skillのcreate-sdd-tasksを使って、specs/07-dynamodb-vector-search/tasks.mdを作成してください。


# for executing tasks
tasks.mdが完成したので、specs/07-dynamodb-vector-search/tasks.mdのタスクを実行し、完了してください。
specs/07-dynamodb-vector-search/specs.md、 specs/07-dynamodb-vector-search/plan.md、 `docs/ADR/`のADR を参照し、 すべてのコンテキストを考慮してタスクリスト内のタスクを実装してください。 
タスクを順番に完了することに集中してください。 
タスクが完了したら、[x] を使用して完了マークを付けてください。 
各ステップが完了したら、タスクリストのマークとタスクの完了マーク [x] を更新することが非常に重要です。
実行が不可能なタスクの場合は、タスクの最後の行に`- 未実施理由:`を追加し、未実施の理由を記載してください。

あなたは、AI AgentやAWSの超優秀なエンジニアです。プロフェッショナルな視点で実装してください。


## ２度目以降のtasks.mdの実行
tasks.mdに完了マークがついてないタスクがあります。続けてタスク実行を実施してください。
