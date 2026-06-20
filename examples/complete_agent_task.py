"""Complete agent task: audit a repository and write an agent-readiness report.

This example is intentionally deterministic. It demonstrates how Destiny wraps
an existing agent, validates a tool call, writes an output artifact, persists
memory, and verifies the outcome with a benchmark case.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from destiny import (  # noqa: E402
    AgentPlan,
    Benchmark,
    EvalCase,
    FunctionTool,
    Runtime,
    RuntimeConfig,
)


class RepositoryAuditAgent:
    name = "repository-audit-agent"

    def plan(self, task, context):
        return AgentPlan(
            task=task,
            tool_name="ProjectAudit",
            tool_args={
                "input_path": "README.md",
                "output_path": "reports/agent-readiness.md",
            },
            rationale="Inspect repository documentation and produce a readiness report.",
        )

    def reflect(self, plan, run, context):
        result = run.tool_results[plan.tool_name]
        if not result.ok:
            return {"ok": False, "error": result.error}
        memory_hits = context["memory"].search("agent readiness report", top_k=1)
        return {
            "ok": True,
            "score": result.data["score"],
            "report_path": result.data["report_path"],
            "memory_hit": memory_hits[0].key if memory_hits else "",
        }


def project_audit_tool(args, context):
    root = Path(context["workspace_root"])
    input_path = root / args["input_path"]
    output_path = root / args["output_path"]

    readme = input_path.read_text(encoding="utf-8")
    checks = {
        "quick_start": "Quick Start" in readme,
        "install": "pip install" in readme,
        "runtime": "Runtime" in readme,
        "memory": "memory" in readme.lower(),
        "evaluation": "Benchmark" in readme or "Evaluation" in readme,
        "tool_manifest": "tool_manifest" in readme or "Tool Manifest" in readme,
    }
    score = round(sum(1 for passed in checks.values() if passed) / len(checks), 2)
    missing = [name for name, passed in checks.items() if not passed]
    missing_lines = [f"- {name}" for name in missing] if missing else ["- none"]

    report = [
        "# Agent Readiness Report",
        "",
        f"Score: {score:.2f}",
        "",
        "## Passed Checks",
        *[f"- {name}" for name, passed in checks.items() if passed],
        "",
        "## Missing Checks",
        *missing_lines,
        "",
        "## Recommendation",
        "Repository is ready for an agent integration demo."
        if score >= 0.8 else "Repository needs clearer onboarding before promotion.",
        "",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(report), encoding="utf-8")

    context["memory"].put(
        "agent-readiness-report",
        f"Agent readiness report generated with score {score:.2f}.",
        {"report_path": str(output_path), "score": score},
    )
    return {
        "score": score,
        "checks": checks,
        "report_path": str(output_path),
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        source_readme = Path(PROJECT_ROOT) / "README.md"
        (workspace / "README.md").write_text(
            source_readme.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        runtime = Runtime.from_config(
            RuntimeConfig(
                workspace_root=str(workspace),
                state_dir=str(workspace / ".destiny"),
                memory_backend="sqlite-vector",
            ),
            tools=[
                FunctionTool(
                    name="ProjectAudit",
                    required=("input_path", "output_path"),
                    handler=project_audit_tool,
                    description="Audit repository docs and write an agent-readiness report.",
                )
            ],
        )
        try:
            agent = runtime.enhance(RepositoryAuditAgent())
            outcome = agent.run("Audit this repository for agent-readiness.", run_id="real-case-audit")
            report_path = Path(outcome.answer["report_path"])
            print(f"status={outcome.run.status.value}")
            print(f"score={outcome.answer['score']:.2f}")
            print(f"report_exists={report_path.exists()}")
            print(f"memory_hit={outcome.answer['memory_hit']}")

            benchmark = Benchmark([
                EvalCase(
                    name="repository-audit",
                    task="Audit this repository for agent-readiness.",
                    expect_tool="ProjectAudit",
                    judge=lambda result, case: (
                        result.answer["ok"]
                        and result.answer["score"] >= 0.8
                        and Path(result.answer["report_path"]).exists()
                    ),
                )
            ])
            print(benchmark.run(agent).summary())
        finally:
            runtime.close()


if __name__ == "__main__":
    main()
