"""Wrap an existing agent with Destiny enhancement."""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from destiny import AgentPlan, FunctionTool, Runtime


class EchoAgent:
    name = "echo-agent"

    def plan(self, task, context):
        return AgentPlan(
            task=task,
            tool_name="Echo",
            tool_args={"message": task},
            rationale="Use the Echo tool to demonstrate guarded execution.",
        )

    def reflect(self, plan, run, context):
        tool_result = run.tool_results[plan.tool_name]
        return {
            "status": run.status.value,
            "tool_ok": tool_result.ok,
            "data": tool_result.data,
        }


def echo_tool(args, context):
    return {
        "message": args["message"],
        "enhanced_by": "destiny-runtime",
        "path": context["node_history"],
    }


runtime = Runtime.from_config(
    os.path.join(os.path.dirname(__file__), "destiny.toml"),
    tools=[FunctionTool(name="Echo", required=("message",), handler=echo_tool)],
)

agent = runtime.enhance(EchoAgent())
outcome = agent.run("hello enhanced agent", run_id="enhanced-agent-demo")

print(outcome.answer)
