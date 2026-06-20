"""Public runtime facade.

The facade intentionally wraps the legacy scripts layer instead of replacing it
in one jump. That keeps the CLI compatible while giving embedders a stable API.
"""

from __future__ import annotations

import os
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from scripts.destiny_engine import DestinyEngine
from scripts.tool_safety_chain import ToolSafetyChain

from .hooks import EnhancementHook, HookAbort
from .providers import (
    FileMemoryProvider,
    MemoryProvider,
    ModelProvider,
    SqliteVectorMemoryProvider,
    VectorMemoryProvider,
)
from .stores import FileRunStore, JsonlAuditLog
from .tools import ToolAdapter, ToolResult, tool_manifest
from .types import RunResult, RunStatus


@dataclass
class RuntimeConfig:
    """Configuration for the public Runtime facade."""

    workspace_root: str = "."
    state_dir: str | None = None
    permission_mode: str = "workspace-write"
    audit_log: bool = True
    persist_runs: bool = True
    default_risk_level: str = "low"
    memory_backend: str = "file"

    VALID_PERMISSION_MODES = {"read-only", "workspace-write", "full-access"}
    VALID_RISK_LEVELS = {"low", "medium", "high"}
    VALID_MEMORY_BACKENDS = {"file", "vector", "sqlite-vector"}

    @property
    def resolved_state_dir(self) -> Path:
        if self.state_dir:
            return Path(self.state_dir).expanduser().resolve()
        return Path(self.workspace_root).resolve() / ".destiny"

    @classmethod
    def from_file(cls, path: str | os.PathLike[str]) -> "RuntimeConfig":
        """Load runtime configuration from a TOML file."""
        config_path = Path(path).expanduser()
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
        if "runtime" in data:
            raw_runtime = data["runtime"]
            if not isinstance(raw_runtime, dict):
                raise ValueError("[runtime] must be a table")
            data = raw_runtime
        config = cls.from_mapping(data)
        if not config.state_dir:
            config.state_dir = str((config_path.parent / ".destiny").resolve())
        return config

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "RuntimeConfig":
        """Create config from a mapping with validation and unknown-key checks."""
        allowed = {
            "workspace_root",
            "state_dir",
            "permission_mode",
            "audit_log",
            "persist_runs",
            "default_risk_level",
            "memory_backend",
        }
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ValueError(f"unknown runtime config keys: {', '.join(unknown)}")
        config = cls(**dict(data))
        config.validate()
        return config

    def validate(self) -> None:
        if self.permission_mode not in self.VALID_PERMISSION_MODES:
            raise ValueError(
                "permission_mode must be one of: "
                + ", ".join(sorted(self.VALID_PERMISSION_MODES))
            )
        if self.default_risk_level not in self.VALID_RISK_LEVELS:
            raise ValueError(
                "default_risk_level must be one of: "
                + ", ".join(sorted(self.VALID_RISK_LEVELS))
            )
        if not isinstance(self.audit_log, bool):
            raise ValueError("audit_log must be a boolean")
        if not isinstance(self.persist_runs, bool):
            raise ValueError("persist_runs must be a boolean")
        if self.memory_backend not in self.VALID_MEMORY_BACKENDS:
            raise ValueError(
                "memory_backend must be one of: "
                + ", ".join(sorted(self.VALID_MEMORY_BACKENDS))
            )


