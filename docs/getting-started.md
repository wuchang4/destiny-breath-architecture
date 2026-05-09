# Getting Started with Destiny-Breath Architecture

## Prerequisites

- An AI agent framework that supports custom system prompts / identity files
- DeepSeek V4 Flash or equivalent LLM
- Python 3.10+ (for scripts and utilities)
- (Optional) Ollama with nomic-embed-text for vector memory

## Step 1: Embed the Architecture

Copy `SOUL.md` into your agent's identity configuration. This file defines:

- **Core Truths**: The agent's fundamental personality and values
- **Logic Anchors**: Reasoning rules that structure every inference
- **Protocols (P0-P6)**: Operating procedures for runtime behavior
- **State Graph**: The 8-node conditional execution engine
- **Evolution Engine**: Metric-driven + text-gradient self-improvement
- **Memory System**: 5-layer persistence architecture

## Step 2: Set Up Infrastructure

```bash
# Create the ~/.clawdbot directory structure
mkdir -p ~/.clawdbot/checkpoints
mkdir -p ~/.clawdbot/baselines
mkdir -p ~/.clawdbot/heartbeat
mkdir -p ~/.clawdbot/patrol
```

## Step 3: Configure Vector Memory (Optional)

```bash
# Install Ollama and pull the embedding model
ollama pull nomic-embed-text

# Copy the vector memory script
cp scripts/vector_memory.py ~/.clawdbot/scripts/
```

## Step 4: Configure Heartbeat (Optional)

Set up the heartbeat automation to check system health every 4 hours:

```bash
python3 ~/.clawdbot/heartbeat/heartbeat.py
```

## Step 5: Start Using

Once the architecture is embedded:

1. The agent will automatically run Protocol 4 (Session Warmup) at each session start
2. Protocol 5 (Heartbeat) will self-check every 4 hours
3. Protocol 1 (AAR) will run after each substantive task
4. State Graph will structure all non-trivial reasoning paths

## Next Steps

- Review the [白皮书.md](../%E7%99%BD%E7%9A%AE%E4%B9%A6.md) for a comprehensive understanding
- Read [known-issues.md](./known-issues.md) for current limitations
- Check the [architecture review PDF](../%E6%9E%B6%E6%9E%84%E5%AE%A1%E9%98%85%E6%8A%A5%E5%91%8A.pdf) for full source attribution
