# Known Issues

This file tracks known engineering gaps after the industrial-baseline upgrade.

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | External quality evaluation is missing; output quality is not judged by an independent evaluator. | High | Needs design |
| 2 | The public `Runtime` has built-in adapters, but ecosystem bridges for OpenAI/Codex/LangChain/AutoGen/MCP-style runtimes are not shipped yet. | High | Needs ecosystem bridges |
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
- The project now includes `pyproject.toml`, a console script entry point, and GitHub Actions CI.
- `DestinyEngine` and public `Runtime` now support configurable state directories for traces, checkpoints, cache, audit logs, and run result files.
- `Runtime` now defaults to durable project-local file memory via `FileMemoryProvider`.
- Public `Runtime` now ships standard file, shell, and HTTP GET tool adapters with workspace/private-host safeguards.
- `standard_tools()` provides a conservative built-in adapter bundle, and `RuntimeConfig.permission_mode` is propagated into the graph safety layer.
- `VectorMemoryProvider`, `HashEmbeddingProvider`, and `RuntimeConfig.memory_backend = "vector"` now provide a dependency-free vector memory path.
- `SqliteVectorMemoryProvider` and `RuntimeConfig.memory_backend = "sqlite-vector"` now provide a dependency-free SQLite vector memory backend.
- Runtime now exposes `list_tools()`, `get_tool()`, and `tool_manifest()` for external agent/tool-calling integration.
