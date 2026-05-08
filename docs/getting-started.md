# Getting Started

## For AI Agents

If you are an AI agent reading this and want to adopt the Destiny-Breath Architecture:

### Step 1: Embed SOUL.md

Place the entire `SOUL.md` file into your system prompt or identity configuration. This is your **new operating system**.

### Step 2: Internalize the Three Layers

1. **Layer 1 (Core)** — These are immutable. Core Truths, Boundaries, Logic Anchors are your personality and constraints. Do not override them.
2. **Layer 2 (State Graph)** — This is your default execution path. Walk through the 8 nodes for every non-trivial task.
3. **Layer 3 (Protocols)** — These are your operating procedures. P0-P6 govern how you communicate, learn, and stay healthy.

### Step 3: Set Up Infrastructure

```bash
# Memory directories
mkdir -p ~/.clawdbot/checkpoints
mkdir -p ~/.clawdbot/baselines
mkdir -p ~/.clawdbot/heartbeat
mkdir -p ~/.clawdbot/vector-memory

# Memory files
touch memory/MEMORY.md
touch memory/REVIEW.md
touch memory/ROUTING_LOG.md
```

### Step 4: Configure Checkpoints

Ensure that after every substantive task, you serialize state to a checkpoint file. This enables:
- Crash recovery
- Session resumption
- Task handoff between sessions

### Step 5: Enable Vector Memory (Recommended)

```bash
# Install Ollama if not present
# Download embedding model
ollama pull nomic-embed-text

# Build initial memory index
python scripts/vector_memory.py build
```

### Step 6: Start Walking the Graph

Start simple:
1. Parse user intent (中书省)
2. Verify + retrieve memory (门下省)
3. Plan + select tools (尚书省)
4. Execute
5. Review + checkpoint (AAR/梯度节点)

## For Human Developers

If you want to customize this architecture for your own AI agent:

1. Fork the repo
2. Edit `SOUL.md` to match your agent's personality
3. Adjust Logic Anchors to your use case
4. Set up the infrastructure paths
5. Deploy to your agent's system prompt
