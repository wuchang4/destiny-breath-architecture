# Destiny Breath Architecture

Agent enhancement framework with deterministic graph execution, safety checks, model routing, caching, memory blocks, tracing, checkpointing, and an embeddable wrapper for existing agents.

This repository is an engineering baseline for improving agents, not a single agent persona. The framework wraps an existing agent and adds structure, guarded tool execution, persistence, audit logs, and reflection hooks.

## What Works

| Area | Status | Notes |
| --- | --- | --- |
| State graph | Working | `ProvinceGraph` v3 supports sequential flow, parallel `门下省‖尚书省`, reducer-based state merge, interrupt/resume, and checkpoints. |
| Tool safety chain | Working | Permission mode checks, path traversal checks, dangerous command detection, confirmation flags, and output limits. |
| Model router | Working prototype | Alias resolution, task-type routing, availability checks, fallback chains, and circuit-breaker integration. |
| Config merger | Working | Default, project, memory preference, session, and runtime layers with deep merge. |
| Tool result cache | Working | TTL/LRU JSON cache for repeated tool calls. |
| Execution tracer | Working | Span tracing, JSON export, OTEL-shaped export, metrics, and structured logs. |
| Memory blocks | Prototype | Core/archival blocks with file persistence and keyword search. |
| Public runtime API | Working | `destiny.Runtime`, `FunctionTool`, typed `RunResult`, JSONL audit log, file-backed run store, and tool manifest export. |
| Standard tool adapters | Working | Built-in file read/write, shell command, and HTTP GET adapters with workspace and SSRF-oriented safeguards plus `standard_tools()` toolkit factory. |
| Agent enhancement API | Working | `AgentAdapter`, `AgentPlan`, and `EnhancedAgent` wrap existing agents with Runtime guarantees. |
| Evaluation API | Working | `Benchmark` and `EvalCase` run deterministic scenarios against enhanced agents. |
| Enhancement hooks | Working | Lifecycle hooks observe or extend plan/run/tool/reflect stages. |
| Provider API | Working | `ModelProvider`, `MemoryProvider`, and `EmbeddingProvider` protocols decouple model/memory backends from Runtime; `Runtime` supports file, JSON vector, and SQLite vector memory backends. |
| CLI | Working | `destiny-engine` console entry point plus script-compatible `python scripts/destiny_engine.py`. |

## Install

```bash
python -m pip install -e ".[dev]"
```

The runtime itself currently uses only Python standard library modules. The `dev` extra installs `pytest` for CI-style test runs.

## Quick Start

Run the deterministic test suite:

```bash
python tests/test_all.py
```

Or, after installing the dev extra:

```bash
python -m pytest
```

Run the execution engine:

```bash
destiny-engine --task "搜索 AI 最新动态" --tool WebSearch --arg "query=AI news" --json
```

Use a project-local runtime state directory:

```bash
destiny-engine --task "搜索 AI 最新动态" --tool WebSearch --arg "query=AI news" --state-dir .destiny --json
```

Override the tool permission mode from the CLI:

```bash
destiny-engine --task "inspect project" --tool Read --arg "path=README.md" --permission read-only --json
```

PowerShell users should prefer `--arg KEY=VALUE` over inline JSON. JSON is still supported:

```bash
destiny-engine --task "搜索 AI 最新动态" --tool WebSearch --args "{\"query\":\"AI news\"}" --json
```

Embed the runtime in Python:

```python
from destiny import FunctionTool, Runtime, RuntimeConfig


def echo(args, context):
    return {"message": args["message"], "path": context["node_history"]}


runtime = Runtime.from_config(
    RuntimeConfig(workspace_root=".", state_dir=".destiny"),
    tools=[FunctionTool(name="Echo", required=("message",), handler=echo)],
)

result = runtime.run(
    task="echo a message",
    tool_name="Echo",
    tool_args={"message": "hello"},
)

print(result.status.value)
print(result.tool_results["Echo"].data)
```

Use built-in standard tools:

```python
from destiny import Runtime, standard_tools

runtime = Runtime.from_config(
    "destiny.toml",
    tools=standard_tools(),
)

runtime.run(
    "write a note",
    tool_name="WriteFile",
    tool_args={"path": "notes/hello.txt", "content": "hello"},
)
```

