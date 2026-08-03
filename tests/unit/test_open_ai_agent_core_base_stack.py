import aws_cdk as core
import aws_cdk.assertions as assertions

from open_ai_agent_core_base.open_ai_agent_core_base_stack import OpenAiAgentCoreBaseStack

# example tests. To run these tests, uncomment this file along with the example
# resource in open_ai_agent_core_base/open_ai_agent_core_base_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = OpenAiAgentCoreBaseStack(app, "open-ai-agent-core-base")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
