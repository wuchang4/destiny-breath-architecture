#!/usr/bin/env python3
"""
天命架构 — 统一执行引擎 (Destiny Engine)
把所有独立脚本串联成一条自动执行链路。

调用方式：
    python destiny_engine.py --task "搜索AI最新动态" --risk low
    python destiny_engine.py --task "删除所有日志" --risk high
    python destiny_engine.py --resume checkpoint.json

执行链路：
    用户指令 → 三省图(中书省→门下省→尚书省→执行→AAR)
    每个节点自动调用对应的脚本：
        中书省 → config_merger.py（读取配置）+ model_router.py（选模型）
        门下省 → tool_safety_chain.py（安全验证）
        尚书省 → model_router.py（任务路由）+ tool_result_cache.py（缓存检查）
        执行节点 → 实际工具调用（由外层 Agent 执行）
        AAR → execution_tracer.py（追踪导出）+ checkpoint_writer.py（检查点）
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# 添加脚本目录到路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from province_graph import ProvinceGraph
from tool_safety_chain import ToolSafetyChain
from model_router import ModelRouter
from config_merger import ConfigMerger
from execution_tracer import ExecutionTracer
from tool_result_cache import ToolResultCache


class DestinyEngine:
    """
    天命统一执行引擎。
    
    将三省图、安全验证链、模型路由、执行追踪、工具缓存
    串联成一条自动执行链路。
    """

    def __init__(self, workspace_root: str = "."):
        self.workspace_root = os.path.abspath(workspace_root)
        self.tracer = ExecutionTracer()
        self.config = ConfigMerger(project_root=self.workspace_root)
        self.router = ModelRouter()
        self.cache = ToolResultCache()
        self.graph = ProvinceGraph()
        self.chain = None  # 延迟初始化，需要知道权限模式

    def run(self, task: str, risk_level: str = "low",
            tool_name: str = "", tool_args: dict = None,
            max_steps: int = 20) -> dict:
        """
        执行完整三省图流程。
        
        Args:
            task: 用户任务描述
            risk_level: 预估风险等级（low/medium/high）
            tool_name: 要调用的工具名
            tool_args: 工具参数
            max_steps: 最大步数
            
        Returns:
            执行结果字典
        """
        tool_args = tool_args or {}
        config = self.config.merge()
        permission = config.get("default_permission_mode", "workspace-write")
        self.chain = ToolSafetyChain(
            permission_mode=permission,
            max_output_chars=config.get("tool_safety", {}).get("max_output_chars", 20000),
        )

        # 注册节点处理器
        self._register_handlers(task, tool_name, tool_args, risk_level)

        # 自动运行三省图
        self.graph.run(max_steps=max_steps)

        # 导出追踪
        trace_path = os.path.join(
            os.path.expanduser("~/.clawdbot"), "traces",
            f"trace_{int(time.time())}.json"
        )
        os.makedirs(os.path.dirname(trace_path), exist_ok=True)
        self.tracer.export_json(trace_path)

        return {
            "success": self.graph.is_finished() and not self.graph.is_interrupted(),
            "interrupted": self.graph.is_interrupted(),
            "interrupt_reason": self.graph.get_interrupt_reason(),
            "current_node": self.graph.current_node,
            "node_history": self.graph.node_history,
            "state": self.graph.state,
            "trace_path": trace_path,
            "trace_summary": self.tracer.summary(),
        }

    def _register_handlers(self, task: str, tool_name: str,
                            tool_args: dict, risk_level: str):
        """为三省图每个节点注册处理函数。"""

        def handle_中书省(state, span):
            """中书省：意图解析 + 配置加载 + 模型选择"""
            with self.tracer.span("中书省-意图解析") as s:
                state["user_intent"] = task
                state["risk_level"] = risk_level
                s.set_attribute("task", task[:100])
                s.set_attribute("risk_level", risk_level)

            with self.tracer.span("中书省-配置加载") as s:
                config = self.config.merge()
                s.set_attribute("default_model", config.get("default_model", "smart"))

            with self.tracer.span("中书省-模型选择") as s:
                model = self.router.auto_select(
                    self._classify_task(task)
                )
                state["selected_tools"] = [tool_name] if tool_name else []
                s.set_attribute("selected_model", model)
                s.set_attribute("task_type", self._classify_task(task))

            return {"confidence": 0.8}

        def handle_门下省(state, span):
            """门下省：安全验证 + 缓存检查"""
            with self.tracer.span("门下省-安全验证") as s:
                if tool_name and tool_args:
                    safety = self.chain.validate(tool_name, tool_args)
                    s.set_attribute("verdict", safety.verdict.value)
                    s.set_attribute("risk_level", safety.risk_level.value)

                    if not safety.passed:
                        state["errors"].append(f"安全验证失败: {safety.block_reason}")
                        state["risk_level"] = "high"
                        return {"risk_level": "high"}

                    if safety.needs_user_confirm:
                        state["risk_level"] = "high"
                        return {"risk_level": "high"}

            with self.tracer.span("门下省-缓存检查") as s:
                if tool_name in ("WebSearch", "WebFetch") and tool_args.get("query"):
                    cached = self.cache.get(tool_name, tool_args["query"])
                    if cached:
                        s.add_event("cache_hit", {"query": tool_args["query"][:50]})
                        state["memory_hits"] = [str(cached)[:200]]

            return {"risk_level": risk_level}

        def handle_尚书省(state, span):
            """尚书省：工具路由 + 执行规划"""
            with self.tracer.span("尚书省-路由决策") as s:
                task_type = self._classify_task(task)
                model = self.router.auto_select(task_type)
                s.set_attribute("task_type", task_type)
                s.set_attribute("selected_model", model)
                s.set_attribute("tools", state.get("selected_tools", []))

            return {"route": task_type}

        def handle_执行节点(state, span):
            """执行节点：记录待执行操作（实际执行由外层 Agent 完成）"""
            with self.tracer.span("执行节点-记录") as s:
                s.set_attribute("tool", tool_name)
                s.set_attribute("args", json.dumps(tool_args, ensure_ascii=False)[:200])
                s.add_event("execution_delegated", {
                    "note": "实际工具调用由外层 Agent 执行，此处记录追踪"
                })

            # 如果是 WebSearch/WebFetch，写入缓存
            if tool_name in ("WebSearch", "WebFetch") and tool_args.get("query"):
                self.cache.put(tool_name, tool_args["query"], "执行结果由外层Agent填充")

            return {}

        def handle_AAR(state, span):
            """AAR：追踪汇总 + 检查点写入"""
            with self.tracer.span("AAR-追踪汇总") as s:
                s.set_attribute("total_spans", len(self.tracer.spans))
                s.set_attribute("errors", len(state.get("errors", [])))
                s.set_attribute("node_count", len(state.get("node_history", [])))

            with self.tracer.span("AAR-检查点") as s:
                checkpoint = self.graph.serialize()
                checkpoint_dir = os.path.join(os.path.expanduser("~/.clawdbot"), "checkpoints")
                os.makedirs(checkpoint_dir, exist_ok=True)
                checkpoint_path = os.path.join(checkpoint_dir, "destiny_engine.json")
                tmp_path = checkpoint_path + ".tmp"
                try:
                    with open(tmp_path, "w", encoding="utf-8") as f:
                        json.dump(checkpoint, f, ensure_ascii=False, indent=2)
                    os.replace(tmp_path, checkpoint_path)
                    s.add_event("checkpoint_saved", {"path": checkpoint_path})
                except OSError as e:
                    s.add_event("checkpoint_failed", {"error": str(e)})

            return {}

        # 注册处理器
        self.graph.register_handler("中书省", handle_中书省)
        self.graph.register_handler("门下省", handle_门下省)
        self.graph.register_handler("尚书省", handle_尚书省)
        self.graph.register_handler("执行节点", handle_执行节点)
        self.graph.register_handler("AAR/Checkpt", handle_AAR)

    def resume(self, checkpoint_path: str = None) -> dict:
        """从检查点恢复执行。"""
        cpath = checkpoint_path or os.path.join(
            os.path.expanduser("~/.clawdbot"), "checkpoints", "destiny_engine.json"
        )
        graph = ProvinceGraph.load_checkpoint(os.path.dirname(cpath))
        if graph:
            self.graph = graph
            self.graph.run()
            return {
                "success": self.graph.is_finished(),
                "current_node": self.graph.current_node,
                "node_history": self.graph.node_history,
            }
        return {"success": False, "error": "检查点恢复失败"}

    @staticmethod
    def _classify_task(task: str) -> str:
        """简单任务分类（0 Token，规则引擎）。"""
        task_lower = task.lower()
        if any(kw in task_lower for kw in ["搜索", "search", "查找", "找"]):
            return "simple_qa"
        if any(kw in task_lower for kw in ["代码", "code", "编程", "bug", "fix"]):
            return "code_generation"
        if any(kw in task_lower for kw in ["图片", "image", "视频", "video", "音频"]):
            return "image_analysis"
        if any(kw in task_lower for kw in ["复杂", "分析", "架构", "设计", "研究"]):
            return "complex_reasoning"
        return "default"


# ── CLI 入口 ───────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="天命统一执行引擎")
    parser.add_argument("--task", type=str, required=True, help="任务描述")
    parser.add_argument("--risk", type=str, default="low",
                        choices=["low", "medium", "high"], help="风险等级")
    parser.add_argument("--tool", type=str, default="", help="要调用的工具名")
    parser.add_argument("--args", type=str, default="{}", help="工具参数（JSON）")
    parser.add_argument("--resume", type=str, help="从检查点恢复")
    parser.add_argument("--json", action="store_true", help="JSON 输出")

    args = parser.parse_args()

    engine = DestinyEngine()

    if args.resume:
        result = engine.resume(args.resume)
    else:
        tool_args = json.loads(args.args)
        result = engine.run(
            task=args.task,
            risk_level=args.risk,
            tool_name=args.tool,
            tool_args=tool_args,
        )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"\n{'='*50}")
        print(f"  天命执行引擎 · 结果")
        print(f"{'='*50}")
        print(f"  任务: {args.task}")
        print(f"  成功: {'✅' if result.get('success') else '❌'}")
        if result.get("interrupted"):
            print(f"  ⏸️ 已中断: {result.get('interrupt_reason')}")
        print(f"  当前节点: {result.get('current_node')}")
        print(f"  执行路径: {' → '.join(result.get('node_history', []))}")
        if result.get("trace_summary"):
            print(f"\n{result['trace_summary']}")
        print(f"{'='*50}")
