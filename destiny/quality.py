"""Deterministic quality evaluation for agent outcomes."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .agents import AgentOutcome
from .types import RunStatus


@dataclass(frozen=True)
class QualityCriterionResult:
    """One rubric criterion score."""

    name: str
    score: float
    weight: float
    passed: bool
    reason: str


@dataclass(frozen=True)
class QualityAssessment:
    """Aggregate quality assessment."""

    score: float
    passed: bool
    min_score: float
    criteria: list[QualityCriterionResult]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QualityRubric:
    """Deterministic rubric for judging an agent output."""

    min_score: float = 0.8
    min_answer_chars: int = 1
    required_terms: tuple[str, ...] = ()
    forbidden_terms: tuple[str, ...] = ()
    required_artifact_keys: tuple[str, ...] = ()
    require_success_status: bool = True
    require_tool_success: bool = True
    allow_errors: bool = False
    weights: dict[str, float] = field(default_factory=lambda: {
        "status": 0.20,
        "tool_success": 0.20,
        "answer_presence": 0.20,
        "required_terms": 0.20,
        "safety": 0.10,
        "artifacts": 0.10,
    })

    def validate(self) -> None:
        if not 0 <= self.min_score <= 1:
            raise ValueError("min_score must be between 0 and 1")
        if self.min_answer_chars < 0:
            raise ValueError("min_answer_chars cannot be negative")
        for name, weight in self.weights.items():
            if weight < 0:
                raise ValueError(f"weight for {name} cannot be negative")


class QualityEvaluator:
    """Score agent outcomes without calling an external model."""

    def __init__(self, rubric: QualityRubric | None = None):
        self.rubric = rubric or QualityRubric()
        self.rubric.validate()

    def evaluate(
        self,
        *,
        task: str,
        outcome: AgentOutcome | None = None,
        answer: Any = None,
    ) -> QualityAssessment:
        if outcome is not None:
            answer = outcome.answer
        answer_text = _stringify(answer)
        criteria = [
            self._status_score(outcome),
            self._tool_score(outcome),
            self._answer_presence_score(answer_text),
            self._required_terms_score(task, answer_text),
            self._safety_score(outcome, answer_text),
            self._artifact_score(answer),
        ]
        score = _weighted_score(criteria)
        passed = score >= self.rubric.min_score and all(
            criterion.passed for criterion in criteria if criterion.weight > 0 and criterion.score == 0
        )
        failed = [criterion.name for criterion in criteria if not criterion.passed]
        summary = (
            f"quality={score:.2f}; passed={passed}; "
            f"failed={','.join(failed) if failed else 'none'}"
        )
        return QualityAssessment(
            score=score,
            passed=passed,
            min_score=self.rubric.min_score,
            criteria=criteria,
            summary=summary,
        )

    def judge(self, *, min_score: float | None = None) -> Callable[[AgentOutcome, Any], bool]:
        threshold = self.rubric.min_score if min_score is None else min_score

        def _judge(outcome: AgentOutcome, case: Any) -> bool:
            task = getattr(case, "task", "") or ""
            assessment = self.evaluate(task=task, outcome=outcome)
            return assessment.score >= threshold and assessment.passed

        return _judge

    def _status_score(self, outcome: AgentOutcome | None) -> QualityCriterionResult:
        weight = self.rubric.weights.get("status", 0.0)
        if outcome is None or not self.rubric.require_success_status:
            return _criterion("status", 1.0, weight, "status not required")
        passed = outcome.run.status == RunStatus.SUCCEEDED and outcome.run.success
        return _criterion(
            "status",
            1.0 if passed else 0.0,
            weight,
            f"run status is {outcome.run.status.value}",
        )

    def _tool_score(self, outcome: AgentOutcome | None) -> QualityCriterionResult:
        weight = self.rubric.weights.get("tool_success", 0.0)
        if outcome is None or not self.rubric.require_tool_success:
            return _criterion("tool_success", 1.0, weight, "tool success not required")
        results = list(outcome.run.tool_results.values())
        if not results:
            return _criterion("tool_success", 1.0, weight, "no tool result required")
        ok_count = sum(1 for result in results if getattr(result, "ok", False))
        score = ok_count / len(results)
        return _criterion(
            "tool_success",
            score,
            weight,
            f"{ok_count}/{len(results)} tool results succeeded",
        )

    def _answer_presence_score(self, answer_text: str) -> QualityCriterionResult:
        weight = self.rubric.weights.get("answer_presence", 0.0)
        if self.rubric.min_answer_chars == 0:
            return _criterion("answer_presence", 1.0, weight, "answer length not required")
        length = len(answer_text.strip())
        score = min(1.0, length / self.rubric.min_answer_chars) if self.rubric.min_answer_chars else 1.0
        return _criterion(
            "answer_presence",
            score,
            weight,
            f"answer has {length} chars; required {self.rubric.min_answer_chars}",
        )

    def _required_terms_score(self, task: str, answer_text: str) -> QualityCriterionResult:
        weight = self.rubric.weights.get("required_terms", 0.0)
        terms = tuple(self.rubric.required_terms)
        if not terms:
            terms = _salient_terms(task)
        if not terms:
            return _criterion("required_terms", 1.0, weight, "no required terms")
        lower_answer = answer_text.lower()
        hits = [term for term in terms if term.lower() in lower_answer]
        score = len(hits) / len(terms)
        return _criterion(
            "required_terms",
            score,
            weight,
            f"matched {len(hits)}/{len(terms)} required terms",
        )

    def _safety_score(self, outcome: AgentOutcome | None, answer_text: str) -> QualityCriterionResult:
        weight = self.rubric.weights.get("safety", 0.0)
        lower_answer = answer_text.lower()
        forbidden_hits = [
            term for term in self.rubric.forbidden_terms
            if term.lower() in lower_answer
        ]
        errors = list(outcome.run.errors) if outcome is not None else []
        has_disallowed_errors = bool(errors) and not self.rubric.allow_errors
        passed = not forbidden_hits and not has_disallowed_errors
        reason_parts = []
        if forbidden_hits:
            reason_parts.append(f"forbidden terms: {', '.join(forbidden_hits)}")
        if has_disallowed_errors:
            reason_parts.append(f"errors: {len(errors)}")
        reason = "; ".join(reason_parts) if reason_parts else "no forbidden terms or disallowed errors"
        return _criterion("safety", 1.0 if passed else 0.0, weight, reason)

    def _artifact_score(self, answer: Any) -> QualityCriterionResult:
        weight = self.rubric.weights.get("artifacts", 0.0)
        keys = self.rubric.required_artifact_keys
        if not keys:
            return _criterion("artifacts", 1.0, weight, "no artifacts required")
        answer_mapping = answer if isinstance(answer, Mapping) else {}
        hits = 0
        missing: list[str] = []
        for key in keys:
            value = answer_mapping.get(key)
            if isinstance(value, str) and value:
                path = Path(value)
                if path.exists() or not os.path.isabs(value):
                    hits += 1
                else:
                    missing.append(key)
            else:
                missing.append(key)
        score = hits / len(keys)
        return _criterion(
            "artifacts",
            score,
            weight,
            f"matched {hits}/{len(keys)} artifact keys" + (f"; missing {', '.join(missing)}" if missing else ""),
        )


def _criterion(name: str, score: float, weight: float, reason: str) -> QualityCriterionResult:
    score = max(0.0, min(1.0, score))
    return QualityCriterionResult(
        name=name,
        score=score,
        weight=weight,
        passed=score > 0,
        reason=reason,
    )


def quality_gate(
    rubric: QualityRubric | None = None,
    *,
    min_score: float | None = None,
) -> Callable[[AgentOutcome, Any], bool]:
    """Return an EvalCase-compatible quality judge."""
    return QualityEvaluator(rubric).judge(min_score=min_score)


def _weighted_score(criteria: list[QualityCriterionResult]) -> float:
    total_weight = sum(criterion.weight for criterion in criteria)
    if total_weight <= 0:
        return 1.0
    return sum(criterion.score * criterion.weight for criterion in criteria) / total_weight


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if is_dataclass(value):
        return _stringify(asdict(value))
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _salient_terms(task: str) -> tuple[str, ...]:
    words = []
    for raw in task.lower().replace("_", " ").split():
        word = "".join(ch for ch in raw if ch.isalnum() or ch in "-")
        if len(word) >= 4 and word not in {"this", "that", "with", "from", "into", "through"}:
            words.append(word)
    return tuple(dict.fromkeys(words[:5]))
