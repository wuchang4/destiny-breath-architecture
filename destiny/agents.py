"""Agent enhancement layer.

This module turns Destiny from a standalone runtime into a wrapper that can
enhance an existing agent with planning, guarded tool execution, persistence,
audit logging, and reflection callbacks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .runtime import Runtime
from .types import RunResult


@dataclass(frozen=True)
class AgentPlan:
    """A structured action plan returned by an AgentAdapter."""

    task: str
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    risk_level: str | None = None
    rationale: str = ""


@dataclass(frozen=True)
class AgentOutcome:
    """Final output returned by an enhanced agent run."""

    answer: Any
    plan: AgentPlan
    run: RunResult
    reflection: Any = None


class AgentAdapter(Protocol):
    """Contract implemented by agents that want Destiny enhancement."""

    name: str

    def plan(self, task: str, context: dict[str, Any]) -> AgentPlan:
        """Return a structured plan for the task."""

    def reflect(self, plan: AgentPlan, run: RunResult, context: dict[str, Any]) -> Any:
        """Inspect the run result and return final agent output or reflection."""


class EnhancedAgent:
    """Wrap an AgentAdapter with Runtime guarantees."""

    def __init__(self, agent: AgentAdapter, runtime: Runtime):
        if not getattr(agent, "name", ""):
            raise ValueError("agent name cannot be empty")
        self.agent = agent
        self.runtime = runtime

    def run(self, task: str, context: dict[str, Any] | None = None, run_id: str | None = None) -> AgentOutcome:
        context = self.runtime.agent_context(context, agent_name=self.agent.name)
        self.runtime._run_hooks("before_plan", context, task)
        plan = self.agent.plan(task, context)
        if not isinstance(plan, AgentPlan):
            raise TypeError("agent.plan() must return AgentPlan")
        self.runtime._run_hooks("after_plan", context, plan)

        runtime_result = self.runtime.run(
            task=plan.task,
            tool_name=plan.tool_name,
            tool_args=plan.tool_args,
            risk_level=plan.risk_level,
            run_id=run_id,
        )
        self.runtime._run_hooks("before_reflect", context, plan, runtime_result)
        reflection = self.agent.reflect(plan, runtime_result, context)
        outcome = AgentOutcome(
            answer=reflection,
            plan=plan,
            run=runtime_result,
            reflection=reflection,
        )
        self.runtime._run_hooks("after_reflect", context, outcome)
        return outcome
