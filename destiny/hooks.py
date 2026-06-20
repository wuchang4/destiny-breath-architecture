"""Hook system for pluggable agent enhancements."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class HookAbort(RuntimeError):
    """Raised by hooks to block a run or tool execution."""

    def __init__(self, reason: str, policy: str = "hook"):
        super().__init__(reason)
        self.reason = reason
        self.policy = policy


class EnhancementHook:
    """Base class for optional runtime/agent lifecycle hooks."""

    name = "hook"

    def before_run(self, context: dict[str, Any]) -> None:
        """Called before Runtime.run invokes the graph engine."""

    def after_run(self, context: dict[str, Any], result: Any) -> None:
        """Called after Runtime.run has built a RunResult."""

    def before_tool(self, context: dict[str, Any], tool_name: str, args: dict[str, Any]) -> None:
        """Called before a registered tool adapter executes."""

    def after_tool(self, context: dict[str, Any], tool_name: str, tool_result: Any) -> None:
        """Called after a registered tool adapter returns."""

    def before_plan(self, context: dict[str, Any], task: str) -> None:
        """Called before an AgentAdapter creates a plan."""

    def after_plan(self, context: dict[str, Any], plan: Any) -> None:
        """Called after an AgentAdapter returns a plan."""

    def before_reflect(self, context: dict[str, Any], plan: Any, run: Any) -> None:
        """Called before an AgentAdapter reflects on a run."""

    def after_reflect(self, context: dict[str, Any], outcome: Any) -> None:
        """Called after an AgentAdapter reflection creates an outcome."""


@dataclass
class RecordingHook(EnhancementHook):
    """Simple hook that records lifecycle events for tests and debugging."""

    name: str = "recording"
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def _record(self, event: str, payload: dict[str, Any] | None = None) -> None:
        self.events.append((event, dict(payload or {})))

    def before_run(self, context: dict[str, Any]) -> None:
        self._record("before_run", {"task": context.get("task"), "tool": context.get("tool_name")})

    def after_run(self, context: dict[str, Any], result: Any) -> None:
        self._record("after_run", {"status": getattr(result.status, "value", result.status)})

    def before_tool(self, context: dict[str, Any], tool_name: str, args: dict[str, Any]) -> None:
        self._record("before_tool", {"tool": tool_name, "args": dict(args)})

    def after_tool(self, context: dict[str, Any], tool_name: str, tool_result: Any) -> None:
        self._record("after_tool", {"tool": tool_name, "ok": getattr(tool_result, "ok", None)})

    def before_plan(self, context: dict[str, Any], task: str) -> None:
        self._record("before_plan", {"agent": context.get("agent_name"), "task": task})

    def after_plan(self, context: dict[str, Any], plan: Any) -> None:
        self._record("after_plan", {"tool": getattr(plan, "tool_name", "")})

    def before_reflect(self, context: dict[str, Any], plan: Any, run: Any) -> None:
        self._record("before_reflect", {"status": getattr(run.status, "value", run.status)})

    def after_reflect(self, context: dict[str, Any], outcome: Any) -> None:
        self._record("after_reflect", {"has_answer": hasattr(outcome, "answer")})


@dataclass
class PolicyHook(EnhancementHook):
    """Policy hook that can block tasks or tools before execution."""

    name: str = "policy"
    denied_tools: set[str] = field(default_factory=set)
    denied_task_keywords: set[str] = field(default_factory=set)
    denied_arg_keywords: set[str] = field(default_factory=set)
    max_risk_level: str | None = None

    _RISK_ORDER = {"low": 0, "medium": 1, "high": 2}

    def before_run(self, context: dict[str, Any]) -> None:
        task = str(context.get("task", "")).lower()
        for keyword in self.denied_task_keywords:
            if keyword.lower() in task:
                raise HookAbort(f"task keyword denied: {keyword}", policy=self.name)
        if self.max_risk_level:
            risk = str(context.get("risk_level", "low"))
            if self._RISK_ORDER.get(risk, 0) > self._RISK_ORDER.get(self.max_risk_level, 0):
                raise HookAbort(f"risk level denied: {risk}", policy=self.name)

    def before_tool(self, context: dict[str, Any], tool_name: str, args: dict[str, Any]) -> None:
        if tool_name in self.denied_tools:
            raise HookAbort(f"tool denied: {tool_name}", policy=self.name)
        arg_text = str(args).lower()
        for keyword in self.denied_arg_keywords:
            if keyword.lower() in arg_text:
                raise HookAbort(f"tool argument keyword denied: {keyword}", policy=self.name)
