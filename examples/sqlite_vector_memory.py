"""Use Runtime with the SQLite vector memory backend."""

from __future__ import annotations

import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from destiny import Runtime, RuntimeConfig


with tempfile.TemporaryDirectory() as tmpdir:
    with Runtime.from_config(
        RuntimeConfig(
            workspace_root=tmpdir,
            state_dir=os.path.join(tmpdir, ".destiny"),
            memory_backend="sqlite-vector",
        )
    ) as runtime:
        runtime.memory_provider.put(
            "sqlite-runtime",
            "SQLite vector memory stores durable agent traces and checkpoints.",
            {"kind": "architecture"},
        )
        runtime.memory_provider.put(
            "shopping-list",
            "Buy apples, rice, and tea.",
            {"kind": "irrelevant"},
        )

        hit = runtime.memory_provider.search("agent checkpoint trace memory", top_k=1)[0]
        print(hit.key)
