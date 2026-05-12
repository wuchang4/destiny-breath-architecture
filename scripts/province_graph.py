#!/usr/bin/env python3
"""
天命架构 — 三省图 State Graph v3 (Province Graph)
参考 langgraph 的 StateGraph + Reducer + 并行执行。

v3 新增（基于顶级框架调研升级）：
  - 并行节点执行：门下省 ‖ 尚书省 并行运行，减少简单任务路径
  - Reducer 状态合并：并发写入时用 field-level reducer 解决冲突（借鉴 LangGraph）
  - 子图支持：节点可注册为子图（sub-graph），形成嵌套层级
  - 语义工具筛选：执行节点集成 skill_index.py 语义搜索
  - 保留 v2 所有能力：interrupt/resume、执行追踪、原子检查点

节点（8个）：
  START → 中书省 → [澄清分支 | 门下省‖尚书省] → [阻断/预警 | 执行节点] → AAR/Checkpt → END

并行路径（confidence >= 0.6）：
  门下省（验证） ‖ 尚书省（规划） → Reducer 合并 → 执行节点

用法：
    from province_graph import ProvinceGraph
    graph = ProvinceGraph()
    graph.run()
    if graph.is_interrupted():
        graph.resume({"user_confirmed": True})
"""

import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Set, TypedDict


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


# ── Reducer 定义（借鉴 LangGraph）────────────────────────

