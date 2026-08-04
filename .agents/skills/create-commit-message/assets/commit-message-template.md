# Commit Message Template

<!--
このテンプレートは、ステージ済み差分に対応するコミットメッセージを作成するために使用する。
生成するメッセージには、未使用のプレースホルダーやこのコメントを残さない。
本文とfooterは、必要な場合だけ追加する。
-->

```text
{{TYPE}}{{BREAKING_MARK}}{{SCOPE}}: {{SUMMARY}}

{{BODY}}

{{FOOTERS}}
```

<!--
TYPE:
feat / fix / docs / test / refactor / perf / build / ci / chore / style / revert

BREAKING_MARK:
破壊的変更の場合だけ ! を使用する。それ以外は空にする。

SCOPE:
必要な場合だけ、括弧を含めて記載する。例: (cdk)、(agent)、(sdd)
不要な場合は空にする。

SUMMARY:
ステージ済み差分の中心的な変更を、簡潔な日本語で記載する。末尾に句点を付けない。

BODY:
summaryだけでは分からない変更理由、影響、注意事項がある場合に記載する。
複数の変更目的が含まれる場合は、主要な変更群を箇条書きで整理できる。

FOOTERS:
関連タスクや破壊的変更など、必要な情報だけ記載する。
例:
Tasks: T010, T020
BREAKING CHANGE: <互換性への影響と移行方法>
-->
