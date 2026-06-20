# Destiny Breath Architecture

Current framework version: `0.5.0`

Production-oriented framework for enhancing existing AI agents with graph execution,
tool safety, persistent memory, tracing, evaluation, lifecycle hooks, and standard
tool adapters.

This repository is not a single agent persona. It is a runtime layer that wraps an
existing agent and gives it stronger execution structure, safer tool use, durable
state, measurable behavior, and memory backends.

## What Problem It Solves

Most agent prototypes start as prompt logic plus tool calls. They usually become
hard to operate when they need to run for a long time:

- No stable execution graph.
- Tool calls are not consistently validated.
- Runs are hard to audit or replay.
- Memory is either missing, ad hoc, or locked to one backend.
- Agent quality is not measured with deterministic cases.
- External agents cannot discover available tools through a stable manifest.

Destiny Breath Architecture adds a production-style control plane around an
agent without forcing the agent itself to be rewritten.

## Current Capabilities

| Area | Status | Notes |
| --- | --- | --- |
| Public runtime | Working | `destiny.Runtime`, typed `RunResult`, audit log, run store, and tool manifest export. |
| Agent wrapper | Working | Wrap an existing agent with `runtime.enhance(agent)`. |
| State graph | Working | `ProvinceGraph` v3 supports deterministic flow, parallel planning/verification, merge reducers, interrupt/resume, and checkpoints. |
| Tool safety | Working | Permission modes, path traversal checks, dangerous command checks, output limits, and confirmation gates. |
| Standard tools | Working | File read/write, shell command, and HTTP GET adapters with workspace and private-host safeguards. |
| Tool manifest | Working | Runtime can export registered tools in native or generic function-calling format. |
| Memory providers | Working | File keyword memory, JSON vector memory, and SQLite vector memory. |
| Model providers | Working | Provider protocol plus deterministic static provider for tests. |
| Token budget | Working | Dependency-free token estimates, context compaction, memory retrieval limits, model prompt/response limits, and tool result compaction. |
| OpenClaw bridge | Working | `OpenClawBridge` routes chat-style payloads through Destiny Runtime controls. |
| MCP bridge | Working | `McpToolBridge` exposes Runtime tools through MCP-style JSON-RPC `tools/list` and `tools/call`. |
| Hooks | Working | Lifecycle hooks for plan/run/tool/reflect stages, including `PolicyHook`. |
| Evaluation | Working | `Benchmark` and `EvalCase` for deterministic enhanced-agent tests. |
| Quality gate | Working | `QualityEvaluator` and `QualityRubric` score outputs and plug into `EvalCase.judge`. |
| CLI | Working | `destiny-engine` plus script-compatible `python scripts/destiny_engine.py`. |
| Tests | Working | Deterministic smoke/integration suite with 129 covered scenarios. |
| Real case | Working | `examples/complete_agent_task.py` runs a full repository-audit agent task. |

## Install

Requires Python 3.11+.

```bash
python -m pip install -e ".[dev]"
```

The runtime itself uses Python standard library modules. The `dev` extra installs
`pytest` for pytest-style runs when available.

## Quick Start

Run the deterministic test suite:

```bash
python tests/test_all.py
```

Run the complete agent task example:

```bash
python examples/complete_agent_task.py
```

Run a minimal runtime:

```python
from destiny import FunctionTool, Runtime, RuntimeConfig


def echo(args, context):
    return {
        "message": args["message"],
        "node_history": context["node_history"],
    }


runtime = Runtime.from_config(
    RuntimeConfig(workspace_root=".", state_dir=".destiny"),
    tools=[
        FunctionTool(
            name="Echo",
            required=("message",),
            handler=echo,
            description="Echo one message.",
        )
    ],
)

result = runtime.run(
    task="echo a message",
    tool_name="Echo",
    tool_args={"message": "hello"},
)

print(result.status.value)
print(result.tool_results["Echo"].data)
```

## Enhance An Existing Agent

Your agent only needs a `plan()` method that returns an `AgentPlan`, plus an
optional `reflect()` method.

```python
from destiny import AgentPlan, FunctionTool, Runtime


class MyAgent:
    name = "my-agent"

    def plan(self, task, context):
        return AgentPlan(
            task=task,
            tool_name="Echo",
            tool_args={"message": task},
            rationale="Run through guarded runtime.",
        )

    def reflect(self, plan, run, context):
        return run.tool_results[plan.tool_name].data


runtime = Runtime.from_config(
    "examples/destiny.toml",
    tools=[FunctionTool(name="Echo", required=("message",), handler=echo)],
)

enhanced_agent = runtime.enhance(MyAgent())
outcome = enhanced_agent.run("improve this task")
print(outcome.answer)
```

