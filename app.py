#!/usr/bin/env python3

"""AgentCore PoCスタックを固定リージョンでsynthするCDKエントリーポイント。"""

import os

import aws_cdk as cdk

from agent_core_cdk_stack.agent_core_stack import AgentCoreStack


app = cdk.App()
# Managed Knowledge Baseとモデルを同一リージョンで利用するため、PoC全体を
# 対応リージョンのus-east-1へ固定し、cross-region構成を作らない。
AgentCoreStack(
    app,
    "OpenAiAgentCoreBaseStack",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region="us-east-1",
    ),
)

app.synth()
