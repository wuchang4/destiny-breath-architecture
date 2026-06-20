"""Use hooks to observe runtime lifecycle events."""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from destiny import FunctionTool, RecordingHook, Runtime


def echo_tool(args, context):
    return {"message": args["message"]}


hook = RecordingHook()
runtime = Runtime.from_config(
    os.path.join(os.path.dirname(__file__), "destiny.toml"),
    tools=[FunctionTool(name="Echo", required=("message",), handler=echo_tool)],
    hooks=[hook],
)

runtime.run("observe this", tool_name="Echo", tool_args={"message": "observe this"})

for event, payload in hook.events:
    print(event, payload)