## Complete Real Case

The repository includes a complete deterministic agent task:

```bash
python examples/complete_agent_task.py
```

The example does the following:

1. Creates a temporary repository workspace.
2. Copies this repository's `README.md` into the workspace.
3. Wraps a `RepositoryAuditAgent` with `Runtime`.
4. Runs a `ProjectAudit` tool through Destiny's safety/runtime layer.
5. Writes `reports/agent-readiness.md`.
6. Persists an agent-readiness memory entry with SQLite vector memory.
7. Runs a `Benchmark` case to verify the task completed correctly.

Expected output:

```text
status=succeeded
score=1.00
report_exists=True
memory_hit=agent-readiness-report
1/1 passed (100.0%); tool_success=100.0%; interrupted=0; errors=0
```

## OpenClaw Bridge

Destiny can wrap OpenClaw-style chat payloads without replacing the chat gateway
or agent loop. The bridge maps a message envelope into a guarded Destiny run,
then returns a response envelope for the original channel.

```bash
python examples/openclaw_bridge.py
```

Minimal usage:

```python
from destiny import FunctionTool, OpenClawBridge, Runtime, RuntimeConfig


def draft_reply(args, context):
    return {"reply": f"Destiny handled: {args['message']}"}


runtime = Runtime.from_config(
    RuntimeConfig(workspace_root=".", state_dir=".destiny"),
    tools=[FunctionTool(name="DraftReply", required=("message",), handler=draft_reply)],
)

bridge = OpenClawBridge(runtime, default_tool="DraftReply")
response = bridge.handle({
    "message": "Summarize the agent upgrade status.",
    "channel": "openclaw",
    "session_id": "demo-session",
})

print(response.message)
```

The bridge keeps Destiny as the control layer: tool safety, memory providers,
token budgets, audit logs, run persistence, and hooks still apply.

## Standard Tool Adapters

Use `standard_tools()` for a conservative built-in tool bundle.

```python
from destiny import Runtime, RuntimeConfig, standard_tools

runtime = Runtime.from_config(
    RuntimeConfig(workspace_root=".", state_dir=".destiny"),
    tools=standard_tools(),
)

runtime.run(
    "write a note",
    tool_name="WriteFile",
    tool_args={"path": "notes/hello.txt", "content": "hello"},
)
```

By default, `standard_tools()` enables workspace file IO only. Shell and HTTP are
explicitly opt-in:

```python
tools = standard_tools(shell=True, http=True)
```

Built-in adapters:

| Tool | Purpose | Default safety posture |
| --- | --- | --- |
| `Read` | Read a workspace file. | Blocks paths outside workspace. |
| `WriteFile` | Write a workspace file. | Blocks paths outside workspace; blocked by read-only mode. |
| `Bash` | Run a shell command. | Opt-in; still passes through safety chain. |
| `WebFetch` | Fetch HTTP(S) text. | Opt-in; private/local hosts blocked by default. |

## Tool Manifest

External agents can inspect registered tools before planning.

```python
print(runtime.list_tools())
print(runtime.tool_manifest())
print(runtime.tool_manifest(format="function"))
```

The `function` format is a generic model-tool-calling shape:

```json
{
  "type": "function",
  "function": {
    "name": "Echo",
    "description": "Echo one message.",
    "parameters": {
      "type": "object",
      "required": ["message"],
      "properties": {
        "message": {"type": "string"}
      }
    }
  }
}
```

## MCP Bridge

`McpToolBridge` exposes registered Runtime tools through an MCP-style JSON-RPC
shape for embedders that want `initialize`, `ping`, `tools/list`, and
`tools/call` without running a full MCP transport server in this package.

```bash
python examples/mcp_bridge.py
```

Minimal usage:

```python
from destiny import FunctionTool, McpToolBridge, Runtime, RuntimeConfig


def summarize(args, context):
    return {"summary": f"Destiny handled: {args['text']}"}


runtime = Runtime.from_config(
    RuntimeConfig(workspace_root=".", state_dir=".destiny"),
    tools=[FunctionTool(name="Summarize", required=("text",), handler=summarize)],
)

bridge = McpToolBridge(runtime)
response = bridge.handle({
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {"name": "Summarize", "arguments": {"text": "agent runtime"}},
})
```

The bridge preserves Destiny's runtime guarantees: tool safety, token budgets,
memory providers, hooks, audit logs, and run persistence still apply.

## Memory Backends

Runtime defaults to durable file-backed memory:

```python
runtime.memory_provider.put("preference", "User prefers concise answers.")
hits = runtime.memory_provider.search("concise answer", top_k=1)
```

Supported backends:

