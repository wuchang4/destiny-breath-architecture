#!/usr/bin/env python3
"""
天命架构 — 三省图 State Graph v2 (Province Graph)
参考 langgraph 的 StateGraph + OpenTelemetry + Claude Agent SDK。

v2 新增（基于顶级框架调研升级）：
  - interrupt/resume 中断恢复机制（借鉴 LangGraph interrupt() 原语）
  - 执行追踪 span/trace 系统（借鉴 OpenTelemetry）
  - 原子检查点写入+恢复校验（借鉴 Claude Agent SDK Session 持久化）
  - 节点级错误处理 + 部分失败恢复（借鉴 Strands Agents 故障处理）

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
    graph.run()  # 自动运行到中断点或结束
    if graph.is_interrupted():
        # 处理中断（如等待用户确认）
        graph.resume({"user_confirmed": True})
"""

import json
import os
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, TypedDict


# ── 状态类型 ──────────────────────────────────────────────

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
    user_confirmed: bool        # 用户是否已确认（用于 interrupt/resume）


# ── 执行追踪 Span（借鉴 OpenTelemetry）───────────────────

class Span:
    """执行追踪 span，记录每个节点的执行细节。"""

    def __init__(self, name: str, parent: Optional["Span"] = None):
        self.span_id = uuid.uuid4().hex[:8]
        self.name = name
        self.parent = parent
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.status = "ok"  # "ok" | "error" | "interrupted"
        self.attributes: Dict[str, Any] = {}
        self.events: List[Dict[str, Any]] = []

    def set_attribute(self, key: str, value: Any):
        self.attributes[key] = value

    def add_event(self, name: str, data: Optional[Dict] = None):
        self.events.append({
            "name": name,
            "time": time.time(),
            "data": data or {},
        })

    def finish(self, status: str = "ok"):
        self.end_time = time.time()
        self.status = status

    @property
    def duration_ms(self) -> float:
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "span_id": self.span_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 2),
            "status": self.status,
            "attributes": self.attributes,
            "events": self.events,
            "parent": self.parent.span_id if self.parent else None,
        }


class TraceContext:
    """执行追踪上下文，管理整个图执行的 span 树。"""

    def __init__(self, trace_id: Optional[str] = None):
        self.trace_id = trace_id or uuid.uuid4().hex[:12]
        self.spans: List[Span] = []
        self._current_span: Optional[Span] = None

    def start_span(self, name: str) -> Span:
        span = Span(name, parent=self._current_span)
        self.spans.append(span)
        self._current_span = span
        return span

    def end_span(self, status: str = "ok"):
        if self._current_span:
            self._current_span.finish(status)
            self._current_span = self._current_span.parent

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "spans": [s.to_dict() for s in self.spans],
            "total_duration_ms": round(
                sum(s.duration_ms for s in self.spans), 2
            ),
        }

    def summary(self) -> str:
        lines = [f"Trace {self.trace_id}:"]
        for s in self.spans:
            indent = "  " if s.parent else ""
            icon = {"ok": "✅", "error": "❌", "interrupted": "⏸️"}.get(s.status, "?")
            lines.append(
                f"  {indent}{icon} {s.name} ({s.duration_ms:.1f}ms) [{s.status}]"
            )
        return "\n".join(lines)


# ── 图拓扑 ─────────────────────────────────────────────────

GRAPH_NODES = [
    "START", "中书省", "澄清分支", "门下省",
    "阻断/预警", "尚书省", "执行节点", "AAR/Checkpt", "END",
]

UNCONDITIONAL_EDGES = [
    ("START", "中书省"),
    ("澄清分支", "中书省"),
    ("尚书省", "执行节点"),
    ("执行节点", "AAR/Checkpt"),
    ("AAR/Checkpt", "END"),
]

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

# 中断点：这些节点执行前会暂停等待人工确认（借鉴 LangGraph interrupt()）
INTERRUPT_NODES = {"阻断/预警"}


