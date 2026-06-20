"""Stable runtime data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RunStatus(str, Enum):
    """Terminal status for a runtime invocation."""

    SUCCEEDED = "succeeded"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


@dataclass(frozen=True)
class RunResult:
    """Normalized result returned by the public Runtime API."""

    status: RunStatus
    success: bool
    interrupted: bool
    current_node: str
    node_history: list[str]
    state: dict[str, Any]
    trace_path: str | None = None
    trace_summary: str = ""
    tool_results: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @classmethod
    def from_engine_result(
        cls,
        result: dict[str, Any],
        tool_results: dict[str, Any] | None = None,
    ) -> "RunResult":
        """Convert the legacy engine dictionary into the public result type."""
        errors = list(result.get("state", {}).get("errors", []))
        if result.get("interrupted"):
            status = RunStatus.INTERRUPTED
        elif result.get("success"):
            status = RunStatus.SUCCEEDED
        else:
            status = RunStatus.FAILED
        return cls(
            status=status,
            success=bool(result.get("success")),
            interrupted=bool(result.get("interrupted")),
            current_node=result.get("current_node", ""),
            node_history=list(result.get("node_history", [])),
            state=dict(result.get("state", {})),
            trace_path=result.get("trace_path"),
            trace_summary=result.get("trace_summary", ""),
            tool_results=tool_results or {},
            errors=errors,
        )
