#!/usr/bin/env python3

"""AgentCore PoCスタックを固定リージョンでsynthするCDKエントリーポイント。"""

import os

import aws_cdk as cdk

from agent_core_cdk_stack.agent_core_stack import AgentCoreStack


app = cdk.App()
# accountはCDK標準の解決方法に委ね、モデル提供リージョンだけを仕様どおり固定する。
AgentCoreStack(
    app,
    "OpenAiAgentCoreBaseStack",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region="us-east-2",
    ),
)

app.synth()
