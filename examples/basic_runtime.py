"""Minimal embeddable Runtime example."""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from destiny import FunctionTool, Runtime


def echo_tool(args, context):
    return {
        "message": args["message"],
        "node_history": context["node_history"],
    }


runtime = Runtime.from_config(
    os.path.join(os.path.dirname(__file__), "destiny.toml"),
    tools=[
        FunctionTool(
            name="Echo",
            required=("message",),
            handler=echo_tool,
        )
    ],
)

result = runtime.run(
    task="echo a message",
    tool_name="Echo",
    tool_args={"message": "hello production baseline"},
)

print(result.status.value)
print(result.tool_results["Echo"].data)
