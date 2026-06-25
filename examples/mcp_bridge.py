"""Expose Destiny Runtime tools through an MCP-style JSON-RPC bridge."""

from __future__ import annotations

import json
import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from destiny import FunctionTool, McpToolBridge, Runtime, RuntimeConfig  # noqa: E402


def summarize(args, context):
    return {
        "summary": f"Destiny MCP bridge handled: {args['text']}",
        "nodes": context["node_history"],
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        runtime = Runtime.from_config(
            RuntimeConfig(workspace_root=tmpdir, state_dir=os.path.join(tmpdir, ".destiny")),
            tools=[
                FunctionTool(
                    name="Summarize",
                    required=("text",),
                    handler=summarize,
                    description="Summarize one text payload.",
                    output_schema={
                        "type": "object",
                        "required": ["summary", "nodes"],
                        "properties": {
                            "summary": {"type": "string"},
                            "nodes": {"type": "array"},
                        },
                    },
                    metadata={
                        "read_only": True,
                        "destructive": False,
                        "idempotent": True,
                        "open_world": False,
                    },
                )
            ],
        )
        bridge = McpToolBridge(runtime)
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "Summarize",
                    "arguments": {"text": "agent runtime integration"},
                },
            },
        ]
        for request in requests:
            response = bridge.handle(request)
            print(json.dumps(response, ensure_ascii=False, sort_keys=True))
        runtime.close()


if __name__ == "__main__":
    main()
