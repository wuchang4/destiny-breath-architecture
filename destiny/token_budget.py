"""Token budget helpers for runtime context compaction.

The framework intentionally keeps this dependency-free. Estimates are coarse,
but they are stable enough to prevent accidental prompt/context blowups before
integrations add provider-specific tokenizers.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from .providers import MemoryRecord


TRUNCATION_MARKER = "\n...[truncated by token budget]"


@dataclass(frozen=True)
class TokenBudgetPolicy:
    """Runtime token budget policy.

    `chars_per_token` is a rough estimator. English text is often around four
    characters per token; CJK text can be denser, but this still gives a useful
    safety rail without adding tokenizer dependencies.
    """

    enabled: bool = True
    chars_per_token: int = 4
    max_context_tokens: int = 8192
    max_task_tokens: int = 2048
    max_model_prompt_tokens: int = 8192
    max_model_response_tokens: int = 4096
    max_tool_result_tokens: int = 4096
    max_memory_record_tokens: int = 1024

    def validate(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("token_budget_enabled must be a boolean")
        numeric_fields = {
            "chars_per_token": self.chars_per_token,
            "max_context_tokens": self.max_context_tokens,
            "max_task_tokens": self.max_task_tokens,
            "max_model_prompt_tokens": self.max_model_prompt_tokens,
            "max_model_response_tokens": self.max_model_response_tokens,
            "max_tool_result_tokens": self.max_tool_result_tokens,
            "max_memory_record_tokens": self.max_memory_record_tokens,
        }
        for name, value in numeric_fields.items():
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_tokens(value: Any, *, chars_per_token: int = 4) -> int:
    """Return a deterministic rough token estimate for arbitrary values."""
    if chars_per_token <= 0:
        raise ValueError("chars_per_token must be positive")
    if value is None:
        return 0
    if isinstance(value, bool):
        return 1
    if isinstance(value, (int, float)):
        return max(1, math.ceil(len(str(value)) / chars_per_token))
    if isinstance(value, str):
        return math.ceil(len(value) / chars_per_token)
    if isinstance(value, bytes):
        return math.ceil(len(value) / chars_per_token)
    if is_dataclass(value):
        return estimate_tokens(asdict(value), chars_per_token=chars_per_token)
    if isinstance(value, dict):
        total = 0
        for key, item in value.items():
            total += estimate_tokens(str(key), chars_per_token=chars_per_token)
            total += estimate_tokens(item, chars_per_token=chars_per_token)
        return total
    if isinstance(value, (list, tuple, set)):
        return sum(estimate_tokens(item, chars_per_token=chars_per_token) for item in value)
    return math.ceil(len(repr(value)) / chars_per_token)


def truncate_text(
    text: str,
    max_tokens: int,
    *,
    chars_per_token: int = 4,
    marker: str = TRUNCATION_MARKER,
) -> tuple[str, bool]:
    """Truncate text to a rough token budget and return `(text, truncated)`."""
    if max_tokens <= 0:
        return "", bool(text)
    max_chars = max_tokens * chars_per_token
    if len(text) <= max_chars:
        return text, False
    if max_chars <= len(marker):
        return text[:max_chars], True
    return text[: max_chars - len(marker)] + marker, True


def compact_value(
    value: Any,
    max_tokens: int,
    *,
    chars_per_token: int = 4,
    max_depth: int = 8,
) -> tuple[Any, dict[str, Any]]:
    """Recursively compact a value to a total rough token budget.

    The return metadata is safe to place in audit logs or tool metadata.
    """
    before = estimate_tokens(value, chars_per_token=chars_per_token)
    state = _BudgetState(
        remaining=max_tokens,
        chars_per_token=chars_per_token,
        truncated=False,
        omitted_items=0,
    )
    compacted = _compact(value, state, depth=0, max_depth=max_depth)
    after = estimate_tokens(compacted, chars_per_token=chars_per_token)
    report = {
        "estimated_tokens_before": before,
        "estimated_tokens_after": after,
        "budget_tokens": max_tokens,
        "truncated": state.truncated or before > max_tokens,
        "omitted_items": state.omitted_items,
    }
    return compacted, report


class BudgetedModelProvider:
    """Model provider wrapper that compacts prompts and context."""

    def __init__(self, provider: Any, policy: TokenBudgetPolicy):
        self.provider = provider
        self.policy = policy
        self.name = getattr(provider, "name", "model")

    def complete(self, prompt: str, context: dict[str, Any] | None = None) -> str:
        if not self.policy.enabled:
            return self.provider.complete(prompt, context)
        compact_prompt, prompt_report = compact_value(
            prompt,
            self.policy.max_model_prompt_tokens,
            chars_per_token=self.policy.chars_per_token,
        )
        model_context = _model_safe_context(context or {}, self.name)
        compact_context, context_report = compact_value(
            model_context,
            self.policy.max_context_tokens,
            chars_per_token=self.policy.chars_per_token,
        )
        if isinstance(compact_context, dict):
            compact_context = dict(compact_context)
            compact_context["token_budget_report"] = {
                "prompt": prompt_report,
                "context": context_report,
            }
        response = self.provider.complete(str(compact_prompt), compact_context)
        compact_response, _ = truncate_text(
            response,
            self.policy.max_model_response_tokens,
            chars_per_token=self.policy.chars_per_token,
        )
        return compact_response


class BudgetedMemoryProvider:
    """Memory provider wrapper that compacts retrieved records."""

    def __init__(self, provider: Any, policy: TokenBudgetPolicy):
        self.provider = provider
        self.policy = policy
        self.name = getattr(provider, "name", "memory")

    def put(self, key: str, content: str, metadata: dict[str, Any] | None = None) -> MemoryRecord:
        return self.provider.put(key, content, metadata)

    def search(self, query: str, top_k: int = 5) -> list[MemoryRecord]:
        records = self.provider.search(query, top_k=top_k)
        if not self.policy.enabled:
            return records
        return [compact_memory_record(record, self.policy) for record in records]

    def __getattr__(self, name: str) -> Any:
        return getattr(self.provider, name)


def compact_memory_record(record: MemoryRecord, policy: TokenBudgetPolicy) -> MemoryRecord:
    content, report = compact_value(
        record.content,
        policy.max_memory_record_tokens,
        chars_per_token=policy.chars_per_token,
    )
    if not report["truncated"]:
        return record
    metadata = dict(record.metadata)
    metadata["token_budget"] = report
    return MemoryRecord(
        key=record.key,
        content=str(content),
        metadata=metadata,
        created_at=record.created_at,
    )


def _model_safe_context(context: dict[str, Any], model_name: str) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in context.items():
        if key == "model":
            safe["model_name"] = model_name
        elif key == "memory":
            safe["memory_name"] = getattr(value, "name", "memory")
        else:
            safe[key] = value
    return safe


@dataclass
class _BudgetState:
    remaining: int
    chars_per_token: int
    truncated: bool
    omitted_items: int


def _compact(value: Any, state: _BudgetState, *, depth: int, max_depth: int) -> Any:
    if state.remaining <= 0:
        state.truncated = True
        state.omitted_items += 1
        return _omitted(value, chars_per_token=state.chars_per_token)
    if depth > max_depth:
        state.truncated = True
        state.omitted_items += 1
        return _omitted(value, chars_per_token=state.chars_per_token)
    if isinstance(value, str):
        needed = estimate_tokens(value, chars_per_token=state.chars_per_token)
        if needed <= state.remaining:
            state.remaining -= needed
            return value
        compacted, truncated = truncate_text(
            value,
            state.remaining,
            chars_per_token=state.chars_per_token,
        )
        state.remaining = 0
        state.truncated = state.truncated or truncated
        return compacted
    if is_dataclass(value):
        return _compact(asdict(value), state, depth=depth + 1, max_depth=max_depth)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        items = list(value.items())
        for index, (key, item) in enumerate(items):
            if state.remaining <= 0:
                result["_token_budget_truncated"] = True
                result["_omitted_keys"] = len(items) - index
                state.truncated = True
                state.omitted_items += len(items) - index
                break
            key_text = str(key)
            key_tokens = estimate_tokens(key_text, chars_per_token=state.chars_per_token)
            if key_tokens <= state.remaining:
                state.remaining -= key_tokens
                result[key_text] = _compact(item, state, depth=depth + 1, max_depth=max_depth)
            else:
                result["_token_budget_truncated"] = True
                result["_omitted_keys"] = len(items) - index
                state.truncated = True
                state.omitted_items += len(items) - index
                break
        return result
    if isinstance(value, (list, tuple, set)):
        result: list[Any] = []
        items = list(value)
        for index, item in enumerate(items):
            if state.remaining <= 0:
                result.append({
                    "_token_budget_truncated": True,
                    "omitted_items": len(items) - index,
                })
                state.truncated = True
                state.omitted_items += len(items) - index
                break
            result.append(_compact(item, state, depth=depth + 1, max_depth=max_depth))
        return result
    needed = estimate_tokens(value, chars_per_token=state.chars_per_token)
    if needed <= state.remaining:
        state.remaining -= needed
        return value
    state.remaining = 0
    state.truncated = True
    return _omitted(value, chars_per_token=state.chars_per_token)


def _omitted(value: Any, *, chars_per_token: int) -> dict[str, Any]:
    return {
        "_token_budget_truncated": True,
        "type": type(value).__name__,
        "estimated_tokens": estimate_tokens(value, chars_per_token=chars_per_token),
    }
