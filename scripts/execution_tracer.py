#!/usr/bin/env python3
"""
天命架构 — 执行追踪器 (Execution Tracer)
借鉴 OpenTelemetry 的 span/trace 模型。

为所有天命组件提供统一的执行追踪能力：
- 三省图每个节点的执行时间
- 工具调用的延迟和结果
- 模型路由的降级事件
- 安全验证链的各层耗时

用法：
    from execution_tracer import ExecutionTracer
    tracer = ExecutionTracer("task-abc")
    with tracer.span("中书省") as s:
        s.set_attribute("confidence", 0.8)
        # 执行逻辑...
    tracer.export_json("trace.json")
    print(tracer.summary())
"""

import json
import os
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, List, Optional


class Span:
    """单个执行 span。"""

    def __init__(self, name: str, parent_id: Optional[str] = None):
        self.span_id = uuid.uuid4().hex[:8]
        self.name = name
        self.parent_id = parent_id
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.status = "ok"
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
            "parent_id": self.parent_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 2),
            "status": self.status,
            "attributes": self.attributes,
            "events": self.events,
        }


class ExecutionTracer:
    """
    执行追踪器。管理 span 树，支持导出和摘要。
    """

    def __init__(self, task_id: Optional[str] = None):
        self.task_id = task_id or uuid.uuid4().hex[:12]
        self.spans: List[Span] = []
        self._current_span_id: Optional[str] = None
        self.start_time = time.time()

    @contextmanager
    def span(self, name: str):
        """上下文管理器，自动管理 span 的开始和结束。"""
        s = Span(name, parent_id=self._current_span_id)
        self.spans.append(s)
        prev = self._current_span_id
        self._current_span_id = s.span_id
        try:
            yield s
            s.finish("ok")
        except Exception as e:
            s.set_attribute("error", str(e))
            s.add_event("exception", {"type": type(e).__name__, "message": str(e)})
            s.finish("error")
            raise
        finally:
            self._current_span_id = prev

    def summary(self) -> str:
        lines = [f"Trace {self.task_id} ({len(self.spans)} spans):"]
        for s in self.spans:
            indent = "  " if s.parent_id else ""
            icon = {"ok": "✅", "error": "❌", "interrupted": "⏸️"}.get(s.status, "?")
            attrs = ""
            if s.attributes:
                parts = [f"{k}={v}" for k, v in list(s.attributes.items())[:3]]
                attrs = f" [{', '.join(parts)}]"
            lines.append(f"  {indent}{icon} {s.name} ({s.duration_ms:.1f}ms){attrs}")
        total = sum(s.duration_ms for s in self.spans)
        lines.append(f"  总耗时: {total:.1f}ms")
        return "\n".join(lines)

    def export_json(self, path: str):
        data = {
            "task_id": self.task_id,
            "start_time": self.start_time,
            "spans": [s.to_dict() for s in self.spans],
            "total_duration_ms": round(sum(s.duration_ms for s in self.spans), 2),
        }
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# ── CLI ────────────────────────────────────────────────────
if __name__ == "__main__":
    tracer = ExecutionTracer("demo")

    with tracer.span("中书省") as s:
        s.set_attribute("confidence", 0.8)
        s.add_event("intent_parsed", {"intent": "搜索信息"})
        time.sleep(0.01)

    with tracer.span("门下省") as s:
        s.set_attribute("risk_level", "low")
        time.sleep(0.005)

    with tracer.span("尚书省") as s:
        s.set_attribute("selected_tools", ["WebSearch", "WebFetch"])
        time.sleep(0.005)

    print(tracer.summary())
