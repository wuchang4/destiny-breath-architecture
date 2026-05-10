#!/usr/bin/env python3
"""
天命架构 — 三省图 State Graph (Province Graph)
参考 langgraph 的 StateGraph 架构设计。

节点（8个）：
  START → 中书省 → [澄清分支 | 门下省] → [阻断/预警 | 尚书省] → 执行节点 → AAR/Checkpt → END

条件边：
  中书省 → 澄清分支     (confidence < 0.6)
  中书省 → 门下省       (confidence >= 0.6)
  门下省 → 阻断/预警    (risk_level == "high")
  门下省 → 尚书省       (risk_level in ["low", "medium"])

用法：
    from province_graph import ProvinceGraph
    graph = ProvinceGraph()
    state = graph.step()  # START → 中书省
    state["confidence"] = 0.8
    state = graph.step(state)  # 中书省 → 门下省
    ...
"""

from typing import Any, Dict, List, Optional, TypedDict


class GraphState(TypedDict, total=False):
    """三省图状态。在节点间传递。"""
    user_intent: str            # 用户原始指令
    confidence: float           # 意图理解置信度 (0.0-1.0)
    risk_level: str             # "low" | "medium" | "high"
    memory_hits: list[str]      # 命中的记忆记录
    selected_tools: list[str]   # 选中的工具
    route: str                  # 路由路径
    errors: list[str]           # 错误收集
    confidence_threshold: float # 置信度阈值


# ── 图拓扑 ─────────────────────────────────────────────────

GRAPH_NODES = [
    "START", "中书省", "澄清分支", "门下省",
    "阻断/预警", "尚书省", "执行节点", "AAR/Checkpt", "END",
]

# 无条件边：(from, to)
UNCONDITIONAL_EDGES = [
    ("START", "中书省"),
    ("澄清分支", "中书省"),      # 澄清后回到中书省重新解析
    ("尚书省", "执行节点"),
    ("执行节点", "AAR/Checkpt"),
    ("AAR/Checkpt", "END"),
]

# 条件边：(from, condition_fn, to_if_true, to_if_false)
CONDITIONAL_EDGES = [
    {
        "from": "中书省",
        "condition": lambda s: s.get("confidence", 1.0) < 0.6,
        "true": "澄清分支",
        "false": "门下省",
    },
    {
        "from": "门下省",
        "condition": lambda s: s.get("risk_level", "low") == "high",
        "true": "阻断/预警",
        "false": "尚书省",
    },
]


