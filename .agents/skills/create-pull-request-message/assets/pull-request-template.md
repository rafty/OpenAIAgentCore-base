# Pull Request Message Template

<!--
このテンプレートは、要件ブランチ全体の差分に対応するPull Requestタイトルと本文を作成するために使用する。
生成するメッセージには、未使用のプレースホルダーやこのコメントを残さない。
確認できない情報を推測で補わない。
-->

## Pull Requestタイトル

```text
{{TYPE}}{{BREAKING_MARK}}{{SCOPE}}: {{PR_SUMMARY}}
```

## Pull Request本文

```markdown
## 概要

{{OVERVIEW}}

## 背景・目的

{{BACKGROUND_AND_PURPOSE}}

## 変更内容

- {{CHANGE_1}}
- {{CHANGE_2}}
- {{CHANGE_3}}

## SDD成果物

- `{{FEATURE_DIR}}/specs.md`
- `{{FEATURE_DIR}}/plan.md`
- `{{FEATURE_DIR}}/tasks.md`
- {{RELATED_ADR_OR_DOCUMENT}}

## 対応タスク

- {{TASK_ID_AND_SUMMARY}}

## 検証結果

- [ ] {{VALIDATION_ITEM_1}}: {{RESULT}}
- [ ] {{VALIDATION_ITEM_2}}: {{RESULT}}

### 未実施の検証

- {{NOT_EXECUTED_VALIDATION_AND_REASON}}

## レビュー観点

- {{REVIEW_POINT_1}}
- {{REVIEW_POINT_2}}

## 対象外

- {{OUT_OF_SCOPE_ITEM}}

## 関連情報

- Issue: {{ISSUE_REFERENCE}}
- ADR: {{ADR_REFERENCE}}
- 関連文書: {{DOCUMENT_REFERENCE}}

## 未確定事項・後続課題

- {{OPEN_QUESTION_OR_FOLLOW_UP}}
```

<!--
タイトル:
- TYPEはブランチ全体の目的に合わせる。
- BREAKING_MARKは破壊的変更の場合だけ ! を使用する。
- SCOPEは必要な場合だけ括弧を含めて記載する。
- PR_SUMMARYは要件として実現した内容を簡潔な日本語で記載する。

本文:
- 差分に含まれない項目は記載しない。
- SDD成果物が差分に含まれない場合は「SDD成果物」節を削除する。
- 対応タスクを確認できない場合は「対応タスク」節を削除するか、未確認と明記する。
- 検証結果のチェックは、実施済みの場合だけ [x] にする。
- 未実施の検証がない場合は、その小節を削除する。
- 関連情報がない項目は削除する。
- 未確定事項や後続課題がない場合は、その節を削除する。
-->
