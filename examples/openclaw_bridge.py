"""Bridge an OpenClaw-style chat payload through Destiny Runtime."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from destiny import FunctionTool, OpenClawBridge, Runtime, RuntimeConfig  # noqa: E402


def draft_reply(args, context):
    memory = context["memory"]
    record = memory.put(
        f"openclaw:{args['session_id']}",
        f"Handled OpenClaw message from {args['sender']}: {args['message']}",
        {"channel": args["channel"]},
    )
    return {
        "reply": f"Destiny handled {args['channel']} message: {args['message']}",
        "memory_key": record.key,
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        runtime = Runtime.from_config(
            RuntimeConfig(
                workspace_root=tmpdir,
                state_dir=str(Path(tmpdir) / ".destiny"),
                memory_backend="sqlite-vector",
                max_tool_result_tokens=512,
            ),
            tools=[
                FunctionTool(
                    name="DraftReply",
                    required=("message", "channel", "session_id", "sender"),
                    handler=draft_reply,
                    description="Draft a reply for an OpenClaw chat payload.",
                )
            ],
        )
        try:
            bridge = OpenClawBridge(runtime, default_tool="DraftReply")
            response = bridge.handle(
                {
                    "message": "Summarize the agent upgrade status.",
                    "channel": "openclaw",
                    "session_id": "demo-session",
                    "sender": "operator",
                },
                run_id="openclaw-demo",
            )
            print(json.dumps(response.to_dict(), ensure_ascii=False, indent=2))
        finally:
            runtime.close()


if __name__ == "__main__":
    main()
