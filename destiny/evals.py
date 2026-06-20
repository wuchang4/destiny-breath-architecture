"""Evaluation helpers for enhanced agents."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .agents import AgentOutcome, EnhancedAgent
from .types import RunStatus

Judge = Callable[[AgentOutcome, "EvalCase"], bool]


@dataclass(frozen=True)
class EvalCase:
    """One deterministic evaluation scenario."""

    name: str
    task: str
    context: dict[str, Any] = field(default_factory=dict)
    expect_status: RunStatus | None = RunStatus.SUCCEEDED
    expect_tool: str | None = None
    judge: Judge | None = None


@dataclass(frozen=True)
class EvalCaseResult:
    """Result for one evaluation case."""

    case_name: str
    passed: bool
    status: RunStatus
    tool_name: str
    tool_ok: bool | None
    errors: list[str]
    duration_ms: float


@dataclass(frozen=True)
class EvalReport:
    """Aggregate benchmark report."""

    total: int
    passed: int
    failed: int
    success_rate: float
    interrupted: int
    tool_success_rate: float
    error_count: int
    duration_ms: float
    cases: list[EvalCaseResult]

    def summary(self) -> str:
        return (
            f"{self.passed}/{self.total} passed "
            f"({self.success_rate:.1%}); "
            f"tool_success={self.tool_success_rate:.1%}; "
            f"interrupted={self.interrupted}; errors={self.error_count}; "
            f"duration={self.duration_ms:.1f}ms"
        )


class Benchmark:
    """Run deterministic eval cases against an EnhancedAgent."""

    def __init__(self, cases: Iterable[EvalCase]):
        self.cases = list(cases)

    def run(self, agent: EnhancedAgent) -> EvalReport:
        start = time.time()
        results: list[EvalCaseResult] = []
        for index, case in enumerate(self.cases):
            case_start = time.time()
            try:
                outcome = agent.run(case.task, context=case.context, run_id=f"eval-{index}-{case.name}")
                result = self._score_case(case, outcome, (time.time() - case_start) * 1000)
            except Exception as exc:
                result = EvalCaseResult(
                    case_name=case.name,
                    passed=False,
                    status=RunStatus.FAILED,
                    tool_name="",
                    tool_ok=None,
                    errors=[f"{type(exc).__name__}: {exc}"],
                    duration_ms=(time.time() - case_start) * 1000,
                )
            results.append(result)

        passed = sum(1 for r in results if r.passed)
        interrupted = sum(1 for r in results if r.status == RunStatus.INTERRUPTED)
        tool_results = [r for r in results if r.tool_ok is not None]
        tool_passed = sum(1 for r in tool_results if r.tool_ok)
        tool_success_rate = tool_passed / len(tool_results) if tool_results else 1.0
        error_count = sum(len(r.errors) for r in results)
        total = len(results)
        return EvalReport(
            total=total,
            passed=passed,
            failed=total - passed,
            success_rate=passed / total if total else 0.0,
            interrupted=interrupted,
            tool_success_rate=tool_success_rate,
            error_count=error_count,
            duration_ms=(time.time() - start) * 1000,
            cases=results,
        )

    @staticmethod
    def _score_case(case: EvalCase, outcome: AgentOutcome, duration_ms: float) -> EvalCaseResult:
        plan = outcome.plan
        tool_result = outcome.run.tool_results.get(plan.tool_name) if plan.tool_name else None
        checks = []
        if case.expect_status is not None:
            checks.append(outcome.run.status == case.expect_status)
        if case.expect_tool is not None:
            checks.append(plan.tool_name == case.expect_tool)
        if tool_result is not None:
            checks.append(tool_result.ok)
        if case.judge:
            checks.append(bool(case.judge(outcome, case)))
        passed = all(checks) if checks else outcome.run.status == RunStatus.SUCCEEDED
        errors = list(outcome.run.errors)
        if tool_result is not None and not tool_result.ok:
            errors.append(tool_result.error)
        return EvalCaseResult(
            case_name=case.name,
            passed=passed,
            status=outcome.run.status,
            tool_name=plan.tool_name,
            tool_ok=tool_result.ok if tool_result is not None else None,
            errors=errors,
            duration_ms=duration_ms,
        )
