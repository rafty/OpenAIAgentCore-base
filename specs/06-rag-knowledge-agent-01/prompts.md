# for spec-draft.md - (1)
`specs/06-rag-knowledge-agent-01/discuss.md`に、 ChatGPTと会話した内容があります。
この`discuss.md`をもとに、`Managed Knowledge Base`をRAGとして使用する`AWS Knowledge Agent`を作成します。

依頼事項は、`discuss.md`に記載されている以下のサンプルmdを`<プロジェクトルート>/knowledge-base-s3`に作成してください。
メタデータも作成してください。

```text
standards/
  aws_architecture_standard.md
  security_standard.md
  monitoring_standard.md

estimation/
  estimation_guideline.md

projects/
  sample_project_alpha.md
```

# for spec-draft.md - (2)

`specs/06-rag-knowledge-agent-01/discuss.md`から要件概要`specs/06-rag-knowledge-agent-01/spec-draft.md`を作成してください。
`spec-draft.md`の記載方法やフォーマットは、`specs/03-agent-base-01/spec-draft.md`を参考にしてください。
私に確認したい事項があれば、質問をしてください。
また、上記で作成したmdをManaged Knowledge BaseのS3にAWS CDKで配置する要件をいれるようにしてください。

# for specs.md

skillのcreate-sdd-specを使って、`specs/06-rag-knowledge-agent-01/specs.md`を作成してください。
また、ADRを作成する場合、skillの`create-adr`を使ってください。


# for plan.md

specs.mdを作成しました。これをもとに、
skillのcreate-sdd-planを使って、`specs/06-rag-knowledge-agent-01/plan.md`を作成してください。
また、ADRを作成する場合、skillの`create-adr`を使ってください。


# for tasks.md

plan.mdを作成しました。これをもとに、
skillのcreate-sdd-tasksを使って、`specs/06-rag-knowledge-agent-01/tasks.md`を作成してください。
また、ADRを作成する場合、skillの`create-adr`を使ってください。


# for executing tasks

tasks.mdが完成したので、skillのexecution-sdd-tasksを使って、specs/06-rag-knowledge-agent-01/tasks.mdのタスクを実行し、完了してください。
specs/06-rag-knowledge-agent-01/specs.md、 specs/06-rag-knowledge-agent-01/plan.md、 `docs/ADR/`のADR を参照し、 
すべてのコンテキストを考慮してタスクリスト内のタスクを実装してください。 

タスクを順番に完了することに集中してください。 
タスクが完了したら、[x] を使用して完了マークを付けてください。 
各ステップが完了したら、タスクリストのマークとタスクの完了マーク [x] を更新することが非常に重要です。
実行が不可能なタスクの場合は、タスクの最後の行に`- 未実施理由:`を追加し、未実施の理由を記載してください。

あなたは、AI AgentやAWSの超優秀なエンジニアです。プロフェッショナルな視点で実装してください。


## ２度目以降のtasks.mdの実行

tasks.mdに完了マークがついてないタスクがあります。skillのexecution-sdd-tasksを使って、続けてタスクを実行してください。
タスクを順番に完了することに集中してください。
