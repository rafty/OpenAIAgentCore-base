# Agent tool weather 要件ドラフト

## 要件概要
- AgentCore GatewayのMCPターゲットとしてLambda関数が`lambda_tools/weather/handler.py`に用意しました。
- このツールのスキーマは`lambda_tools/weather/tools.json`に用意しました。
- このGatewayターゲットは、`Weather Agent`が利用するものとして用意しました。
`lambda_tools/weather/handler.py`がGatewayターゲットとして動作するようにSpecを検討したいです。

## 質問
- ツールスキーマ`lambda_tools/weather/tools.json`はこの配置で問題ないですか？
- `lambda_tools/weather/handler.py`に問題はありませんか？