class Runtime:
    """Embeddable runtime entry point for applications."""

    def __init__(
        self,
        config: RuntimeConfig | None = None,
        tools: Iterable[ToolAdapter] | None = None,
        hooks: Iterable[EnhancementHook] | None = None,
        model_provider: ModelProvider | None = None,
        memory_provider: MemoryProvider | None = None,
    ):
        self.config = config or RuntimeConfig()
        self.config.validate()
        self.state_dir = self.config.resolved_state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._tools: dict[str, ToolAdapter] = {}
        for tool in tools or []:
            self.register_tool(tool)
        self.hooks = list(hooks or [])
        self.model_provider = model_provider
        self.memory_provider = memory_provider or self._default_memory_provider()
        self.audit = JsonlAuditLog(self.state_dir / "audit.jsonl") if self.config.audit_log else None
        self.run_store = FileRunStore(self.state_dir / "runs") if self.config.persist_runs else None

    @classmethod
    def from_config(
        cls,
        config: RuntimeConfig | Mapping[str, Any] | str | os.PathLike[str] | None = None,
        tools: Iterable[ToolAdapter] | None = None,
        hooks: Iterable[EnhancementHook] | None = None,
        model_provider: ModelProvider | None = None,
        memory_provider: MemoryProvider | None = None,
    ) -> "Runtime":
        if config is None:
            runtime_config = RuntimeConfig()
        elif isinstance(config, RuntimeConfig):
            runtime_config = config
        elif isinstance(config, (str, os.PathLike)):
            runtime_config = RuntimeConfig.from_file(config)
        else:
            runtime_config = RuntimeConfig.from_mapping(config)
        return cls(
            runtime_config,
            tools=tools,
            hooks=hooks,
            model_provider=model_provider,
            memory_provider=memory_provider,
        )

    def register_tool(self, tool: ToolAdapter) -> None:
        if not tool.name:
            raise ValueError("tool name cannot be empty")
        self._tools[tool.name] = tool

    def list_tools(self) -> list[str]:
        """Return registered tool names in stable order."""
        return sorted(self._tools)

    def get_tool(self, name: str) -> ToolAdapter | None:
        """Return one registered tool adapter by name."""
        return self._tools.get(name)

    def tool_manifest(self, *, format: str = "destiny") -> list[dict[str, Any]]:
        """Return a serializable manifest for registered tools."""
        return tool_manifest(list(self._tools.values()), format=format)

    def register_hook(self, hook: EnhancementHook) -> None:
        self.hooks.append(hook)

    def close(self) -> None:
        """Release provider resources held by this Runtime."""
        close = getattr(self.memory_provider, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> "Runtime":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def _default_memory_provider(self) -> MemoryProvider:
        if self.config.memory_backend == "sqlite-vector":
            return SqliteVectorMemoryProvider(self.state_dir / "memory" / "vector-memory.sqlite")
        if self.config.memory_backend == "vector":
            return VectorMemoryProvider(self.state_dir / "memory" / "vector-memory.json")
        return FileMemoryProvider(self.state_dir / "memory" / "memory.json")

    def enhance(self, agent: Any):
        """Wrap an AgentAdapter with this Runtime."""
        from .agents import EnhancedAgent

        return EnhancedAgent(agent, self)

    def run(
        self,
        task: str,
        tool_name: str = "",
        tool_args: dict[str, Any] | None = None,
        risk_level: str | None = None,
        run_id: str | None = None,
    ) -> RunResult:
        """Run a task through graph orchestration and optional tool execution."""
        run_id = run_id or f"run_{int(time.time() * 1000)}"
        tool_args = tool_args or {}
        risk = risk_level or self.config.default_risk_level
        hook_context = {
            "run_id": run_id,
            "task": task,
            "tool_name": tool_name,
            "tool_args": tool_args,
            "risk_level": risk,
            "model": self.model_provider,
            "memory": self.memory_provider,
        }
        try:
            self._run_hooks("before_run", hook_context)
        except HookAbort as exc:
            result = self._blocked_result(run_id, task, tool_name, tool_args, risk, exc)
            self._audit("run_blocked", {"run_id": run_id, "reason": exc.reason, "policy": exc.policy})
            if self.run_store:
                self.run_store.save(run_id, result)
            self._run_hooks("after_run", hook_context, result)
            return result
        self._audit("run_started", {"run_id": run_id, "task": task, "tool": tool_name})

        engine = DestinyEngine(
            workspace_root=self.config.workspace_root,
            state_dir=str(self.state_dir),
            runtime_args={"default_permission_mode": self.config.permission_mode},
        )
        engine_result = engine.run(
            task=task,
            risk_level=risk,
            tool_name=tool_name,
            tool_args=tool_args,
        )

        tool_results: dict[str, Any] = {}
        if tool_name:
            if engine_result.get("success"):
                tool_results[tool_name] = self._execute_registered_tool(tool_name, tool_args, engine_result)
            elif tool_name in self._tools:
                errors = engine_result.get("state", {}).get("errors", [])
                reason = "; ".join(str(error) for error in errors) or engine_result.get("interrupt_reason") or "orchestration blocked"
                tool_results[tool_name] = ToolResult(
                    ok=False,
                    error=reason,
                    metadata={"stage": "orchestration"},
                )

        result = RunResult.from_engine_result(engine_result, tool_results=tool_results)
        if self.run_store:
            self.run_store.save(run_id, result)
        self._audit("run_finished", {"run_id": run_id, "result": result})
        self._run_hooks("after_run", hook_context, result)
        return result

    def _execute_registered_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        engine_result: dict[str, Any],
    ) -> ToolResult:
        tool = self._tools.get(tool_name)
        if not tool:
            return ToolResult(
                ok=False,
                error=f"tool '{tool_name}' is not registered; execution was only orchestrated",
            )

        safety = ToolSafetyChain(
            permission_mode=self.config.permission_mode,
            workspace_root=self.config.workspace_root,
        ).validate(tool_name, args)
        if not safety.passed or safety.needs_user_confirm:
            return ToolResult(ok=False, error=safety.block_reason or safety.verdict.value)

        context = {
            "workspace_root": os.path.abspath(self.config.workspace_root),
            "state": engine_result.get("state", {}),
            "node_history": engine_result.get("node_history", []),
            "model": self.model_provider,
            "memory": self.memory_provider,
        }
        try:
            self._run_hooks("before_tool", context, tool_name, args)
        except HookAbort as exc:
            result = ToolResult(
                ok=False,
                error=f"policy blocked: {exc.reason}",
                metadata={"policy": exc.policy},
            )
            self._run_hooks("after_tool", context, tool_name, result)
            return result
        result = tool.execute(args, context)
        self._run_hooks("after_tool", context, tool_name, result)
        return result

    def _audit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.audit:
            self.audit.write(event_type, payload)

    def _run_hooks(self, method_name: str, *args: Any) -> None:
        for hook in self.hooks:
            getattr(hook, method_name)(*args)

    @staticmethod
    def _blocked_result(
        run_id: str,
        task: str,
        tool_name: str,
        tool_args: dict[str, Any],
        risk: str,
        exc: HookAbort,
    ) -> RunResult:
        return RunResult(
            status=RunStatus.FAILED,
            success=False,
            interrupted=False,
            current_node="POLICY_BLOCKED",
            node_history=["POLICY_BLOCKED"],
            state={
                "run_id": run_id,
                "user_intent": task,
                "selected_tools": [tool_name] if tool_name else [],
                "tool_args": tool_args,
                "risk_level": risk,
                "errors": [f"policy blocked: {exc.reason}"],
            },
            errors=[f"policy blocked: {exc.reason}"],
        )
