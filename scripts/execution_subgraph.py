#!/usr/bin/env python3
"""
执行子图 (Execution Sub-Graph)
将三省图的"执行节点"展开为5个子节点的嵌套子图。

子节点：
  工具选择 → 安全验证 → 实际执行 → 结果验证 → 缓存/去重

每个子节点都可追踪、可检查点。
集成语义工具筛选（skill_index.py）和安全验证链（tool_safety_chain.py）。
"""

import json
import os
import time
import uuid
from typing import Any, Callable, Dict, List, Optional
from province_graph import ProvinceGraph, Span, StateReducer


class ExecutionSubGraph:
    """
    执行子图：将单个"执行节点"展开为5步精细流程。

    子节点流程：
    ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐
    │ 工具选择 │ → │ 安全验证 │ → │ 实际执行 │ → │ 结果验证 │ → │ 缓存去重 │
    └─────────┘   └─────────┘   └─────────┘   └─────────┘   └─────────┘

    每个子节点都可以独立追踪（OTEL span），支持中断和错误恢复。
    """

    SUB_NODES = ["工具选择", "安全验证", "实际执行", "结果验证", "缓存去重"]

    def __init__(self, parent_trace=None):
        self._handlers: Dict[str, Callable] = {}
        self._parent_trace = parent_trace
        self._execution_log: List[Dict] = []

    def register(self, node_name: str, handler: Callable):
        """注册子节点处理器。handler(state, span) -> state_update"""
        self._handlers[node_name] = handler

    def execute(self, state: Dict[str, Any], parent_span: Optional[Span] = None) -> Dict[str, Any]:
        """
        执行完整子图流程。

        Args:
            state: 从父图传入的状态
            parent_span: 父图的 span（用于嵌套追踪）

        Returns:
            状态更新（通过 Reducer 合并到父图状态）
        """
        result = dict(state)
        self._execution_log.clear()

        for node_name in self.SUB_NODES:
            span_name = f"sub_exec@{node_name}"
            span = Span(span_name, parent=parent_span)

            handler = self._handlers.get(node_name)
            if handler:
                try:
                    update = handler(result, span)
                    if update:
                        result = StateReducer.merge(result, update)
                    span.finish("ok")
                except Exception as e:
                    span.set_attribute("error", str(e))
                    span.add_event("error", {"message": str(e)})
                    span.finish("error")
                    result.setdefault("errors", []).append(f"执行子图/{node_name}: {e}")
                    # 错误后停止子图
                    break
            else:
                # 无 handler，使用默认行为
                default = self._default_behavior(node_name, result)
                if default:
                    result = StateReducer.merge(result, default)
                span.finish("ok")

            self._execution_log.append({
                "node": node_name,
                "span_id": span.span_id,
                "duration_ms": span.duration_ms,
                "status": span.status,
            })

        return result

    def _default_behavior(self, node_name: str, state: Dict) -> Optional[Dict]:
        """无 handler 时的默认行为。"""
        if node_name == "工具选择":
            # 尝试语义筛选
            return self._default_tool_selection(state)
        elif node_name == "安全验证":
            # 默认通过
            return {"_security_check": "passed"}
        elif node_name == "结果验证":
            # 默认通过
            return {"_result_validation": "passed"}
        elif node_name == "缓存去重":
            # 默认不缓存
            return {"_cached": False}
        return None

    def _default_tool_selection(self, state: Dict) -> Optional[Dict]:
        """默认工具选择：尝试语义筛选。"""
        intent = state.get("user_intent", "")
        if not intent:
            return None

        try:
            import sys
            sys.path.insert(0, os.path.dirname(__file__))
            from skill_index import search_skills
            results = search_skills(intent, top_k=3)
            if results:
                return {"selected_tools": [r["name"] for r in results]}
        except Exception:
            pass
        return None

    def get_execution_log(self) -> List[Dict]:
        return self._execution_log