`standard_tools()` enables workspace file IO by default. Shell and HTTP adapters are opt-in: `standard_tools(shell=True, http=True)`.

Export registered tool metadata for an external agent:

```python
manifest = runtime.tool_manifest()
function_manifest = runtime.tool_manifest(format="function")
```

Enhance an existing agent:

```python
from destiny import AgentPlan, FunctionTool, Runtime


class MyAgent:
    name = "my-agent"

    def plan(self, task, context):
        return AgentPlan(
            task=task,
            tool_name="Echo",
            tool_args={"message": task},
        )

    def reflect(self, plan, run, context):
        return run.tool_results[plan.tool_name].data


runtime = Runtime.from_config(
    "destiny.toml",
    tools=[FunctionTool(name="Echo", required=("message",), handler=echo)],
)

enhanced_agent = runtime.enhance(MyAgent())
outcome = enhanced_agent.run("improve this task")
print(outcome.answer)
```

Evaluate an enhanced agent:

```python
from destiny import Benchmark, EvalCase, RunStatus

benchmark = Benchmark([
    EvalCase(name="happy-path", task="hello", expect_tool="Echo"),
    EvalCase(
        name="danger-blocked",
        task="delete root",
        context={"tool": "Bash", "tool_args": {"command": "rm -rf /"}},
        expect_status=RunStatus.INTERRUPTED,
    ),
])

report = benchmark.run(enhanced_agent)
print(report.summary())
```

Attach lifecycle hooks:

```python
from destiny import PolicyHook, RecordingHook, Runtime

hook = RecordingHook()
policy = PolicyHook(
    denied_task_keywords={"forbidden"},
    denied_tools={"DangerousTool"},
    max_risk_level="medium",
)

runtime = Runtime.from_config("destiny.toml", tools=[...], hooks=[policy, hook])
runtime.run("observe this", tool_name="Echo", tool_args={"message": "hi"})
print(hook.events)
```

Attach model and memory providers. By default, `Runtime` uses a project-local file memory store at `.destiny/memory/memory.json`; pass another provider when you want a custom backend.

```python
from destiny import FileMemoryProvider, Runtime, StaticModelProvider

runtime = Runtime.from_config(
    "destiny.toml",
    tools=[...],
    model_provider=StaticModelProvider("deterministic response"),
    memory_provider=FileMemoryProvider(".destiny/memory/custom-memory.json"),
)
```

Enable a built-in vector memory backend:

```python
from destiny import Runtime, RuntimeConfig

runtime = Runtime.from_config(
    RuntimeConfig(
        workspace_root=".",
        state_dir=".destiny",
        memory_backend="sqlite-vector",
    )
)

runtime.memory_provider.put("architecture", "Agent memory should preserve traces and checkpoints.")
hits = runtime.memory_provider.search("checkpoint trace memory", top_k=1)
print(hits[0].key)
```

Or load runtime settings from `destiny.toml`:

```toml
[runtime]
workspace_root = "."
state_dir = ".destiny"
permission_mode = "workspace-write"
audit_log = true
persist_runs = true
default_risk_level = "low"
memory_backend = "file"  # "file", "vector", or "sqlite-vector"
```

```python
runtime = Runtime.from_config("destiny.toml", tools=[...])
```

## Runtime Flow

```text
START
  -> 中书省
  -> 门下省‖尚书省    # v3 parallel verification + planning path
  -> 执行节点
  -> AAR/Checkpt
  -> END
```

Low-confidence tasks route to `澄清分支`. High-risk tasks route to `阻断/预警` and require explicit resume with confirmation.

## Project Layout

