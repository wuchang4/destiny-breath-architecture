"""Use model and memory providers from an enhanced agent."""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from destiny import AgentPlan, FunctionTool, KeywordMemoryProvider, Runtime, StaticModelProvider


class ProviderAgent:
    name = "provider-agent"

    def plan(self, task, context):
        message = context["model"].complete(task, context)
        return AgentPlan(task=task, tool_name="Remember", tool_args={"message": message})

    def reflect(self, plan, run, context):
        return [record.content for record in context["memory"].search("agent memory")]


def remember_tool(args, context):
    record = context["memory"].put("last", args["message"], {"source": "remember_tool"})
    return {"key": record.key}


runtime = Runtime.from_config(
    os.path.join(os.path.dirname(__file__), "destiny.toml"),
    tools=[FunctionTool(name="Remember", required=("message",), handler=remember_tool)],
    model_provider=StaticModelProvider("agent memory from provider"),
    memory_provider=KeywordMemoryProvider(),
)

outcome = runtime.enhance(ProviderAgent()).run("store useful memory")
print(outcome.answer)
