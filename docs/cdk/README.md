# AWS CDK Pythonプロジェクトへようこそ

このプロジェクトは、Pythonで開発し、[uv](https://docs.astral.sh/uv/)で依存関係を管理するAWS CDKプロジェクトです。

`cdk.json`には、AWS CDK ToolkitがCDKアプリケーションをどのように実行するかを定義します。

このプロジェクトでは、CDKアプリケーションを`uv`経由で実行するように設定しています。

```json
{
  "app": "uv run python app.py"
}
```

## 前提ソフトウェア

このプロジェクトを使用する前に、次のソフトウェアをインストールしてください。

* Python
* uv
* Node.js
* AWS CDK Toolkit
* AWS CLI

インストールされているバージョンは、次のコマンドで確認できます。

```bash
python3 --version
uv --version
node --version
cdk --version
aws --version
```

## 依存関係のインストール

Pythonの依存関係は`pyproject.toml`に定義され、具体的なバージョンは`uv.lock`に固定されています。

リポジトリをクローンした後、次のコマンドを実行してください。

```bash
uv sync
```

このコマンドを実行すると、`.venv`仮想環境が自動的に作成され、`uv.lock`に記録された依存関係がインストールされます。

仮想環境を手動で有効化する必要はありません。

## 依存関係の追加

アプリケーションで使用する依存関係を追加するには、次のコマンドを実行します。

```bash
uv add <パッケージ名>
```

例：

```bash
uv add boto3
```

テストや開発時にのみ使用する開発用依存関係を追加するには、次のコマンドを実行します。

```bash
uv add --dev <パッケージ名>
```

例：

```bash
uv add --dev pytest
```

依存関係を追加または更新した場合は、次の2つのファイルをGitにコミットしてください。

```text
pyproject.toml
uv.lock
```

`.venv`ディレクトリはGitにコミットしないでください。

## テストの実行

テストは`uv`経由で実行します。

```bash
uv run pytest
```

## CloudFormationテンプレートの生成

次のコマンドを実行します。

```bash
cdk synth
```

AWS CDK Toolkitは`cdk.json`を読み込み、内部で次のコマンドを実行してCDKアプリケーションを起動します。

```bash
uv run python app.py
```

Pythonアプリケーションを直接実行することもできます。

```bash
uv run python app.py
```

## AWS環境のブートストラップ

AWSアカウントおよびリージョンへ初めてデプロイする前に、CDKのブートストラップを実行してください。

```bash
cdk bootstrap
```

AWSアカウントIDとリージョンを明示的に指定する場合は、次のように実行します。

```bash
cdk bootstrap aws://<AWSアカウントID>/<AWSリージョン>
```

例：

```bash
cdk bootstrap aws://123456789012/ap-northeast-1
```

## 主なコマンド

* `uv sync`：Pythonの依存関係をインストールし、仮想環境を同期します
* `uv run pytest`：テストを実行します
* `uv add <パッケージ名>`：アプリケーション用の依存関係を追加します
* `uv add --dev <パッケージ名>`：開発用の依存関係を追加します
* `cdk ls`：CDKアプリケーションに含まれるスタックを一覧表示します
* `cdk synth`：CloudFormationテンプレートを生成します
* `cdk diff`：デプロイ済みのスタックと現在のコードとの差分を表示します
* `cdk deploy`：設定されたAWSアカウントおよびリージョンへスタックをデプロイします
* `cdk destroy`：デプロイ済みのスタックを削除します
* `cdk docs`：AWS CDKのドキュメントを開きます

## プロジェクト構成

```text
.
├── app.py
├── cdk.json
├── pyproject.toml
├── uv.lock
├── <プロジェクトパッケージ>/
│   ├── __init__.py
│   └── <プロジェクトパッケージ>_stack.py
└── tests/
```

主なファイルの役割は次のとおりです。

* `app.py`：CDKアプリケーションを定義し、スタックを生成します
* `cdk.json`：AWS CDK Toolkitがアプリケーションを実行する方法を定義します
* `pyproject.toml`：Pythonプロジェクトの情報と依存関係を定義します
* `uv.lock`：実際に使用する依存パッケージのバージョンを固定します
* `<プロジェクトパッケージ>_stack.py`：スタック内に作成するAWSリソースを定義します

## 基本的な開発手順

通常は、次の順序でコマンドを実行します。

```bash
uv sync
uv run pytest
cdk synth
cdk diff
cdk deploy
```