class ProvinceGraph:
    """
    三省图状态机管理。
    
    参考 langgraph 的 StateGraph，实现带条件分支的有向图。
    支持：
    - 节点间状态传递
    - 条件分支（confidence < 0.6 → 澄清，risk == high → 阻断）
    - 重置和恢复
    - 状态序列化（用于检查点）
    """

    def __init__(self):
        self.state: Dict[str, Any] = self._default_state()
        self.current_node: str = "START"
        self.execution_trace: List[str] = ["START"]

    @staticmethod
    def _default_state() -> Dict[str, Any]:
        return {
            "user_intent": "",
            "confidence": 1.0,
            "risk_level": "low",
            "memory_hits": [],
            "selected_tools": [],
            "route": "",
            "errors": [],
            "confidence_threshold": 0.6,
        }

    def step(self, state_update: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        执行一步：从当前节点移动到下一个节点。
        
        Args:
            state_update: 要合并到状态中的更新（通常是上一个节点的输出）
            
        Returns:
            更新后的完整状态
        """
        if self.is_finished():
            return self.state

        # 合并状态更新
        if state_update:
            self.state.update(state_update)

        # 找下一个节点
        next_node = self._find_next_node()

        self.current_node = next_node
        self.execution_trace.append(next_node)
        return self.state

    def _find_next_node(self) -> str:
        """查找当前节点的下一个节点。"""
        # 1. 检查无条件边
        for edge in UNCONDITIONAL_EDGES:
            if edge[0] == self.current_node:
                return edge[1]

        # 2. 检查条件边
        for edge in CONDITIONAL_EDGES:
            if edge["from"] == self.current_node:
                if edge["condition"](self.state):
                    return edge["true"]
                else:
                    return edge["false"]

        # 3. 无法移动 → END
        return "END"

    def is_finished(self) -> bool:
        return self.current_node == "END"

    def reset(self):
        """重置图到初始状态。"""
        self.state = self._default_state()
        self.current_node = "START"
        self.execution_trace = ["START"]

    def serialize(self) -> Dict[str, Any]:
        """序列化为可检查点保存的字典。"""
        return {
            "current_node": self.current_node,
            "state": self.state,
            "execution_trace": self.execution_trace,
        }

    @classmethod
    def deserialize(cls, data: Dict[str, Any]) -> "ProvinceGraph":
        """从检查点恢复图。"""
        graph = cls()
        graph.current_node = data.get("current_node", "START")
        graph.state = data.get("state", cls._default_state())
        graph.execution_trace = data.get("execution_trace", ["START"])
        return graph

    def get_available_transitions(self) -> List[str]:
        """获取当前节点可用的下一跳。"""
        transitions = []
        for edge in UNCONDITIONAL_EDGES:
            if edge[0] == self.current_node:
                transitions.append(f"→ {edge[1]} (无条件)")
        for edge in CONDITIONAL_EDGES:
            if edge["from"] == self.current_node:
                transitions.append(
                    f"→ {edge['true']} (if true) | → {edge['false']} (if false)"
                )
        return transitions

    def display(self) -> str:
        """显示当前图状态。"""
        lines = [
            f"当前节点: {self.current_node}",
            f"执行路径: {' → '.join(self.execution_trace)}",
            f"状态:",
            f"  意图: {self.state.get('user_intent', '(空)')}",
            f"  置信度: {self.state.get('confidence', 0)}",
            f"  风险等级: {self.state.get('risk_level', 'low')}",
            f"  选中工具: {self.state.get('selected_tools', [])}",
        ]
        transitions = self.get_available_transitions()
        if transitions:
            lines.append("  可用跳转:")
            for t in transitions:
                lines.append(f"    {t}")
        return "\n".join(lines)


# ── CLI 入口 ───────────────────────────────────────────────
if __name__ == "__main__":
    print("天命三省图 State Graph — 演示\n")

    graph = ProvinceGraph()

    # 模拟完整执行流程
    print("=== 正常流程 ===")
    graph.step()  # START → 中书省
    print(f"  {graph.current_node} (解析意图)")

    graph.step({"confidence": 0.8})  # 中书省 → 门下省
    print(f"  {graph.current_node} (验证合规)")

    graph.step({"risk_level": "low"})  # 门下省 → 尚书省
    print(f"  {graph.current_node} (规划工具)")

    graph.step()  # 尚书省 → 执行节点
    print(f"  {graph.current_node} (执行任务)")

    graph.step()  # 执行节点 → AAR
    print(f"  {graph.current_node} (复盘)")

    graph.step()  # AAR → END
    print(f"  {graph.current_node}")

    print(f"\n执行路径: {' → '.join(graph.execution_trace)}")
    print(f"是否结束: {graph.is_finished()}")

    # 演示低置信度路径
    print("\n=== 低置信度路径 ===")
    graph2 = ProvinceGraph()
    graph2.step()  # START → 中书省
    graph2.step({"confidence": 0.3})  # 中书省 → 澄清分支
    print(f"  当前节点: {graph2.current_node} (需要澄清)")
    graph2.step()  # 澄清分支 → 中书省
    print(f"  当前节点: {graph2.current_node} (重新解析)")

    # 演示高风险路径
    print("\n=== 高风险路径 ===")
    graph3 = ProvinceGraph()
    graph3.step()
    graph3.step({"confidence": 0.9})
    graph3.step({"risk_level": "high"})
    print(f"  当前节点: {graph3.current_node} (已阻断)")
