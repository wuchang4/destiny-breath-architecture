"""Tool adapter contracts for production-style runtime integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class ToolResult:
    """Normalized output from a tool adapter."""

    ok: bool
    data: Any = None
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolAdapter(Protocol):
    """Contract implemented by runtime tools."""

    name: str
    schema: dict[str, Any]
    description: str

    def validate(self, args: dict[str, Any]) -> None:
        """Raise ValueError when args are invalid."""

    def execute(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        """Execute the tool and return a normalized result."""


@dataclass
class RegisteredTool:
    """Simple concrete adapter for tools with a callable implementation."""

    name: str
    handler: Callable[[dict[str, Any], dict[str, Any]], Any]
    schema: dict[str, Any] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    description: str = ""
    output_schema: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self, args: dict[str, Any]) -> None:
        missing = [key for key in self.required if key not in args]
        if missing:
            raise ValueError(f"missing required tool args for {self.name}: {', '.join(missing)}")

    def execute(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        try:
            self.validate(args)
            data = self.handler(args, context)
            return ToolResult(ok=True, data=data)
        except Exception as exc:
            return ToolResult(ok=False, error=str(exc), metadata={"type": type(exc).__name__})


class FunctionTool(RegisteredTool):
    """Alias with a clearer name for user-created function-backed tools."""


def tool_spec(tool: ToolAdapter) -> dict[str, Any]:
    """Return a normalized public specification for one tool adapter."""
    schema = dict(getattr(tool, "schema", {}) or {})
    required = list(getattr(tool, "required", ()) or ())
    if not schema:
        schema = {
            "type": "object",
            "properties": {key: {"type": "string"} for key in required},
            "required": required,
        }
    elif required and "required" not in schema:
        schema["required"] = required
    spec = {
        "name": tool.name,
        "description": getattr(tool, "description", "") or "",
        "schema": schema,
    }
    output_schema = dict(getattr(tool, "output_schema", {}) or {})
    metadata = dict(getattr(tool, "metadata", {}) or {})
    if output_schema:
        spec["output_schema"] = output_schema
    if metadata:
        spec["metadata"] = metadata
    return spec


def tool_manifest(tools: list[ToolAdapter], *, format: str = "destiny") -> list[dict[str, Any]]:
    """Return a stable manifest for a list of tools.

    The default `destiny` format is framework-native. The `function` format is a
    generic model-tool-calling shape with name, description, and parameters.
    """
    specs = [tool_spec(tool) for tool in sorted(tools, key=lambda item: item.name)]
    if format == "destiny":
        return specs
    if format == "function":
        return [
            {
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": spec["description"],
                    "parameters": spec["schema"],
                },
            }
            for spec in specs
        ]
    raise ValueError("format must be one of: destiny, function")
