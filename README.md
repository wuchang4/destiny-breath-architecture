# 天命·生息架构 (Destiny-Breath Architecture)

<h3 align="center">
  An AI Agent operating system that evolves itself.
</h3>

<p align="center">
  <img src="https://img.shields.io/github/stars/wuchang4/destiny-breath-architecture?style=flat-square" />
  <img src="https://img.shields.io/github/license/wuchang4/destiny-breath-architecture?style=flat-square" />
  <img src="https://img.shields.io/badge/status-v3.0-brightgreen?style=flat-square" />
</p>

---

**Destiny-Breath Architecture** is a self-evolving AI agent framework designed for **long-running, memory-persistent, metric-driven agents**. It is not a prompt library — it is an **operating system for AI agents** with:

- **State Graph (三省图)**: 8-node conditional directed graph for structured reasoning
- **6 Operating Protocols**: Command transparency, AAR, routing logs, state sensing, session warmup, heartbeat, runtime dashboard
- **4-Engine Evolution**: Metric-driven optimization + text-gradient backpropagation
- **5-Layer Memory System**: Surface → Vector → Mid → Deep → Core
- **130 Skills across 7 Domain Hubs**: Search, browser, content, Douyin, media, security, agent-core
- **天行军 Subsystem**: Concrete implementation with DDGS search backend, EventBus, source tracing

## Why This Exists

Most AI agents today are **stateless and static**:
- Start fresh every session — no memory
- No way to measure if they're improving
- No graceful error recovery
- No self-correction mechanism

This architecture solves that by embedding **self-evolution, persistent memory, and structured execution** into the agent's identity layer.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│               Core Layer: Truths + Logic Anchors             │  ← Immutable
├─────────────────────────────────────────────────────────────┤
│               Capability Map: Cognition + Tools + Memory      │  ← Actual capabilities
├─────────────────────────────────────────────────────────────┤
│               Operating Protocols (P0-P6)                     │  ← Runtime rules
├─────────────────────────────────────────────────────────────┤
│               State Graph (三省图, 8 nodes)                   │  ← Execution engine
├─────────────────────────────────────────────────────────────┤
│               Evolution Engine (Metrics + Gradients)          │  ← Learning
├─────────────────────────────────────────────────────────────┤
│               Multi-Layer Memory System (5 layers)            │  ← Persistence
├─────────────────────────────────────────────────────────────┤
│               天行军 Subsystem (12 components)                │  ← Concrete practice
└─────────────────────────────────────────────────────────────┘
Runtime: WorkBuddy + DeepSeek V4 Flash
```

## Status Dashboard

| Component | Status | Description |
|-----------|--------|-------------|
| Core Truths | 🟢 Stable | Foundation of every response |
| Logic Anchors | 🟢 Stable | 11 logic anchors for structured reasoning |
| State Graph (三省图) | 🟢 Stable | 8-node conditional directed graph (ProvinceGraph, 38 lines) |
| Heartbeat (P5) | 🟢 Online | Auto self-check every 4 hours |
| Dashboard (P6) | 🟢 Online | Runtime diagnostics per heartbeat |
| Metric System | 🟡 Evolving | Evaluation metrics per task type |
| Text-Grad Evolution | 🟢 Online | Error → gradient → backpropagation → rule update |
| Vector Memory | 🟢 Online | Semantic search via nomic-embed-text, ~90% token savings |
| Skill System | 🟢 v3 | 130 skills across 7 domain hubs |
| 天行军 Subsystem | 🟢 Full loop | State Graph → EventBus → DDGS → AAR closed loop |
| EventBus | 🟢 Online | SQLite-persisted event-driven architecture |

## Files

| File | Description |
|------|-------------|
| [SOUL.md](./SOUL.md) | Core architecture definition — the agent's identity and operating system |
| [白皮书.md](./%E7%99%BD%E7%9A%AE%E4%B9%A6.md) | Architecture white paper (Chinese) |
| [白皮书_v3.0.pdf](./%E7%99%BD%E7%9A%AE%E4%B9%A6_v3.0.pdf) | White paper in PDF format |
| [架构审阅报告.pdf](./%E6%9E%B6%E6%9E%84%E5%AE%A1%E9%98%85%E6%8A%A5%E5%91%8A.pdf) | Full architecture review report with source attribution table |

## Quick Start

### 1. Embed into Your Agent

Copy `SOUL.md` into your agent's system prompt or identity configuration. This file is the agent's **identity and operating system** — it contains all the rules, protocols, and memory architecture.

### 2. Set Up Infrastructure

```bash
# Create checkpoint directory
mkdir -p ~/.clawdbot/checkpoints
mkdir -p ~/.clawdbot/baselines
mkdir -p ~/.clawdbot/heartbeat
```

### 3. Configure Heartbeat (Optional)

```bash
cp scripts/heartbeat.py ~/.clawdbot/heartbeat/
```

## Design References

This architecture is not built from scratch. Key inspirations:

| Source | What We Borrowed | Depth |
|--------|-----------------|-------|
| **langgraph** (LangChain) | State Graph, checkpoint persistence, Human-in-the-loop | 🔵 Deep |
| **dspy** (Stanford) | Metric system, baseline comparison, optimization loop | 🔵 Deep |
| **textgrad** | Text-gradient backpropagation, computation graph tracing | 🔵 Deep |
| **Matt Pocock** | Caveman Mode, Grill Before You Build | 🟡 Medium |
| **ByteDance DeerFlow 2.0** | Vector memory retrieval, sub-agent pooling | 🟡 Medium |
| **n8n** | Event bus, workflow orchestration | 🟡 Medium |
| **Netflix Conductor** | Persistent state tracking, replay mechanism | 🟢 Light |
| **gpt-researcher** | Search pipeline (decompose → search → report) | 🟢 Light |
| **OpenHands** | Agent unified interface abstraction | 🟢 Light |
| **隋唐三省六部制** | Naming and role division for 三省图 nodes | 🟢 Conceptual |

## Known Limitations

- State Graph runs as mental simulation, not an independent engine
- Metric scores are self-assessed, no external validator
- Memory distillation is partially manual
- No tool result caching yet
- WeChat control limited by Qt UIA + missing multimodal vision

---

*Built by 天命人 · Powered by DeepSeek V4 Flash · v3.0 (2026-05-09)*
