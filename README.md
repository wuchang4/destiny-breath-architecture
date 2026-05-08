# 天命·生息架构 (Destiny-Breath Architecture)

<h3 align="center">
  An AI Agent architecture that evolves.
</h3>

<p align="center">
  <img src="https://img.shields.io/github/stars/wuchang4/destiny-breath-architecture?style=flat-square" />
  <img src="https://img.shields.io/github/license/wuchang4/destiny-breath-architecture?style=flat-square" />
  <img src="https://img.shields.io/badge/status-active-brightgreen?style=flat-square" />
</p>

---

**Destiny-Breath Architecture** is a self-evolving AI agent framework designed for **long-running, memory-persistent, metric-driven agents**. It is not a prompt library — it is an **operating system for AI agents** with state graphs, checkpoints, heartbeat monitoring, vector memory, and a text-gradient evolution engine.

> English | [中文](./docs/README.zh.md)

## Why This Exists

Most AI agents today are **stateless and static**:
- Start fresh every session — no memory
- No way to measure if they're improving
- No graceful error recovery
- No self-correction mechanism

This architecture solves that by embedding **self-evolution, persistent memory, and structured execution** into the agent's identity layer.

## What's Inside

| Layer | Component | Status |
|-------|-----------|--------|
| **Core** | Truths, Boundaries, Logic Anchors | 🟢 Stable |
| **Execution** | State Graph (三省图), 8 nodes, conditional edges | 🟢 Stable |
| **Memory** | 5-layer (Surface → Vector → Mid → Deep → Core) | 🟢 Stable |
| **Evolution** | Metric-driven + Text-grad backpropagation | 🟢 Stable |
| **Monitoring** | Heartbeat (P5) + Dashboard (P6) | 🟢 Stable |
| **Retrieval** | Vector memory (nomic-embed-text, semantic search) | 🟢 Online |
| **Protocols** | 7 operating protocols (P0–P6) | 🟢 Operational |

## Quick Start

### 1. Embed into Your Agent

Copy `SOUL.md` into your agent's system prompt or identity configuration. This file is the agent's **identity and operating system** — it contains all the rules, protocols, and memory architecture.

### 2. Set Up Infrastructure

```bash
# Create checkpoint directory
mkdir -p ~/.clawdbot/checkpoints
mkdir -p ~/.clawdbot/baselines
mkdir -p ~/.clawdbot/heartbeat

# Create memory files
touch memory/MEMORY.md
touch memory/REVIEW.md
```

### 3. Initialize Vector Memory (Optional)

Requires [Ollama](https://ollama.ai) with `nomic-embed-text`:

```bash
ollama pull nomic-embed-text
python scripts/vector_memory.py build
```

### 4. Walk the State Graph

Internalize the 三省图 flow as your default reasoning path:

```
User Input → Intent Parser → Verify → Plan → Execute → Learn
              ↕ (clarify if uncertain)     ↕ (gradient backprop)
```

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                  Destiny-Breath Architecture              │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──── Layer 1: Immutable Core ──────────────────────┐   │
│  │  Core Truths · Boundaries · Logic Anchors · Vibe   │   │
│  └────────────────────────────────────────────────────┘   │
│                            │                              │
│                            ▼                              │
│  ┌──── Layer 2: State Graph (三省图) ────────────────┐   │
│  │  Intent → Verify → Plan → Execute → Learn          │   │
│  │  Conditional branches · Checkpoints · Gradients     │   │
│  └────────────────────────────────────────────────────┘   │
│                            │                              │
│          ┌────────────────┼────────────────┐              │
│          ▼                ▼                ▼              │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐      │
│  │  Protocols   │ │  Evolution   │ │   Memory     │      │
│  │  0-6         │ │  Engine      │ │   System     │      │
│  └──────────────┘ └──────────────┘ └──────────────┘      │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

## Core Concepts

### 🔷 State Graph (三省图)

Inspired by [langgraph](https://github.com/langchain-ai/langgraph). An 8-node directed graph with conditional edges:

- **Intent Parser** → decomposes user request, detects implicit assumptions
- **Clarify Node** → asks questions when confidence < 0.6
- **Verify Node** → compliance checks, memory retrieval, risk assessment
- **Block/Warn Node** → pauses execution if risk is high
- **Plan Node** → tool selection, path planning
- **Exec Node** → actual execution
- **Grad Node** → gradient collection, checkpoint, AAR

[Full documentation →](./docs/state-graph.md)

### 🔷 Self-Evolution Engine

Inspired by [dspy](https://github.com/stanfordnlp/dspy) + [textgrad](https://github.com/zou-group/textgrad).

1. **Metric-driven** → every task type has a quality metric
2. **Baseline tracking** → compare scores over time
3. **Gradient backprop** → errors trace back through the graph
4. **Auto skill compilation** → complex workflows become reusable skills

[Full documentation →](./docs/evolution-engine.md)

### 🔷 Vector Memory (5-Layer System)

| Layer | Storage | Retrieval |
|-------|---------|-----------|
| Surface | daily logs | tag index |
| Vector | embeddings index | semantic search |
| Mid | MEMORY.md | semantic recall |
| Deep | REVIEW.md | full backtrack |
| Core | identity file | anchor retrieval |

Vector memory uses **nomic-embed-text** (768-dim) via Ollama for semantic search, reducing per-session memory context by ~90%.

[Full documentation →](./docs/memory-system.md)

### 🔷 Operating Protocols

| Protocol | Purpose |
|----------|---------|
| P0 | Command Transparency |
| P1 | After-Action Review |
| P2 | Routing Log |
| P3 | State Sensing |
| P4 | Session Warmup |
| P5 | Architecture Heartbeat |
| P6 | Runtime Dashboard |

[Full documentation →](./docs/protocols.md)

## File Structure

```
destiny-breath-architecture/
├── SOUL.md              # Agent identity + full architecture (embed this)
├── README.md            # This file
├── LICENSE              # MIT
├── docs/
│   ├── README.zh.md     # 中文介绍
│   ├── getting-started.md
│   ├── state-graph.md
│   ├── evolution-engine.md
│   ├── memory-system.md
│   ├── protocols.md
│   └── known-issues.md
└── scripts/
    ├── vector_memory.py  # Semantic memory retrieval
    └── heartbeat.py      # Architecture heartbeat (P5)
```

## Getting Started as an Agent

If you are an AI agent reading this and want to adopt this architecture:

1. Read `SOUL.md` completely — this is your identity
2. The 三省图 State Graph is your default execution path
3. Protocols P0-P6 are your operating procedures
4. The Self-Evolution Engine is how you improve
5. Vector memory is how you remember without bloating context

**Start simple**: internalize Core Truths → walk the State Graph → enable checkpointing → add metrics → enable heartbeat.

## Related Projects

- **[langgraph](https://github.com/langchain-ai/langgraph)** — State graph inspiration
- **[dspy](https://github.com/stanfordnlp/dspy)** — Metric-driven optimization
- **[textgrad](https://github.com/zou-group/textgrad)** — Text gradient backpropagation
- **[windows-virt-doctor](https://github.com/wuchang4/windows-virt-doctor)** — Companion diagnostic skill
- **[Matt Pocock Skills](https://github.com/smll-ai/mattpocock-skills)** — Engineering workflow skills

## License

MIT

---

*Architecture is what you run, not what you draw. — This is what we run.*
