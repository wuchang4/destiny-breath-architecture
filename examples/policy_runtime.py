"""Use PolicyHook to block tasks or tools before execution."""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from destiny import FunctionTool, PolicyHook, Runtime


def echo_tool(args, context):
    return {"message": args["message"]}


runtime = Runtime.from_config(
    os.path.join(os.path.dirname(__file__), "destiny.toml"),
    tools=[FunctionTool(name="Echo", required=("message",), handler=echo_tool)],
    hooks=[
        PolicyHook(
            denied_task_keywords={"forbidden"},
            denied_arg_keywords={"secret"},
            max_risk_level="medium",
        )
    ],
)

allowed = runtime.run("allowed task", tool_name="Echo", tool_args={"message": "hello"})
blocked = runtime.run("forbidden task", tool_name="Echo", tool_args={"message": "hello"})

print(allowed.status.value, allowed.tool_results["Echo"].ok)
print(blocked.status.value, blocked.errors)
