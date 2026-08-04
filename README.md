# 仕様駆動開発(SDD) ガイド

このプロジェクトでは、Amazon Bedrock AgentCoreを複数人で開発するために、仕様駆動開発（SDD / Spec-Driven Development）を採用しています。

実装前に仕様、実装計画、実装タスクを段階的に整理し、要件単位のブランチとPull Requestでレビュー可能な状態を保ちながら開発を進めます。

SDDの基本方針、具体的な実施手順、共同開発のルールは、次のドキュメントを参照してください。

- [SDDガイド](docs/SDD/README.md)
- [SDDの実施手順](docs/SDD/workflow.md)
- [SDD共同開発ルール](docs/SDD/team-development.md)

# AWS CDK Pythonプロジェクト

このプロジェクトは、Pythonで開発し、[uv](https://docs.astral.sh/uv/)で依存関係を管理するAWS CDKプロジェクトです。

`cdk.json`には、AWS CDK ToolkitがCDKアプリケーションをどのように実行するかを定義します。

このプロジェクトでは、CDKアプリケーションを`uv`経由で実行するように設定しています。

[docs/CDK/README.md](docs/CDK/README.md)
