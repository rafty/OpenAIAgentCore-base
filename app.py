#!/usr/bin/env python3

import aws_cdk as cdk

from agent_core_cdk_stack.agent_core_stack import  AgentCoreStack


app = cdk.App()
AgentCoreStack(app, "OpenAiAgentCoreBaseStack", )

app.synth()
