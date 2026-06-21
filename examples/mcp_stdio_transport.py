"""Run the MCP-style stdio transport with in-memory streams."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from destiny import FunctionTool, McpStdioTransport, McpToolBridge, Runtime, RuntimeConfig  # noqa: E402


def echo(args, context):
    return {"echo": args["message"]}


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        runtime = Runtime.from_config(
            RuntimeConfig(workspace_root=tmpdir, state_dir=os.path.join(tmpdir, ".destiny")),
            tools=[FunctionTool(name="Echo", required=("message",), handler=echo)],
        )
        input_stream = io.StringIO(
            "\n".join([
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
                json.dumps({
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "Echo", "arguments": {"message": "hello stdio"}},
                }),
                "",
            ])
        )
        output_stream = io.StringIO()
        transport = McpStdioTransport(
            McpToolBridge(runtime),
            input_stream=input_stream,
            output_stream=output_stream,
        )
        transport.serve()
        print(output_stream.getvalue().strip())
        runtime.close()


if __name__ == "__main__":
    main()
