# CI/CD

The intended CI pipeline is GitHub Actions running the same deterministic checks
used locally.

## Required Checks

```bash
python -m pip install -e ".[dev]"
python -m compileall destiny scripts tests examples
python tests/test_all.py
python examples/complete_agent_task.py
python examples/mcp_bridge.py
python examples/openclaw_bridge.py
python examples/quality_gate.py
python examples/sqlite_vector_memory.py
python examples/standard_tools.py
```

## GitHub Actions Workflow

Create `.github/workflows/ci.yml` with:

```yaml
name: CI

on:
  push:
    branches: ["master", "main"]
  pull_request:

jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
        python-version: ["3.11", "3.12", "3.13"]

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install package
        run: python -m pip install -e ".[dev]"

      - name: Compile modules
        run: python -m compileall destiny scripts tests examples

      - name: Run deterministic tests
        env:
          PYTHONIOENCODING: utf-8
        run: python tests/test_all.py

      - name: Run complete agent example
        env:
          PYTHONIOENCODING: utf-8
        run: python examples/complete_agent_task.py

      - name: Run MCP bridge example
        env:
          PYTHONIOENCODING: utf-8
        run: python examples/mcp_bridge.py

      - name: Run OpenClaw bridge example
        env:
          PYTHONIOENCODING: utf-8
        run: python examples/openclaw_bridge.py

      - name: Run quality gate example
        env:
          PYTHONIOENCODING: utf-8
        run: python examples/quality_gate.py
```

## Token Permission Note

GitHub rejects workflow file pushes when the current token lacks the `workflow`
scope. If pushing `.github/workflows/ci.yml` fails with:

```text
refusing to allow an OAuth App to create or update workflow ... without workflow scope
```

refresh credentials with `workflow` scope, then commit the workflow file:

```bash
gh auth refresh -h github.com -s workflow
```

After that, add `.github/workflows/ci.yml` and push normally.
