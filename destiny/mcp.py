"""MCP-style tool bridge for Destiny Runtime.

This is a dependency-free bridge for the core tool subset of the Model Context
Protocol: `initialize`, `ping`, `tools/list`, and `tools/call`. It is designed
for embedders that want MCP-shaped JSON-RPC messages without running a full MCP
transport server inside this package.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Mapping

from .version import __version__


JSONRPC_VERSION = "2.0"
DEFAULT_MCP_PROTOCOL_VERSION = "2025-06-18"


@dataclass(frozen=True)
class McpToolBridge:
    """Expose Runtime tools through an MCP-style JSON-RPC interface."""

    runtime: Any
    server_name: str = "destiny-runtime"
    protocol_version: str = DEFAULT_MCP_PROTOCOL_VERSION
    cache_ttl_ms: int = 300_000

    def handle(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        """Handle one JSON-RPC request or notification.

        Notifications do not have an `id` and therefore return `None`.
        """
        request_id = message.get("id")
        method = message.get("method")
        if message.get("jsonrpc") != JSONRPC_VERSION or not isinstance(method, str):
            return self._error(request_id, -32600, "Invalid Request")
        if request_id is None:
            return None
        try:
            if method == "initialize":
                return self._result(request_id, self.initialize())
            if method == "ping":
                return self._result(request_id, {})
            if method == "tools/list":
                return self._result(request_id, self.list_tools())
            if method == "tools/call":
                params = message.get("params") or {}
                if not isinstance(params, Mapping):
                    return self._error(request_id, -32602, "Invalid params")
                name = params.get("name")
                arguments = params.get("arguments") or {}
                if not isinstance(name, str) or not name:
                    return self._error(request_id, -32602, "tools/call requires params.name")
                if not isinstance(arguments, dict):
                    return self._error(request_id, -32602, "tools/call params.arguments must be an object")
                if self.runtime.get_tool(name) is None:
                    return self._error(request_id, -32602, f"tool not found: {name}")
                return self._result(request_id, self.call_tool(name, arguments))
            return self._error(request_id, -32601, f"Method not found: {method}")
        except Exception as exc:
            return self._error(request_id, -32603, f"Internal error: {exc}")

    def initialize(self) -> dict[str, Any]:
        return {
            "protocolVersion": self.protocol_version,
            "serverInfo": {
                "name": self.server_name,
                "version": __version__,
            },
            "capabilities": {
                "tools": {
                    "listChanged": False,
                },
            },
        }

    def list_tools(self) -> dict[str, Any]:
        tools = []
        for spec in self.runtime.tool_manifest(format="destiny"):
            tools.append({
                "name": spec["name"],
                "title": spec["name"],
                "description": spec.get("description", ""),
                "inputSchema": spec.get("schema") or {"type": "object"},
            })
        return {
            "tools": tools,
            "ttlMs": self.cache_ttl_ms,
            "cacheScope": "public",
        }

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        arguments = dict(arguments or {})
        run = self.runtime.run(
            task=f"MCP tools/call {name}",
            tool_name=name,
            tool_args=arguments,
            run_id=run_id or f"mcp-{name}-{int(time.time() * 1000)}",
        )
        tool_result = run.tool_results.get(name)
        if tool_result is None:
            return _tool_error(f"tool did not return a result: {name}", {"run_status": run.status.value})
        if not tool_result.ok:
            return _tool_error(
                tool_result.error or "tool failed",
                {
                    "run_status": run.status.value,
                    "errors": list(run.errors),
                    "tool_metadata": dict(tool_result.metadata),
                },
            )
        structured = _structured_content(tool_result.data)
        return {
            "content": [{
                "type": "text",
                "text": _content_text(tool_result.data),
            }],
            "structuredContent": structured,
            "isError": False,
            "_meta": {
                "run_status": run.status.value,
                "trace_path": run.trace_path,
            },
        }

    def _result(self, request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": result,
        }

    def _error(self, request_id: Any, code: int, message: str) -> dict[str, Any]:
        response: dict[str, Any] = {
            "jsonrpc": JSONRPC_VERSION,
            "error": {
                "code": code,
                "message": message,
            },
        }
        if request_id is not None:
            response["id"] = request_id
        return response


def mcp_tool_manifest(runtime: Any, *, cache_ttl_ms: int = 300_000) -> dict[str, Any]:
    """Return an MCP-shaped tools/list result for a Runtime."""
    return McpToolBridge(runtime, cache_ttl_ms=cache_ttl_ms).list_tools()


def _tool_error(message: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "content": [{
            "type": "text",
            "text": message,
        }],
        "structuredContent": {
            "error": message,
            **(metadata or {}),
        },
        "isError": True,
    }


def _structured_content(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return data
    return {"result": data}


def _content_text(data: Any) -> str:
    if isinstance(data, str):
        return data
    try:
        return json.dumps(data, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(data)
