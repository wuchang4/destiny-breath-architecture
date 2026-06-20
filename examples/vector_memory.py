"""Use the file-backed vector memory provider."""

from __future__ import annotations

import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from destiny import Runtime, RuntimeConfig, VectorMemoryProvider


with tempfile.TemporaryDirectory() as tmpdir:
    memory_path = os.path.join(tmpdir, ".destiny", "memory", "vector-memory.json")
    memory = VectorMemoryProvider(memory_path)
    runtime = Runtime.from_config(
        RuntimeConfig(
            workspace_root=tmpdir,
            state_dir=os.path.join(tmpdir, ".destiny"),
            memory_backend="vector",
        ),
        memory_provider=memory,
    )

    runtime.memory_provider.put(
        "agent-runtime",
        "Agent runtime memory should preserve checkpoints, traces, and tool outcomes.",
        {"kind": "architecture"},
    )
    runtime.memory_provider.put(
        "recipe",
        "A cooking recipe needs salt, oil, and heat.",
        {"kind": "irrelevant"},
    )

    reloaded = VectorMemoryProvider(memory_path)
    hit = reloaded.search_with_scores("runtime checkpoint trace memory", top_k=1)[0]
    print(hit[0].key)
    print(round(hit[1], 3))