class ProvinceGraph:
    """
    三省图状态机 v2。

    v2 新增能力（基于顶级框架调研）：
    - interrupt/resume: 在高风险节点自动中断，等待用户确认后恢复
    - execution_trace: OpenTelemetry 风格的 span/trace 执行追踪
    - atomic_checkpoint: 原子写入检查点，恢复时校验完整性
    - node_error_handling: 节点级错误捕获，部分失败可恢复
    """

    CHECKPOINT_DIR = os.path.expanduser("~/.clawdbot/checkpoints")

    def __init__(self, trace_id: Optional[str] = None):
        self.state: Dict[str, Any] = self._default_state()
        self.current_node: str = "START"
        self.node_history: List[str] = ["START"]
        self._interrupted: bool = False
        self._interrupt_reason: str = ""
        self._node_handlers: Dict[str, Callable] = {}
        self._trace = TraceContext(trace_id)

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
            "user_confirmed": False,
        }

    # ── 中断/恢复（借鉴 LangGraph interrupt() 原语）──────

    def is_interrupted(self) -> bool:
        """检查图是否处于中断状态。"""
        return self._interrupted

    def get_interrupt_reason(self) -> str:
        """获取中断原因。"""
        return self._interrupt_reason

    def resume(self, state_update: Optional[Dict[str, Any]] = None):
        """
        从中断点恢复执行。
        
        Args:
            state_update: 用户提供的更新（如 user_confirmed=True）
        """
        if not self._interrupted:
            return

        if state_update:
            self.state.update(state_update)

        self._interrupted = False
        self._interrupt_reason = ""

        # 继续执行
        span = self._trace.start_span(f"resume@{self.current_node}")
        span.add_event("resumed", {"user_confirmed": self.state.get("user_confirmed", False)})
        self._trace.end_span("ok")

    # ── 节点处理器注册 ────────────────────────────────────

    def register_handler(self, node_name: str, handler: Callable):
        """
        为指定节点注册处理函数。
        
        handler 签名: fn(state: dict, span: Span) -> dict
        返回值会合并到 state 中。
        """
        self._node_handlers[node_name] = handler

    # ── 核心执行 ──────────────────────────────────────────

    def step(self, state_update: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """执行一步：从当前节点移动到下一个节点。"""
        if self.is_finished() or self._interrupted:
            return self.state

        # 合并状态更新
        if state_update:
            self.state.update(state_update)

        # 找下一个节点
        next_node = self._find_next_node()

        # 中断检查（借鉴 LangGraph interrupt()）
        if next_node in INTERRUPT_NODES and not self.state.get("user_confirmed", False):
            span = self._trace.start_span(f"interrupt@{next_node}")
            span.set_attribute("interrupt_reason", f"高风险操作需要用户确认: {next_node}")
            span.add_event("interrupted")
            self._interrupted = True
            self._interrupt_reason = f"即将进入 {next_node}，需要用户确认后继续"
            self.current_node = next_node
            self.node_history.append(next_node)
            self._trace.end_span("interrupted")
            self._save_checkpoint()
            return self.state

        # 执行节点处理器（如果有）
        span = self._trace.start_span(f"execute@{next_node}")
        self.current_node = next_node
        self.node_history.append(next_node)

        handler = self._node_handlers.get(next_node)
        if handler:
            try:
                handler_result = handler(self.state, span)
                if handler_result:
                    self.state.update(handler_result)
            except Exception as e:
                span.set_attribute("error", str(e))
                span.add_event("error", {"message": str(e)})
                self.state["errors"].append(f"{next_node}: {e}")
                self._trace.end_span("error")
                return self.state

        self._trace.end_span("ok")

        # 每步写检查点（借鉴 LangGraph Checkpointer）
        self._save_checkpoint()

        return self.state

    def run(self, max_steps: int = 20) -> Dict[str, Any]:
        """
        自动运行图到结束或中断。
        
        Args:
            max_steps: 最大步数（防止无限循环）
            
        Returns:
            最终状态
        """
        for _ in range(max_steps):
            if self.is_finished() or self._interrupted:
                break
            self.step()
        return self.state

    def _find_next_node(self) -> str:
        """查找当前节点的下一个节点。"""
        for edge in UNCONDITIONAL_EDGES:
            if edge[0] == self.current_node:
                return edge[1]
        for edge in CONDITIONAL_EDGES:
            if edge["from"] == self.current_node:
                if edge["condition"](self.state):
                    return edge["true"]
                else:
                    return edge["false"]
        return "END"

    # ── 检查点（借鉴 Claude Agent SDK Session 持久化）─────

    def _save_checkpoint(self):
        """原子写入检查点。先写临时文件再重命名，防止写入中断导致文件损坏。"""
        checkpoint = self.serialize()
        os.makedirs(self.CHECKPOINT_DIR, exist_ok=True)
        checkpoint_path = os.path.join(self.CHECKPOINT_DIR, "province_graph.json")
        tmp_path = checkpoint_path + ".tmp"

        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(checkpoint, f, ensure_ascii=False, indent=2)
            # 原子重命名
            if os.path.exists(checkpoint_path):
                os.replace(tmp_path, checkpoint_path)
            else:
                os.rename(tmp_path, checkpoint_path)
        except (OSError, PermissionError) as e:
            print(f"[ProvinceGraph] 检查点写入失败: {e}")

    @classmethod
    def load_checkpoint(cls, checkpoint_dir: Optional[str] = None) -> Optional["ProvinceGraph"]:
        """
        从检查点恢复图。
        
        借鉴 Claude Agent SDK 的 Session 恢复机制：
        - 读取检查点文件
        - 校验 schema 完整性
        - 恢复图状态和执行追踪
        """
        cdir = checkpoint_dir or cls.CHECKPOINT_DIR
        checkpoint_path = os.path.join(cdir, "province_graph.json")

        try:
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"[ProvinceGraph] 检查点恢复失败: {e}")
            return None

        # 校验 schema
        required_keys = {"current_node", "state", "node_history"}
        if not required_keys.issubset(data.keys()):
            print(f"[ProvinceGraph] 检查点 schema 不完整，缺少: {required_keys - data.keys()}")
            return None

        graph = cls()
        graph.current_node = data["current_node"]
        graph.state = data.get("state", cls._default_state())
        graph.node_history = data.get("node_history", ["START"])
        graph._interrupted = data.get("interrupted", False)
        graph._interrupt_reason = data.get("interrupt_reason", "")
        return graph

    # ── 状态查询 ──────────────────────────────────────────

    def is_finished(self) -> bool:
        return self.current_node == "END"

    def reset(self):
        """重置图到初始状态。"""
        self.state = self._default_state()
        self.current_node = "START"
        self.node_history = ["START"]
        self._interrupted = False
        self._interrupt_reason = ""
        self._trace = TraceContext()

    def serialize(self) -> Dict[str, Any]:
        """序列化为可检查点保存的字典。"""
        return {
            "version": 2,
            "current_node": self.current_node,
            "state": self.state,
            "node_history": self.node_history,
            "interrupted": self._interrupted,
            "interrupt_reason": self._interrupt_reason,
            "trace": self._trace.to_dict(),
            "saved_at": time.time(),
        }

    @classmethod
    def deserialize(cls, data: Dict[str, Any]) -> "ProvinceGraph":
        """从字典恢复图。"""
        graph = cls()
        graph.current_node = data.get("current_node", "START")
        graph.state = data.get("state", cls._default_state())
        graph.node_history = data.get("node_history", ["START"])
        graph._interrupted = data.get("interrupted", False)
        graph._interrupt_reason = data.get("interrupt_reason", "")
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
            f"执行路径: {' → '.join(self.node_history)}",
            f"中断状态: {'⏸️ 已中断 - ' + self._interrupt_reason if self._interrupted else '✅ 运行中'}",
            f"状态:",
            f"  意图: {self.state.get('user_intent', '(空)')}",
            f"  置信度: {self.state.get('confidence', 0)}",
            f"  风险等级: {self.state.get('risk_level', 'low')}",
            f"  选中工具: {self.state.get('selected_tools', [])}",
            f"  错误: {self.state.get('errors', [])}",
        ]
        transitions = self.get_available_transitions()
        if transitions:
            lines.append("  可用跳转:")
            for t in transitions:
                lines.append(f"    {t}")

        # 追踪摘要
        lines.append(f"\n{self._trace.summary()}")
        return "\n".join(lines)

    @property
    def trace(self) -> TraceContext:
        return self._trace