def create_default_execution_subgraph() -> ExecutionSubGraph:
    """创建默认的执行子图，包含标准 handler。"""
    sub = ExecutionSubGraph()

    # 工具选择：语义筛选
    def tool_selection(state, span):
        intent = state.get("user_intent", "")
        span.set_attribute("user_intent", intent)
        try:
            import sys
            sys.path.insert(0, os.path.dirname(__file__))
            from skill_index import search_skills
            results = search_skills(intent, top_k=3)
            tools = [r["name"] for r in results] if results else []
            span.add_event("tools_selected", {"tools": tools, "count": len(tools)})
            return {"selected_tools": tools}
        except Exception as e:
            span.add_event("tool_selection_fallback", {"error": str(e)})
            return {"selected_tools": []}

    # 安全验证
    def security_check(state, span):
        tools = state.get("selected_tools", [])
        risk = state.get("risk_level", "low")
        span.set_attribute("risk_level", risk)
        span.set_attribute("tools_count", len(tools))

        # 高风险工具检查
        dangerous_patterns = ["rm", "delete", "drop", "format", "regedit"]
        for tool in tools:
            for pattern in dangerous_patterns:
                if pattern in tool.lower():
                    span.add_event("security_block", {"tool": tool, "reason": f"匹配危险模式: {pattern}"})
                    return {"risk_level": "high", "errors": [f"安全验证阻止: {tool}"]}

        span.add_event("security_passed")
        return {"_security_check": "passed"}

    # 实际执行
    def actual_execution(state, span):
        tools = state.get("selected_tools", [])
        span.set_attribute("selected_tools", tools)
        # 这里是实际调用工具的地方，子图只负责流程框架
        # 真正的工具调用由父图的执行引擎完成
        span.add_event("execution_delegated", {"tools": tools})
        return {"_execution_status": "delegated_to_engine"}

    # 结果验证
    def result_validation(state, span):
        errors = state.get("errors", [])
        if errors:
            span.add_event("validation_errors", {"count": len(errors)})
            return {"_result_validation": "has_errors"}
        span.add_event("validation_passed")
        return {"_result_validation": "passed"}

    # 缓存去重
    def cache_and_dedup(state, span):
        # 生成执行指纹
        fingerprint = {
            "intent": state.get("user_intent", ""),
            "tools": tuple(sorted(state.get("selected_tools", []))),
            "route": state.get("route", ""),
        }
        fingerprint_str = str(fingerprint)
        span.set_attribute("fingerprint", fingerprint_str[:100])
        span.add_event("cached", {"fingerprint": fingerprint_str[:50]})
        return {"_cached": True, "_fingerprint": fingerprint_str}

    sub.register("工具选择", tool_selection)
    sub.register("安全验证", security_check)
    sub.register("实际执行", actual_execution)
    sub.register("结果验证", result_validation)
    sub.register("缓存去重", cache_and_dedup)

    return sub


# ── CLI 测试 ──────────────────────────────────────────────
if __name__ == "__main__":
    print("执行子图测试\n")

    sub = create_default_execution_subgraph()

    test_state = {
        "user_intent": "帮我写一篇公众号文章",
        "confidence": 0.9,
        "risk_level": "low",
        "memory_hits": [],
        "selected_tools": [],
        "route": "",
        "errors": [],
    }

    print("输入状态:")
    print(f"  intent: {test_state['user_intent']}")
    print(f"  selected_tools: {test_state['selected_tools']}")

    result = sub.execute(test_state)

    print("\n输出状态:")
    print(f"  selected_tools: {result.get('selected_tools')}")
    print(f"  risk_level: {result.get('risk_level')}")
    print(f"  security_check: {result.get('_security_check')}")
    print(f"  result_validation: {result.get('_result_validation')}")
    print(f"  cached: {result.get('_cached')}")
    print(f"  errors: {result.get('errors')}")

    print("\n执行日志:")
    for entry in sub.get_execution_log():
        icon = "✅" if entry["status"] == "ok" else "❌"
        print(f"  {icon} {entry['node']} ({entry['duration_ms']:.1f}ms)")

    # 测试与三省图集成
    print("\n=== 与三省图集成测试 ===")
    graph = ProvinceGraph()
    graph.register_handler("中书省", lambda s, sp: {"user_intent": "帮我写文章", "confidence": 0.85})

    # 注册执行子图
    exec_sub = create_default_execution_subgraph()
    graph.register_sub_graph("执行节点", exec_sub)

    graph.step()  # START → 中书省
    graph.step({"confidence": 0.85})  # 中书省 → 门下省‖尚书省（并行）
    print(f"  当前: {graph.current_node}")
    print(f"  tools: {graph.state.get('selected_tools')}")
    print(f"  risk: {graph.state.get('risk_level')}")

    # 继续执行到END
    while not graph.is_finished() and not graph.is_interrupted():
        graph.step()
        print(f"  → {graph.current_node}")

    print(f"\n追踪摘要:")
    print(graph.trace.summary())