| Path | Purpose |
| --- | --- |
| `scripts/province_graph.py` | State graph runtime and checkpointing. |
| `scripts/destiny_engine.py` | End-to-end runtime orchestration and CLI. |
| `destiny/runtime.py` | Public embeddable runtime facade. |
| `destiny/agents.py` | Agent enhancement contracts and wrapper. |
| `destiny/evals.py` | Benchmark and deterministic evaluation helpers. |
| `destiny/hooks.py` | Pluggable enhancement hook lifecycle. |
| `destiny/providers.py` | Model and memory provider protocols plus deterministic baseline providers. |
| `destiny/adapters.py` | Built-in file, shell, and HTTP tool adapters. |
| `destiny/tools.py` | Tool adapter contracts and function-backed tool helpers. |
| `destiny/stores.py` | JSONL audit log and file-backed run store. |
| `scripts/tool_safety_chain.py` | Tool execution safety checks. |
| `scripts/model_router.py` | Model aliasing, selection, fallback, and availability checks. |
| `scripts/config_merger.py` | Layered configuration merge. |
| `scripts/tool_result_cache.py` | TTL/LRU tool result cache. |
| `scripts/execution_tracer.py` | Tracing, metrics, and export helpers. |
| `scripts/memory_blocks.py` | Core and archival memory block prototype. |
| `tests/test_all.py` | Deterministic smoke and integration coverage. |
| `.github/workflows/ci.yml` | Windows/Linux Python matrix CI. |

## Industrial Baseline Criteria

This repository now targets these baseline standards:

- Installable Python package via `pyproject.toml`.
- Console script entry point: `destiny-engine`.
- Embeddable Python API via `destiny.Runtime`.
- Existing agents can be wrapped through `runtime.enhance(agent)`.
- Built-in standard tool adapters cover workspace file IO, guarded shell execution, and HTTP GET with private-host blocking by default.
- Runtime can expose registered tool names and serializable tool manifests for external agent integration.
- Enhanced agents can be evaluated with deterministic `Benchmark` cases.
- Runtime and enhanced-agent lifecycles can be extended with hooks.
- `PolicyHook` can block denied tasks, tools, arguments, or risk levels with standard `RunResult`/`ToolResult` outputs.
- Model and memory backends are exposed through provider protocols and runtime context.
- Runtime defaults to `FileMemoryProvider` for durable project-local agent memory.
- `VectorMemoryProvider` adds file-backed vector retrieval through a pluggable `EmbeddingProvider`.
- `SqliteVectorMemoryProvider` provides a dependency-free SQLite vector memory backend for longer-running local agents.
- Cross-platform CI matrix for Windows and Linux.
- Deterministic test suite covering graph, safety, routing, config, cache, tracing, circuit breaker, memory blocks, and integration flow.
- Versioned graph serialization (`version = 3`).
- High-risk graph state cannot bypass interrupt through the v3 parallel path.
- Model availability failures return `False` and can trigger fallback.
- CLI supports shell-safe `--arg KEY=VALUE` parameters.
- CLI and `RuntimeConfig` permission modes are propagated into the graph safety layer.
- Runtime runs produce JSONL audit events and optional normalized run result files.
- `DestinyEngine` and `Runtime` can write traces, checkpoints, cache files, audit logs, and run results under a configurable state directory.
- `RuntimeConfig` can be loaded from `destiny.toml` with validation for unknown keys and enum values.

## Known Limits

- This is still a prototype runtime. The public `Runtime` can execute registered adapters, but the legacy `DestinyEngine` still only records delegated execution.
- Built-in adapters cover file IO, shell commands, and HTTP GET; bridges for OpenAI/Codex/LangChain/AutoGen/MCP-style runtimes are not shipped yet.
- `memory_blocks.py` and `FileMemoryProvider` are keyword-based. Vector memory backends provide retrieval over embeddings, but production semantic quality depends on plugging in a real embedding backend.
- Some auxiliary legacy scripts still use user-local defaults such as `~/.clawdbot`, but `DestinyEngine` and the public `Runtime` now support configurable `.destiny` state storage for traces, checkpoints, cache, audit, and run artifacts.
- There is no external evaluator for agent output quality yet.
- The project does not currently ship the claimed large skill library; local skill indexing depends on the operator's machine.

## Development

```bash
python -m compileall scripts tests
python tests/test_all.py
python -m pytest
```

Before calling the project production-ready, the next milestones should be:

1. Split the monolithic `tests/test_all.py` into focused pytest modules.
2. Add bridges for OpenAI/Codex/LangChain/AutoGen/MCP-style agent runtimes.
3. Add first-class OpenAI/local embedding provider adapters and external vector database backends such as pgvector or Qdrant.
4. Add an independent evaluator for agent output quality.
5. Add stronger graph checkpoint migrations and thread-aware tracing.
