"""Run a Destiny Runtime as an MCP-style stdio tool server."""

from __future__ import annotations

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from destiny import McpStdioTransport, McpToolBridge, Runtime, RuntimeConfig, standard_tools


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Destiny tools over MCP-style stdio JSON-RPC.")
    parser.add_argument("--workspace", default=".", help="Workspace root for Runtime tools.")
    parser.add_argument("--state-dir", default=None, help="Runtime state directory.")
    parser.add_argument(
        "--permission",
        default="workspace-write",
        choices=sorted(RuntimeConfig.VALID_PERMISSION_MODES),
        help="Runtime permission mode.",
    )
    parser.add_argument(
        "--memory-backend",
        default="file",
        choices=sorted(RuntimeConfig.VALID_MEMORY_BACKENDS),
        help="Runtime memory backend.",
    )
    parser.add_argument("--server-name", default="destiny-runtime", help="MCP server name.")
    parser.add_argument("--enable-shell", action="store_true", help="Expose the Bash tool.")
    parser.add_argument("--enable-http", action="store_true", help="Expose the WebFetch tool.")
    parser.add_argument(
        "--allow-outside-workspace",
        action="store_true",
        help="Allow file tools to access paths outside the workspace.",
    )
    parser.add_argument(
        "--allow-private-hosts",
        action="store_true",
        help="Allow WebFetch to access private/local hosts.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = Runtime.from_config(
        RuntimeConfig(
            workspace_root=args.workspace,
            state_dir=args.state_dir,
            permission_mode=args.permission,
            memory_backend=args.memory_backend,
        ),
        tools=standard_tools(
            shell=args.enable_shell,
            http=args.enable_http,
            allow_outside_workspace=args.allow_outside_workspace,
            allow_private_hosts=args.allow_private_hosts,
        ),
    )
    try:
        bridge = McpToolBridge(runtime, server_name=args.server_name)
        McpStdioTransport(bridge).serve()
    finally:
        runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
