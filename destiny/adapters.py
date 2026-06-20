"""Standard tool adapters for the public runtime."""

from __future__ import annotations

import ipaddress
import socket
import subprocess
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .tools import ToolResult


def _workspace_root(context: dict[str, Any]) -> Path:
    return Path(context.get("workspace_root") or ".").expanduser().resolve()


def _resolve_workspace_path(
    raw_path: str,
    context: dict[str, Any],
    *,
    allow_outside_workspace: bool = False,
) -> Path:
    root = _workspace_root(context)
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    if allow_outside_workspace:
        return resolved
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes workspace: {raw_path}") from exc
    return resolved


@dataclass
class FileReadTool:
    """Read a UTF-8 text file inside the runtime workspace."""

    name: str = "Read"
    description: str = "Read a UTF-8 text file from inside the runtime workspace."
    max_chars: int = 20000
    allow_outside_workspace: bool = False
    schema: dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {"type": "string"},
            "encoding": {"type": "string", "default": "utf-8"},
            "max_chars": {"type": "integer"},
        },
    })

    def validate(self, args: dict[str, Any]) -> None:
        path = args.get("path") or args.get("file_path")
        if not isinstance(path, str) or not path:
            raise ValueError("Read requires a non-empty path")
        max_chars = args.get("max_chars", self.max_chars)
        if not isinstance(max_chars, int) or max_chars <= 0:
            raise ValueError("max_chars must be a positive integer")

    def execute(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        try:
            self.validate(args)
            raw_path = args.get("path") or args.get("file_path")
            path = _resolve_workspace_path(
                raw_path,
                context,
                allow_outside_workspace=self.allow_outside_workspace,
            )
            if not path.is_file():
                raise FileNotFoundError(str(path))
            encoding = args.get("encoding", "utf-8")
            max_chars = min(args.get("max_chars", self.max_chars), self.max_chars)
            content = path.read_text(encoding=encoding, errors="replace")
            truncated = len(content) > max_chars
            if truncated:
                content = content[:max_chars]
            return ToolResult(
                ok=True,
                data={
                    "path": str(path),
                    "content": content,
                    "truncated": truncated,
                },
                metadata={"chars": len(content)},
            )
        except Exception as exc:
            return ToolResult(ok=False, error=str(exc), metadata={"type": type(exc).__name__})


@dataclass
class FileWriteTool:
    """Write a UTF-8 text file inside the runtime workspace."""

    name: str = "WriteFile"
    description: str = "Write a UTF-8 text file inside the runtime workspace."
    allow_outside_workspace: bool = False
    schema: dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "required": ["path", "content"],
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "encoding": {"type": "string", "default": "utf-8"},
            "overwrite": {"type": "boolean", "default": True},
            "create_parents": {"type": "boolean", "default": True},
        },
    })

    def validate(self, args: dict[str, Any]) -> None:
        path = args.get("path") or args.get("file_path")
        if not isinstance(path, str) or not path:
            raise ValueError("WriteFile requires a non-empty path")
        if not isinstance(args.get("content"), str):
            raise ValueError("WriteFile requires string content")

    def execute(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        try:
            self.validate(args)
            raw_path = args.get("path") or args.get("file_path")
            path = _resolve_workspace_path(
                raw_path,
                context,
                allow_outside_workspace=self.allow_outside_workspace,
            )
            overwrite = bool(args.get("overwrite", True))
            create_parents = bool(args.get("create_parents", True))
            if path.exists() and not overwrite:
                raise FileExistsError(str(path))
            if create_parents:
                path.parent.mkdir(parents=True, exist_ok=True)
            encoding = args.get("encoding", "utf-8")
            path.write_text(args["content"], encoding=encoding)
            return ToolResult(
                ok=True,
                data={"path": str(path), "bytes": path.stat().st_size},
                metadata={"created": True},
            )
        except Exception as exc:
            return ToolResult(ok=False, error=str(exc), metadata={"type": type(exc).__name__})


@dataclass
class ShellCommandTool:
    """Execute a shell command from the runtime workspace."""

    name: str = "Bash"
    description: str = "Execute a shell command from the runtime workspace."
    timeout: int = 30
    max_output_chars: int = 20000
    schema: dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "required": ["command"],
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "integer"},
        },
    })

    def validate(self, args: dict[str, Any]) -> None:
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("Bash requires a non-empty command")
        timeout = args.get("timeout", self.timeout)
        if not isinstance(timeout, int) or timeout <= 0:
            raise ValueError("timeout must be a positive integer")

    def execute(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        try:
            self.validate(args)
            timeout = min(args.get("timeout", self.timeout), self.timeout)
            completed = subprocess.run(
                args["command"],
                cwd=str(_workspace_root(context)),
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            stdout, stdout_truncated = self._truncate(completed.stdout)
            stderr, stderr_truncated = self._truncate(completed.stderr)
            return ToolResult(
                ok=completed.returncode == 0,
                data={
                    "returncode": completed.returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                    "truncated": stdout_truncated or stderr_truncated,
                },
            )
        except subprocess.TimeoutExpired as exc:
            return ToolResult(
                ok=False,
                error=f"command timed out after {exc.timeout}s",
                metadata={"type": type(exc).__name__},
            )
        except Exception as exc:
            return ToolResult(ok=False, error=str(exc), metadata={"type": type(exc).__name__})

    def _truncate(self, text: str) -> tuple[str, bool]:
        if len(text) <= self.max_output_chars:
            return text, False
        return text[:self.max_output_chars], True


@dataclass
class HttpGetTool:
    """Fetch HTTP(S) text content with SSRF-oriented defaults."""

    name: str = "WebFetch"
    description: str = "Fetch HTTP(S) text content with private-host blocking by default."
    timeout: int = 10
    max_bytes: int = 1_000_000
    allow_private_hosts: bool = False
    user_agent: str = "destiny-runtime/0.4"
    schema: dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {"type": "string"},
            "headers": {"type": "object"},
            "timeout": {"type": "integer"},
            "max_bytes": {"type": "integer"},
        },
    })

    def validate(self, args: dict[str, Any]) -> None:
        url = args.get("url")
        if not isinstance(url, str) or not url:
            raise ValueError("WebFetch requires a non-empty url")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("WebFetch only supports http(s) URLs")
        timeout = args.get("timeout", self.timeout)
        if not isinstance(timeout, int) or timeout <= 0:
            raise ValueError("timeout must be a positive integer")
        max_bytes = args.get("max_bytes", self.max_bytes)
        if not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")

    def execute(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        try:
            self.validate(args)
            parsed = urlparse(args["url"])
            if not self.allow_private_hosts:
                self._reject_private_host(parsed.hostname or "")
            timeout = min(args.get("timeout", self.timeout), self.timeout)
            max_bytes = min(args.get("max_bytes", self.max_bytes), self.max_bytes)
            headers = {"User-Agent": self.user_agent}
            headers.update(args.get("headers") or {})
            request = urllib.request.Request(args["url"], headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read(max_bytes + 1)
                truncated = len(raw) > max_bytes
                if truncated:
                    raw = raw[:max_bytes]
                encoding = response.headers.get_content_charset() or "utf-8"
                text = raw.decode(encoding, errors="replace")
                return ToolResult(
                    ok=True,
                    data={
                        "url": response.geturl(),
                        "status": response.status,
                        "content": text,
                        "truncated": truncated,
                    },
                    metadata={"headers": dict(response.headers.items())},
                )
        except Exception as exc:
            return ToolResult(ok=False, error=str(exc), metadata={"type": type(exc).__name__})

    def _reject_private_host(self, hostname: str) -> None:
        if hostname.lower() in {"localhost", "localhost.localdomain"}:
            raise ValueError("private or local host is not allowed")
        try:
            addresses = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise ValueError(f"cannot resolve host: {hostname}") from exc
        for family, _, _, _, sockaddr in addresses:
            if family not in (socket.AF_INET, socket.AF_INET6):
                continue
            ip = ipaddress.ip_address(sockaddr[0])
            if not ip.is_global:
                raise ValueError("private or local host is not allowed")


def standard_tools(
    *,
    file_io: bool = True,
    shell: bool = False,
    http: bool = False,
    allow_outside_workspace: bool = False,
    allow_private_hosts: bool = False,
) -> list[Any]:
    """Return a conservative bundle of built-in tool adapters.

    File IO is enabled by default because it is still constrained to the
    workspace. Shell and HTTP adapters are opt-in.
    """
    tools: list[Any] = []
    if file_io:
        tools.extend([
            FileReadTool(allow_outside_workspace=allow_outside_workspace),
            FileWriteTool(allow_outside_workspace=allow_outside_workspace),
        ])
    if shell:
        tools.append(ShellCommandTool())
    if http:
        tools.append(HttpGetTool(allow_private_hosts=allow_private_hosts))
    return tools
