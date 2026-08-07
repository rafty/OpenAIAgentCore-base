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