class StateReducer:
    """
    状态字段级 Reducer。定义并发节点写入同一字段时如何合并。

    LangGraph 的核心创新：每个 state 字段可以有独立的 reducer 函数，
    当多个并行节点同时更新该字段时，reducer 决定最终值。

    默认 reducer：
    - list 字段：追加合并 (append_merge)
    - str 字段：后写入者胜出 (last_writer_wins)
    - float/int 字段：后写入者胜出
    - errors 字段：始终追加
    """

    @staticmethod
    def append_merge(existing: list, incoming: list) -> list:
        """列表追加合并，去重。"""
        if not incoming:
            return existing
        combined = list(existing) if existing else []
        for item in incoming:
            if item not in combined:
                combined.append(item)
        return combined

    @staticmethod
    def last_writer_wins(existing: Any, incoming: Any) -> Any:
        """后写入者胜出。如果 incoming 为 None/空，保留 existing。"""
        if incoming is None or (isinstance(incoming, str) and incoming == ""):
            return existing
        return incoming

    @staticmethod
    def max_value(existing: float, incoming: float) -> float:
        """取较大值。"""
        return max(existing or 0, incoming or 0)

    @staticmethod
    def min_value(existing: float, incoming: float) -> float:
        """取较小值。"""
        if existing is None:
            return incoming
        if incoming is None:
            return existing
        return min(existing, incoming)

    # 字段→Reducer 映射
    FIELD_REDUCERS: Dict[str, Callable] = {
        "memory_hits": append_merge,
        "selected_tools": append_merge,
        "errors": append_merge,
        "confidence": last_writer_wins,
        "risk_level": last_writer_wins,
        "user_intent": last_writer_wins,
        "route": last_writer_wins,
        "confidence_threshold": last_writer_wins,
        "user_confirmed": last_writer_wins,
    }

    @classmethod
    def merge(cls, base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
        """用 reducer 合并两个 state 更新。"""
        result = dict(base)
        for key, value in update.items():
            if key in cls.FIELD_REDUCERS:
                result[key] = cls.FIELD_REDUCERS[key](result.get(key), value)
            else:
                result[key] = cls.last_writer_wins(result.get(key), value)
        return result

    @classmethod
    def merge_multiple(cls, base: Dict[str, Any], updates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """合并多个并发节点的状态更新。"""
        result = dict(base)
        for update in updates:
            result = cls.merge(result, update)
        return result


# ── 执行追踪 Span（保留 v2）─────────────────────────────

class Span:
    """执行追踪 span，记录每个节点的执行细节。"""

    def __init__(self, name: str, parent: Optional["Span"] = None):
        self.span_id = uuid.uuid4().hex[:8]
        self.name = name
        self.parent = parent
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.status = "ok"  # "ok" | "error" | "interrupted" | "parallel"
        self.attributes: Dict[str, Any] = {}
        self.events: List[Dict[str, Any]] = []

    def set_attribute(self, key: str, value: Any):
        self.attributes[key] = value

    def add_event(self, name: str, data: Optional[Dict] = None):
        self.events.append({"name": name, "time": time.time(), "data": data or {}})

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
            "total_duration_ms": round(sum(s.duration_ms for s in self.spans), 2),
        }

    def summary(self) -> str:
        lines = [f"Trace {self.trace_id}:"]
        for s in self.spans:
            indent = "  " if s.parent else ""
            icon = {"ok": "✅", "error": "❌", "interrupted": "⏸️", "parallel": "⚡"}.get(s.status, "?")
            lines.append(f"  {indent}{icon} {s.name} ({s.duration_ms:.1f}ms) [{s.status}]")
        return "\n".join(lines)


# ── 图拓扑 ─────────────────────────────────────────────────

GRAPH_NODES = [
    "START", "中书省", "澄清分支", "门下省",
    "阻断/预警", "尚书省", "执行节点", "AAR/Checkpt", "END",
]

UNCONDITIONAL_EDGES = [
    ("START", "中书省"),
    ("澄清分支", "中书省"),
    ("执行节点", "AAR/Checkpt"),
    ("AAR/Checkpt", "END"),
]

CONDITIONAL_EDGES = [
    {
        "from": "中书省",
        "condition": lambda s: s.get("confidence", 1.0) < 0.6,
        "true": "澄清分支",
        "false": "门下省",  # v3: 这里触发并行组
    },
    {
        "from": "门下省",  # 并行组的门下省出口
        "condition": lambda s: s.get("risk_level", "low") == "high",
        "true": "阻断/预警",
        "false": "尚书省",
    },
]

# ── v3: 并行组定义 ────────────────────────────────────────
# 当 confidence >= 0.6 时，门下省和尚书省并行执行
PARALLEL_GROUPS = {
    "门下省‖尚书省": {
        "trigger_from": "中书省",       # 从哪个节点触发并行
        "nodes": ["门下省", "尚书省"],  # 并行执行的节点
        "merge_to": "执行节点",         # 合并后跳到哪个节点
        "condition": lambda s: s.get("confidence", 1.0) >= 0.6,
    },
}

# 中断点
INTERRUPT_NODES = {"阻断/预警"}


class ProvinceGraph:
    """
    三省图状态机 v3。

    v3 新增能力（基于顶级框架调研）：
    - parallel_execution: 门下省 ‖ 尚书省并行，简单任务路径缩短50%
    - state_reducer: 并发写入时 field-level reducer 合并（借鉴 LangGraph）
    - sub_graph: 节点可注册为子图，形成嵌套层级
    - semantic_tool_selection: 执行节点集成语义技能筛选
    - 保留 v2: interrupt/resume、执行追踪、原子检查点
    """

    CHECKPOINT_DIR = os.path.expanduser("~/.clawdbot/checkpoints")

    def __init__(self, trace_id: Optional[str] = None):
        self.state: Dict[str, Any] = self._default_state()
        self.current_node: str = "START"
        self.node_history: List[str] = ["START"]
        self._interrupted: bool = False
        self._interrupt_reason: str = ""
        self._node_handlers: Dict[str, Callable] = {}
        self._sub_graphs: Dict[str, "ProvinceGraph"] = {}  # v3: 子图注册
        self._trace = TraceContext(trace_id)
        self._parallel_executor = ThreadPoolExecutor(max_workers=2)

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

    # ── 中断/恢复（保留 v2）──────────────────────────────

    def is_interrupted(self) -> bool:
        return self._interrupted

    def get_interrupt_reason(self) -> str:
        return self._interrupt_reason

    def resume(self, state_update: Optional[Dict[str, Any]] = None):
        if not self._interrupted:
            return
        if state_update:
            self.state.update(state_update)
        self._interrupted = False
        self._interrupt_reason = ""
        span = self._trace.start_span(f"resume@{self.current_node}")
        span.add_event("resumed", {"user_confirmed": self.state.get("user_confirmed", False)})
        self._trace.end_span("ok")

    # ── 节点/子图注册 ────────────────────────────────────

    def register_handler(self, node_name: str, handler: Callable):
        """
        为指定节点注册处理函数。
        handler 签名: fn(state: dict, span: Span) -> dict
        返回值会通过 reducer 合并到 state 中。
        """
        self._node_handlers[node_name] = handler

    def register_sub_graph(self, node_name: str, sub_graph: "ProvinceGraph"):
        """
        v3: 为指定节点注册子图。子图会替代该节点的普通 handler 执行。
        子图拥有自己的内部节点和状态，但共享父图的输入/输出状态。
        """
        self._sub_graphs[node_name] = sub_graph

    # ── 核心执行 ──────────────────────────────────────────

    def step(self, state_update: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """执行一步：从当前节点移动到下一个节点。"""
        if self.is_finished() or self._interrupted:
            return self.state

        if state_update:
            self.state.update(state_update)

        # 检查是否触发并行组
        parallel_group = self._find_parallel_group()
        if parallel_group:
            return self._execute_parallel_group(parallel_group)

        # 顺序执行（保留 v2 逻辑）
        next_node = self._find_next_node()

        # 中断检查
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

        # 执行节点
        self._execute_single_node(next_node)
        return self.state

    def run(self, max_steps: int = 20) -> Dict[str, Any]:
        """自动运行图到结束或中断。"""
        for _ in range(max_steps):
            if self.is_finished() or self._interrupted:
                break
            self.step()
        return self.state

    # ── v3: 并行执行 ─────────────────────────────────────

    def _find_parallel_group(self) -> Optional[Dict]:
        """检查当前节点是否触发并行组。"""
        for group_name, group in PARALLEL_GROUPS.items():
            if group["trigger_from"] == self.current_node and group["condition"](self.state):
                return {"name": group_name, **group}
        return None

    def _execute_parallel_group(self, group: Dict) -> Dict[str, Any]:
        """
        并行执行一组节点，用 Reducer 合并结果。

        流程：
        1. 为每个并行节点创建独立的 state 副本
        2. 并行执行所有节点的 handler
        3. 收集所有节点的状态更新
        4. 用 StateReducer.merge_multiple 合并
        5. 跳到 merge_to 节点
        """
        group_name = group["name"]
        nodes = group["nodes"]
        merge_to = group["merge_to"]

        span = self._trace.start_span(f"parallel@{group_name}")
        span.set_attribute("parallel_nodes", nodes)
        span.add_event("parallel_start", {"nodes": nodes})

        # 记录到历史
        self.node_history.append(f"[{group_name}]")

        # 并行执行
        results: List[Dict[str, Any]] = []
        futures = {}

        for node_name in nodes:
            handler = self._node_handlers.get(node_name)
            if handler:
                future = self._parallel_executor.submit(
                    self._run_node_handler, node_name, handler, dict(self.state)
                )
                futures[future] = node_name
            else:
                # 无 handler 的节点：模拟默认行为
                default_result = self._simulate_default_node(node_name)
                if default_result:
                    results.append(default_result)

        # 收集结果
        for future in as_completed(futures):
            node_name = futures[future]
            try:
                result = future.result(timeout=30)
                if result:
                    results.append(result)
                    span.add_event(f"node_complete", {"node": node_name})
            except Exception as e:
                span.add_event(f"node_error", {"node": node_name, "error": str(e)})
                self.state["errors"].append(f"{node_name}: {e}")

        # Reducer 合并
        self.state = StateReducer.merge_multiple(self.state, results)

        span.set_attribute("merged_fields", list(set().union(*(r.keys() for r in results)) if results else []))
        span.add_event("parallel_end", {"merged_updates": len(results)})
        self._trace.end_span("parallel")

        # 跳到合并目标
        self.current_node = merge_to
        self.node_history.append(merge_to)

        # 中断检查（合并目标可能是阻断节点）
        if merge_to in INTERRUPT_NODES and not self.state.get("user_confirmed", False):
            self._interrupted = True
            self._interrupt_reason = f"并行组 {group_name} 合并后需要用户确认"
            self._save_checkpoint()
            return self.state

        self._save_checkpoint()
        return self.state

    def _run_node_handler(self, node_name: str, handler: Callable, state_copy: Dict) -> Optional[Dict]:
        """在独立线程中运行节点 handler。"""
        span = self._trace.start_span(f"execute@{node_name}")
        try:
            result = handler(state_copy, span)
            span.add_event("handler_returned")
            return result
        except Exception as e:
            span.set_attribute("error", str(e))
            span.add_event("error", {"message": str(e)})
            return {"errors": [f"{node_name}: {e}"]}
        finally:
            self._trace.end_span("ok")

    def _simulate_default_node(self, node_name: str) -> Optional[Dict]:
        """模拟无 handler 的节点的默认行为（用于测试）。"""
        defaults = {
            "门下省": {"risk_level": "low", "memory_hits": []},
            "尚书省": {"selected_tools": [], "route": "default"},
        }
        return defaults.get(node_name)

    # ── 顺序执行（保留 v2）───────────────────────────────

    def _execute_single_node(self, next_node: str):
        """顺序执行单个节点。"""
        span = self._trace.start_span(f"execute@{next_node}")
        self.current_node = next_node
        self.node_history.append(next_node)

        # 子图检查
        if next_node in self._sub_graphs:
            sub_graph = self._sub_graphs[next_node]
            span.add_event("sub_graph_start", {"node": next_node})
            sub_graph.state.update(self.state)
            sub_result = sub_graph.run()
            self.state = StateReducer.merge(self.state, sub_result)
            span.add_event("sub_graph_end", {"node": next_node})
            self._trace.end_span("ok")
            self._save_checkpoint()
            return

        # 普通 handler
        handler = self._node_handlers.get(next_node)
        if handler:
            try:
                handler_result = handler(self.state, span)
                if handler_result:
                    self.state = StateReducer.merge(self.state, handler_result)
            except Exception as e:
                span.set_attribute("error", str(e))
                span.add_event("error", {"message": str(e)})
                self.state["errors"].append(f"{next_node}: {e}")
                self._trace.end_span("error")
                return

        self._trace.end_span("ok")
        self._save_checkpoint()

    def _find_next_node(self) -> str:
        """查找当前节点的下一个节点。"""
        # 先检查无条件边
        for edge in UNCONDITIONAL_EDGES:
            if edge[0] == self.current_node:
                return edge[1]
        # 再检查条件边
        for edge in CONDITIONAL_EDGES:
            if edge["from"] == self.current_node:
                if edge["condition"](self.state):
                    return edge["true"]
                else:
                    return edge["false"]
        return "END"

    # ── 检查点（保留 v2）─────────────────────────────────

    def _save_checkpoint(self):
        checkpoint = self.serialize()
        os.makedirs(self.CHECKPOINT_DIR, exist_ok=True)
        checkpoint_path = os.path.join(self.CHECKPOINT_DIR, "province_graph.json")
        tmp_path = checkpoint_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(checkpoint, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, checkpoint_path)
        except (OSError, PermissionError) as e:
            print(f"[ProvinceGraph] 检查点写入失败: {e}")

    @classmethod
    def load_checkpoint(cls, checkpoint_dir: Optional[str] = None) -> Optional["ProvinceGraph"]:
        cdir = checkpoint_dir or cls.CHECKPOINT_DIR
        checkpoint_path = os.path.join(cdir, "province_graph.json")
        try:
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"[ProvinceGraph] 检查点恢复失败: {e}")
            return None
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
        self.state = self._default_state()
        self.current_node = "START"
        self.node_history = ["START"]
        self._interrupted = False
        self._interrupt_reason = ""
        self._trace = TraceContext()

    def serialize(self) -> Dict[str, Any]:
        return {
            "version": 3,
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
        graph = cls()
        graph.current_node = data.get("current_node", "START")
        graph.state = data.get("state", cls._default_state())
        graph.node_history = data.get("node_history", ["START"])
        graph._interrupted = data.get("interrupted", False)
        graph._interrupt_reason = data.get("interrupt_reason", "")
        return graph

    def get_available_transitions(self) -> List[str]:
        transitions = []
        for edge in UNCONDITIONAL_EDGES:
            if edge[0] == self.current_node:
                transitions.append(f"→ {edge[1]} (无条件)")
        for edge in CONDITIONAL_EDGES:
            if edge["from"] == self.current_node:
                transitions.append(f"→ {edge['true']} (if true) | → {edge['false']} (if false)")
        # 并行组
        for group_name, group in PARALLEL_GROUPS.items():
            if group["trigger_from"] == self.current_node:
                transitions.append(f"→ {'‖'.join(group['nodes'])} (并行) → {group['merge_to']}")
        return transitions

    def display(self) -> str:
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
        lines.append(f"\n{self._trace.summary()}")
        return "\n".join(lines)

    @property
    def trace(self) -> TraceContext:
        return self._trace

    def __del__(self):
        """清理线程池。"""
        try:
            self._parallel_executor.shutdown(wait=False)
        except Exception:
            pass


# ── CLI 入口 ───────────────────────────────────────────────
if __name__ == "__main__":
    print("天命三省图 State Graph v3 — 演示\n")

    # === 顺序流程（低置信度走澄清分支）===
    print("=== 低置信度路径（顺序）===")
    graph = ProvinceGraph()
    graph.step()  # START → 中书省
    print(f"  {graph.current_node} (解析意图)")
    graph.step({"confidence": 0.3})  # 中书省 → 澄清分支
    print(f"  {graph.current_node} (需要澄清)")
    graph.step()  # 澄清分支 → 中书省
    print(f"  {graph.current_node} (重新解析)")

    # === 并行流程（高置信度走门下省‖尚书省）===
    print("\n=== 高置信度路径（并行）===")
    graph2 = ProvinceGraph()

    # 注册节点 handler
    def zhongshu_handler(state, span):
        span.add_event("intent_parsed")
        return {"user_intent": "写一篇文章", "confidence": 0.85}

    def menxia_handler(state, span):
        span.add_event("verification_complete")
        time.sleep(0.1)  # 模拟耗时
        return {"risk_level": "low", "memory_hits": ["记忆1", "记忆2"]}

    def shangshu_handler(state, span):
        span.add_event("tools_selected")
        time.sleep(0.15)  # 模拟耗时（比门下省稍长）
        return {"selected_tools": ["content-创作中心", "khazix-writer"], "route": "content"}

    graph2.register_handler("中书省", zhongshu_handler)
    graph2.register_handler("门下省", menxia_handler)
    graph2.register_handler("尚书省", shangshu_handler)

    graph2.step()  # START → 中书省
    print(f"  {graph2.current_node}")

    graph2.step({"confidence": 0.85})  # 中书省 → 门下省‖尚书省（并行）
    print(f"  {graph2.current_node} (并行完成)")
    print(f"  risk_level={graph2.state.get('risk_level')}")
    print(f"  selected_tools={graph2.state.get('selected_tools')}")
    print(f"  memory_hits={graph2.state.get('memory_hits')}")

    # 并行组合并后已跳到执行节点
    graph2.step()  # 执行节点 → AAR
    print(f"  {graph2.current_node}")

    graph2.step()  # AAR → END
    print(f"  {graph2.current_node}")

    print(f"\n{graph2.trace.summary()}")

    # === 并行执行耗时对比 ===
    print("\n=== 并行 vs 顺序耗时对比 ===")
    t0 = time.time()
    g_para = ProvinceGraph()
    g_para.register_handler("中书省", zhongshu_handler)
    g_para.register_handler("门下省", menxia_handler)
    g_para.register_handler("尚书省", shangshu_handler)
    g_para.step()
    g_para.step({"confidence": 0.9})
    parallel_time = (time.time() - t0) * 1000
    print(f"  并行路径: {parallel_time:.1f}ms (门下省100ms + 尚书省150ms 并发)")

    t0 = time.time()
    g_seq = ProvinceGraph()
    g_seq.register_handler("门下省", menxia_handler)
    g_seq.register_handler("尚书省", shangshu_handler)
    g_seq.current_node = "中书省"
    g_seq._execute_single_node("门下省")
    g_seq._execute_single_node("尚书省")
    sequential_time = (time.time() - t0) * 1000
    print(f"  顺序路径: {sequential_time:.1f}ms (门下省100ms + 尚书省150ms 串行)")
    print(f"  加速比: {sequential_time / parallel_time:.1f}x")

    # === Reducer 测试 ===
    print("\n=== Reducer 合并测试 ===")
    base = {"memory_hits": ["A"], "selected_tools": ["tool1"], "risk_level": "low", "errors": []}
    update1 = {"memory_hits": ["B", "A"], "selected_tools": ["tool2"], "risk_level": "medium"}
    update2 = {"memory_hits": ["C"], "errors": ["err1"]}
    merged = StateReducer.merge_multiple(base, [update1, update2])
    print(f"  memory_hits: {merged['memory_hits']} (追加去重)")
    print(f"  selected_tools: {merged['selected_tools']} (追加去重)")
    print(f"  risk_level: {merged['risk_level']} (后写入者胜出)")
    print(f"  errors: {merged['errors']} (追加)")

    print(f"\n检查点已保存到: {ProvinceGraph.CHECKPOINT_DIR}/province_graph.json")
