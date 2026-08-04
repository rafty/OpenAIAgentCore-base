import aws_cdk as core
import aws_cdk.assertions as assertions

from agent_core_cdk_stack.agent_core_stack import AgentCoreStack

# example tests. To run these tests, uncomment this file along with the example
# resource in agent_core_cdk_stack/agent_core_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = AgentCoreStack(app, "open-ai-agent-core-base")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