| Backend | Config value | Storage | Notes |
| --- | --- | --- | --- |
| File keyword | `file` | `.destiny/memory/memory.json` | Default, simple, deterministic. |
| JSON vector | `vector` | `.destiny/memory/vector-memory.json` | Vector retrieval with pluggable embeddings. |
| SQLite vector | `sqlite-vector` | `.destiny/memory/vector-memory.sqlite` | Better local backend for longer-running agents. |

Use SQLite vector memory:

```python
from destiny import Runtime, RuntimeConfig

with Runtime.from_config(
    RuntimeConfig(
        workspace_root=".",
        state_dir=".destiny",
        memory_backend="sqlite-vector",
    )
) as runtime:
    runtime.memory_provider.put(
        "architecture",
        "Agent memory should preserve traces and checkpoints.",
    )
    hits = runtime.memory_provider.search("checkpoint trace memory", top_k=1)
    print(hits[0].key)
```

The built-in `HashEmbeddingProvider` is dependency-free and deterministic. It is
useful for tests and local scaffolding, not a substitute for high-quality model
embeddings. Production integrations should plug in real embedding providers or
external vector databases behind the same protocol.

## Token Budget Controls

Runtime token budget controls are enabled by default. They prevent common agent
cost explosions without adding tokenizer dependencies:

- Long agent context values are compacted before plan/reflect callbacks.
- Model prompts, model context, and model responses are capped through a
  budgeted provider view.
- Memory search results returned through runtime context are capped per record.
- Tool result payloads are compacted before reflection, run persistence, and
  audit logs.

Configure the rough budgets in `RuntimeConfig`:

```python
runtime = Runtime.from_config(
    RuntimeConfig(
        workspace_root=".",
        max_context_tokens=4096,
        max_model_prompt_tokens=4096,
        max_model_response_tokens=2048,
        max_tool_result_tokens=2048,
        max_memory_record_tokens=512,
    )
)
```

The estimator defaults to `4` characters per token. For stricter local tests,
set `token_chars_per_token=1`. Disable the layer with
`token_budget_enabled=False` when an integration needs raw, unmodified payloads.

## Policy Hooks

Hooks can observe or block runtime events.

```python
from destiny import PolicyHook, Runtime

runtime = Runtime.from_config(
    "examples/destiny.toml",
    tools=standard_tools(),
    hooks=[
        PolicyHook(
            denied_task_keywords={"forbidden"},
            denied_tools={"DangerousTool"},
            max_risk_level="medium",
        )
    ],
)
```

`PolicyHook` can block:

- Task keywords.
- Tool names.
- Tool argument substrings.
- Risk levels above a configured threshold.

## Evaluation

Use deterministic benchmark cases to check whether an enhanced agent behaves as
expected.

```python
from destiny import Benchmark, EvalCase, RunStatus

benchmark = Benchmark([
    EvalCase(name="happy-path", task="hello", expect_tool="Echo"),
    EvalCase(
        name="danger-blocked",
        task="delete root",
        context={"tool": "Bash", "tool_args": {"command": "rm -rf /"}},
        expect_status=RunStatus.INTERRUPTED,
        expect_tool="Bash",
    ),
])

report = benchmark.run(enhanced_agent)
print(report.summary())
```

Use a deterministic quality gate when the output itself needs to be scored:

```python
from destiny import QualityEvaluator, QualityRubric

rubric = QualityRubric(
    min_score=0.85,
    min_answer_chars=60,
    required_terms=("Destiny", "runtime", "OpenClaw", "token budget"),
    forbidden_terms=("unknown", "cannot"),
)
evaluator = QualityEvaluator(rubric)

EvalCase(
    name="quality-gated-status",
    task="Explain Destiny runtime OpenClaw token budget status.",
    judge=evaluator.judge(),
)
```

Run the quality gate example:

```bash
python examples/quality_gate.py
```

## CLI

Run the engine:

```bash
destiny-engine --task "search AI news" --tool WebSearch --arg "query=AI news" --json
```

Use a project-local state directory:

```bash
destiny-engine --task "search AI news" --tool WebSearch --arg "query=AI news" --state-dir .destiny --json
```

Override permission mode:

```bash
destiny-engine --task "inspect project" --tool Read --arg "path=README.md" --permission read-only --json
```

PowerShell users should prefer `--arg KEY=VALUE` over inline JSON. JSON is also
supported:

```bash
destiny-engine --task "search AI news" --tool WebSearch --args "{\"query\":\"AI news\"}" --json
```

## Runtime Configuration

Example `destiny.toml`:

