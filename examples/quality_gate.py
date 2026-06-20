"""Use a deterministic quality gate with an enhanced agent benchmark."""

from __future__ import annotations

import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from destiny import (  # noqa: E402
    AgentPlan,
    Benchmark,
    EvalCase,
    FunctionTool,
    QualityEvaluator,
    QualityRubric,
    Runtime,
    RuntimeConfig,
)


class StatusAgent:
    name = "status-agent"

    def plan(self, task, context):
        return AgentPlan(task=task, tool_name="Status", tool_args={"message": task})

    def reflect(self, plan, run, context):
        return run.tool_results[plan.tool_name].data


def status_tool(args, context):
    return {
        "answer": (
            "Destiny agent upgrade status: runtime, memory, evaluation, "
            "OpenClaw bridge, and token budget controls are working."
        )
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        runtime = Runtime.from_config(
            RuntimeConfig(workspace_root=tmpdir, state_dir=os.path.join(tmpdir, ".destiny")),
            tools=[FunctionTool(name="Status", required=("message",), handler=status_tool)],
        )
        rubric = QualityRubric(
            min_score=0.85,
            min_answer_chars=60,
            required_terms=("Destiny", "runtime", "OpenClaw", "token budget"),
            forbidden_terms=("unknown", "cannot"),
        )
        evaluator = QualityEvaluator(rubric)
        agent = runtime.enhance(StatusAgent())
        report = Benchmark([
            EvalCase(
                name="quality-gated-status",
                task="Explain Destiny runtime OpenClaw token budget status.",
                expect_tool="Status",
                judge=evaluator.judge(),
            )
        ]).run(agent)
        outcome = agent.run("Explain Destiny runtime OpenClaw token budget status.", run_id="quality-demo")
        assessment = evaluator.evaluate(task="Explain Destiny runtime OpenClaw token budget status.", outcome=outcome)
        print(report.summary())
        print(assessment.summary)
        runtime.close()


if __name__ == "__main__":
    main()
