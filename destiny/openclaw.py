"""OpenClaw-style bridge for Destiny Runtime.

The bridge keeps Destiny in its intended role: a production control plane that
wraps an existing agent or chat gateway payload instead of replacing it.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from .agents import AgentPlan
from .types import RunStatus


@dataclass(frozen=True)
class OpenClawRequest:
    """A small transport-neutral request envelope for OpenClaw-style agents."""

    message: str
    channel: str = "local"
    session_id: str = "default"
    sender: str = "user"
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    risk_level: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "OpenClawRequest":
        message = payload.get("message") or payload.get("text") or payload.get("task")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("OpenClawRequest requires a non-empty message/text/task")
        tool_args = payload.get("tool_args") or payload.get("args") or {}
        if not isinstance(tool_args, dict):
            raise ValueError("tool_args must be an object")
        metadata = payload.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        risk_level = payload.get("risk_level")
        if risk_level is not None and not isinstance(risk_level, str):
            raise ValueError("risk_level must be a string when provided")
        return cls(
            message=message,
            channel=str(payload.get("channel") or "local"),
            session_id=str(payload.get("session_id") or payload.get("conversation_id") or "default"),
            sender=str(payload.get("sender") or payload.get("user") or "user"),
            tool_name=str(payload.get("tool_name") or payload.get("tool") or ""),
            tool_args=dict(tool_args),
            risk_level=risk_level,
            metadata=dict(metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OpenClawResponse:
    """Response envelope suitable for returning to an OpenClaw chat channel."""

    ok: bool
    message: str
    session_id: str
    channel: str
    run_status: str
    tool_name: str = ""
    data: Any = None
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OpenClawBridge:
    """Route OpenClaw-style payloads through a Destiny Runtime."""

    def __init__(
        self,
        runtime: Any,
        *,
        default_tool: str = "",
        default_tool_args: Mapping[str, Any] | None = None,
        agent_name: str = "openclaw-destiny-bridge",
        include_envelope_args: bool = True,
    ):
        self.runtime = runtime
        self.default_tool = default_tool
        self.default_tool_args = dict(default_tool_args or {})
        self.agent_name = agent_name
        self.include_envelope_args = include_envelope_args

    def handle(
        self,
        payload: OpenClawRequest | Mapping[str, Any],
        *,
        run_id: str | None = None,
    ) -> OpenClawResponse:
        request = payload if isinstance(payload, OpenClawRequest) else OpenClawRequest.from_mapping(payload)
        agent = self.runtime.enhance(_OpenClawBridgeAgent(self))
        outcome = agent.run(
            request.message,
            context={"openclaw": request.to_dict()},
            run_id=run_id or self._run_id(request),
        )
        if isinstance(outcome.answer, OpenClawResponse):
            return outcome.answer
        return OpenClawResponse(
            ok=outcome.run.status == RunStatus.SUCCEEDED,
            message=str(outcome.answer),
            session_id=request.session_id,
            channel=request.channel,
            run_status=outcome.run.status.value,
            tool_name=outcome.plan.tool_name,
            data=outcome.answer,
            errors=list(outcome.run.errors),
        )

    def skill_manifest(self, *, name: str = "destiny-runtime") -> dict[str, Any]:
        return openclaw_skill_manifest(
            name=name,
            default_tool=self.default_tool,
            agent_name=self.agent_name,
        )

    def _tool_args(self, request: OpenClawRequest) -> dict[str, Any]:
        tool_args = dict(self.default_tool_args)
        if self.include_envelope_args:
            tool_args.update({
                "message": request.message,
                "channel": request.channel,
                "session_id": request.session_id,
                "sender": request.sender,
            })
        tool_args.update(request.tool_args)
        return tool_args

    @staticmethod
    def _run_id(request: OpenClawRequest) -> str:
        safe_session = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in request.session_id)
        return f"openclaw-{safe_session}-{int(time.time() * 1000)}"


class _OpenClawBridgeAgent:
    def __init__(self, bridge: OpenClawBridge):
        self.bridge = bridge
        self.name = bridge.agent_name

    def plan(self, task: str, context: dict[str, Any]) -> AgentPlan:
        request = OpenClawRequest.from_mapping(context.get("openclaw") or {"message": task})
        tool_name = request.tool_name or self.bridge.default_tool
        return AgentPlan(
            task=request.message,
            tool_name=tool_name,
            tool_args=self.bridge._tool_args(request) if tool_name else {},
            risk_level=request.risk_level,
            rationale="Route OpenClaw payload through Destiny Runtime controls.",
        )

    def reflect(self, plan: AgentPlan, run: Any, context: dict[str, Any]) -> OpenClawResponse:
        request = OpenClawRequest.from_mapping(context.get("openclaw") or {"message": plan.task})
        tool_result = run.tool_results.get(plan.tool_name) if plan.tool_name else None
        if tool_result is None:
            ok = run.status == RunStatus.SUCCEEDED
            data = {"message": plan.task}
            message = plan.task if ok else "; ".join(run.errors)
            errors = list(run.errors)
        elif tool_result.ok:
            ok = True
            data = tool_result.data
            message = _extract_reply(tool_result.data)
            errors = []
        else:
            ok = False
            data = tool_result.data
            message = tool_result.error
            errors = list(run.errors) + [tool_result.error]
        return OpenClawResponse(
            ok=ok,
            message=message,
            session_id=request.session_id,
            channel=request.channel,
            run_status=run.status.value,
            tool_name=plan.tool_name,
            data=data,
            errors=[error for error in errors if error],
            metadata={
                "sender": request.sender,
                "agent": self.name,
                "trace_path": run.trace_path,
                "interrupted": run.interrupted,
            },
        )


def openclaw_skill_manifest(
    *,
    name: str = "destiny-runtime",
    default_tool: str = "",
    agent_name: str = "openclaw-destiny-bridge",
) -> dict[str, Any]:
    """Return a serializable manifest for OpenClaw skill/gateway registration."""
    return {
        "name": name,
        "description": "Route OpenClaw-style chat tasks through Destiny Runtime controls.",
        "agent_name": agent_name,
        "default_tool": default_tool,
        "input_schema": {
            "type": "object",
            "required": ["message"],
            "properties": {
                "message": {"type": "string"},
                "channel": {"type": "string", "default": "local"},
                "session_id": {"type": "string", "default": "default"},
                "sender": {"type": "string", "default": "user"},
                "tool_name": {"type": "string"},
                "tool_args": {"type": "object"},
                "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
                "metadata": {"type": "object"},
            },
        },
        "output_schema": {
            "type": "object",
            "required": ["ok", "message", "session_id", "channel", "run_status"],
            "properties": {
                "ok": {"type": "boolean"},
                "message": {"type": "string"},
                "session_id": {"type": "string"},
                "channel": {"type": "string"},
                "run_status": {"type": "string"},
                "tool_name": {"type": "string"},
                "data": {},
                "errors": {"type": "array", "items": {"type": "string"}},
                "metadata": {"type": "object"},
            },
        },
    }


def _extract_reply(data: Any) -> str:
    if isinstance(data, dict):
        for key in ("reply", "message", "content", "text", "answer"):
            value = data.get(key)
            if isinstance(value, str):
                return value
        return str(data)
    if data is None:
        return ""
    return str(data)