```toml
[runtime]
workspace_root = "."
state_dir = ".destiny"
permission_mode = "workspace-write"
audit_log = true
persist_runs = true
default_risk_level = "low"
memory_backend = "file"
token_budget_enabled = true
token_chars_per_token = 4
max_context_tokens = 8192
max_task_tokens = 2048
max_model_prompt_tokens = 8192
max_model_response_tokens = 4096
max_tool_result_tokens = 4096
max_memory_record_tokens = 1024
```

Allowed values:

| Field | Values |
| --- | --- |
| `permission_mode` | `read-only`, `workspace-write`, `full-access` |
| `default_risk_level` | `low`, `medium`, `high` |
| `memory_backend` | `file`, `vector`, `sqlite-vector` |
| `token_budget_enabled` | `true`, `false` |
| `token_chars_per_token` | positive integer rough estimator |
| `max_*_tokens` | positive integer budget limits |

## Runtime Flow

```text
START
  -> intent/config/model-selection
  -> parallel safety-verification + routing
  -> execution-record
  -> after-action-review/checkpoint
  -> END
```

Low-confidence tasks route to clarification. High-risk or blocked tool calls
route to interruption and require explicit confirmation/resume.

## Project Layout

| Path | Purpose |
| --- | --- |
| `destiny/runtime.py` | Public embeddable runtime facade. |
| `destiny/agents.py` | Agent enhancement contracts and wrapper. |
| `destiny/adapters.py` | Built-in file, shell, and HTTP tool adapters. |
| `destiny/providers.py` | Model, memory, embedding, file/vector/SQLite providers. |
| `destiny/mcp.py` | MCP-style JSON-RPC bridge for Runtime tools. |
| `destiny/openclaw.py` | OpenClaw-style request/response bridge and skill manifest helper. |
| `destiny/token_budget.py` | Token estimates, compaction helpers, and budgeted provider views. |
| `destiny/tools.py` | Tool adapter contracts and manifest helpers. |
| `destiny/evals.py` | Benchmark and deterministic evaluation helpers. |
| `destiny/quality.py` | Deterministic quality scoring and Benchmark-compatible quality gates. |
| `destiny/hooks.py` | Lifecycle hooks and policy hook. |
| `destiny/stores.py` | JSONL audit log and file-backed run store. |
| `scripts/province_graph.py` | State graph runtime and checkpointing. |
| `scripts/destiny_engine.py` | End-to-end orchestration and CLI. |
| `scripts/tool_safety_chain.py` | Tool safety checks. |
| `scripts/model_router.py` | Model aliasing, selection, fallback, availability checks. |
| `scripts/config_merger.py` | Layered configuration merge. |
| `scripts/tool_result_cache.py` | TTL/LRU tool result cache. |
| `scripts/execution_tracer.py` | Tracing, metrics, and export helpers. |
| `scripts/memory_blocks.py` | Core and archival memory block prototype. |
| `examples/` | Runnable integration examples. |
| `examples/complete_agent_task.py` | Complete repository-audit agent task. |
| `examples/mcp_bridge.py` | MCP-style JSON-RPC tool bridge demo. |
| `examples/openclaw_bridge.py` | OpenClaw-style chat payload bridge demo. |
| `examples/quality_gate.py` | Deterministic quality gate demo. |
| `tests/test_all.py` | Deterministic smoke/integration coverage. |
| `docs/ci-cd.md` | GitHub Actions CI/CD workflow template and token-scope note. |

## Production Baseline

The repository now provides:

- Installable package via `pyproject.toml`.
- Console script entry point: `destiny-engine`.
- Public embeddable API: `destiny.Runtime`.
- Standard tool adapters with safety checks.
- Tool discovery and manifest export.
- File, JSON vector, and SQLite vector memory backends.
- Provider interfaces for models, memory, and embeddings.
- Agent enhancement wrapper.
- OpenClaw-style bridge for chat payload integration.
- MCP-style bridge for tool-listing and tool-calling integration.
- Policy hooks.
- Evaluation helpers.
- Deterministic quality evaluator and Benchmark-compatible quality gates.
- Audit logs and run result persistence.
- Configurable state directory.
- Token budget controls for context, model calls, memory retrieval, and tool results.
- Deterministic test suite covering 129 scenarios.
- Complete real-case example for an agent-driven repository readiness audit.

## Current Limits

This is still a production-oriented framework baseline, not a finished ecosystem.
Important remaining work:

- Enable GitHub Actions CI once a token with `workflow` scope is available.
- Add first-class OpenAI/local embedding provider adapters.
- Add external vector database adapters such as pgvector or Qdrant.
- Add bridge packages for LangChain, AutoGen, Codex-style runtimes, full MCP transport, and deeper OpenClaw deployments.
- Split the monolithic `tests/test_all.py` into focused pytest modules.
- Add release packaging and formal versioned docs.

## License

MIT
