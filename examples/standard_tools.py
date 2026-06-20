"""Use built-in standard tool adapters with Runtime."""

from __future__ import annotations

import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from destiny import Runtime, RuntimeConfig, standard_tools


with tempfile.TemporaryDirectory() as tmpdir:
    runtime = Runtime.from_config(
        RuntimeConfig(workspace_root=tmpdir, state_dir=f"{tmpdir}/.destiny"),
        tools=standard_tools(),
    )

    written = runtime.run(
        "write a note",
        tool_name="WriteFile",
        tool_args={"path": "notes/hello.txt", "content": "hello from standard adapters"},
    )
    print(written.tool_results["WriteFile"].ok)

    read = runtime.run(
        "read the note",
        tool_name="Read",
        tool_args={"path": "notes/hello.txt"},
    )
    print(read.tool_results["Read"].data["content"])