# ── CLI 入口 ───────────────────────────────────────────────
if __name__ == "__main__":
    print("天命三省图 State Graph v2 — 演示\n")

    # === 正常流程 ===
    print("=== 正常流程 ===")
    graph = ProvinceGraph()
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
    print(f"\n{graph.trace.summary()}")

    # === 中断/恢复流程（v2 新增）===
    print("\n=== 中断/恢复流程 ===")
    graph2 = ProvinceGraph()
    graph2.step()  # START → 中书省
    graph2.step({"confidence": 0.9})  # 中书省 → 门下省
    graph2.step({"risk_level": "high"})  # 门下省 → 阻断/预警（应中断）

    if graph2.is_interrupted():
        print(f"  ⏸️ 图已中断: {graph2.get_interrupt_reason()}")
        print(f"  当前节点: {graph2.current_node}")

        # 模拟用户确认后恢复
        print("  用户确认...")
        graph2.resume({"user_confirmed": True})
        graph2.step()  # 继续执行
        print(f"  恢复后节点: {graph2.current_node}")

    print(f"\n{graph2.trace.summary()}")

    # === 低置信度流程 ===
    print("\n=== 低置信度路径 ===")
    graph3 = ProvinceGraph()
    graph3.step()
    graph3.step({"confidence": 0.3})
    print(f"  当前节点: {graph3.current_node} (需要澄清)")
    graph3.step()
    print(f"  当前节点: {graph3.current_node} (重新解析)")

    # === 检查点恢复演示 ===
    print("\n=== 检查点恢复 ===")
    print(f"  检查点已自动保存到: {graph.CHECKPOINT_DIR}/province_graph.json")
    recovered = ProvinceGraph.load_checkpoint()
    if recovered:
        print(f"  恢复成功: 当前节点={recovered.current_node}, 中断={recovered.is_interrupted()}")
    else:
        print("  恢复检查点（上一次运行的最新状态）")

    print(f"\n{graph3.trace.summary()}")
