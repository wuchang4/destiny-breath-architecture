# Known Issues

This file tracks known engineering gaps after the industrial-baseline upgrade.

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | Deterministic quality evaluation is available, but model-based external judging and calibration datasets are not shipped yet. | High | Needs LLM judge/calibration set |
| 2 | The public `Runtime` has OpenClaw and MCP-style tool bridges, but full MCP transport plus OpenAI/Codex/LangChain/AutoGen bridges are not shipped yet. | High | Needs more ecosystem bridges |
| 3 | Vector memory backends are available, but production semantic quality still depends on real embedding providers and external vector database adapters. | Medium | Needs embedding/external vector adapters |
| 4 | Auxiliary scripts such as heartbeat/checkpoint helpers still use user-local `~/.clawdbot` paths. | Medium | Needs shared path provider |
| 5 | Tests are centralized in `tests/test_all.py`, which is useful for smoke coverage but coarse for long-term maintenance. | Medium | Needs pytest module split |
| 6 | Skill indexing depends on operator-local `~/.workbuddy/skills`; the repository does not ship a 130-skill library. | Medium | Needs packaged sample registry |
| 7 | The graph has v3 parallel execution, but thread-level tracing still shares one trace context. | Medium | Needs thread-local trace context or span links |

## Recently Fixed

- Tool result cache is implemented and covered by deterministic tests.
- Model availability no longer returns `True` after failed fallback checks.
- `ProvinceGraph` v3 high-risk parallel paths now route to `阻断/预警` instead of bypassing interruption.
- Direct Windows test runs reconfigure stdout/stderr to UTF-8 with replacement errors.
- The project now includes `pyproject.toml`, a console script entry point, and a documented GitHub Actions CI template. Enabling the workflow requires a GitHub token with `workflow` scope.
- `DestinyEngine` and public `Runtime` now support configurable state directories for traces, checkpoints, cache, audit logs, and run result files.
- `Runtime` now defaults to durable project-local file memory via `FileMemoryProvider`.
- Public `Runtime` now ships standard file, shell, and HTTP GET tool adapters with workspace/private-host safeguards.
- `standard_tools()` provides a conservative built-in adapter bundle, and `RuntimeConfig.permission_mode` is propagated into the graph safety layer.
- `VectorMemoryProvider`, `HashEmbeddingProvider`, and `RuntimeConfig.memory_backend = "vector"` now provide a dependency-free vector memory path.
- `SqliteVectorMemoryProvider` and `RuntimeConfig.memory_backend = "sqlite-vector"` now provide a dependency-free SQLite vector memory backend.
- Runtime now exposes `list_tools()`, `get_tool()`, and `tool_manifest()` for external agent/tool-calling integration.
- Package/runtime/tracing/User-Agent version metadata is unified around `0.5.0`.
- `examples/complete_agent_task.py` now demonstrates a complete repository-audit agent task with artifact writing, SQLite vector memory, and benchmark verification.
- Runtime now includes dependency-free token budget controls for context compaction, model prompts/responses, memory search results, and tool result payloads.
- `OpenClawBridge` and `examples/openclaw_bridge.py` now provide a first ecosystem bridge for chat-style agent payloads.
- `QualityEvaluator`, `QualityRubric`, and `examples/quality_gate.py` now provide deterministic output-quality gates for Benchmark runs.
- `McpToolBridge` and `examples/mcp_bridge.py` now provide a dependency-free MCP-style `tools/list` and `tools/call` bridge.
