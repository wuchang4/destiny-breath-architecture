#!/usr/bin/env python3
"""
天命架构 — 执行追踪器 v2 (Execution Tracer)
兼容 OpenTelemetry (OTEL) 格式，支持结构化 span/metrics/logs。

v2 升级（基于 2026 顶级框架调研）：
  - OTEL JSON 导出：可接入 Jaeger/Grafana/Tempo 等可视化工具
  - Metrics 支持：计数器/直方图/仪表盘，供心跳仪表盘使用
  - 结构化日志：每个 span 关联结构化日志事件
  - 保留 v1 的上下文管理器 API，完全向后兼容

用法：
    from execution_tracer import ExecutionTracer
    tracer = ExecutionTracer("task-abc")

    # span 追踪（与 v1 兼容）
    with tracer.span("中书省") as s:
        s.set_attribute("confidence", 0.8)
        s.add_event("intent_parsed", {"intent": "搜索信息"})

    # 指标记录（v2 新增）
    tracer.record_metric("task_duration_ms", 150, {"task_type": "search"})
    tracer.record_counter("tool_calls", 1, {"tool": "WebSearch"})

    # 导出
    tracer.export_otel_json("trace.json")     # OTEL 格式
    tracer.export_json("trace_legacy.json")    # 旧格式兼容
    tracer.export_metrics("metrics.json")      # 指标汇总

    # 心跳仪表盘集成
    from execution_tracer import HeartbeatDashboard
    dashboard = HeartbeatDashboard()
    dashboard.ingest(tracer)
    dashboard.export_diagnostics("diagnostics.json")
"""

import json
import os
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from destiny.version import __version__ as DESTINY_VERSION
except Exception:
    DESTINY_VERSION = "0.5.0"


# ── Span（兼容 v1 + OTEL 扩展）────────────────────────────

class Span:
    """
    执行 span。v2 扩展为 OTEL 兼容格式。

    OTEL Span 字段映射：
    - span_id → traceId/spanId
    - name → name
    - start_time/end_time → startTimeUnixNano/endTimeUnixNano
    - attributes → attributes (key-value pairs)
    - events → events (带时间戳的日志)
    - status → status.code (OK/ERROR)
    """

    def __init__(self, name: str, parent_id: Optional[str] = None, trace_id: Optional[str] = None):
        self.span_id = uuid.uuid4().hex[:16]
        self.trace_id = trace_id or uuid.uuid4().hex[:32]
        self.name = name
        self.parent_id = parent_id
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.status = "ok"  # "ok" | "error" | "interrupted"
        self.attributes: Dict[str, Any] = {}
        self.events: List[Dict[str, Any]] = []
        self._links: List[Dict] = []  # OTEL Links（关联其他 trace）

    def set_attribute(self, key: str, value: Any):
        self.attributes[key] = value

    def add_event(self, name: str, data: Optional[Dict] = None):
        self.events.append({
            "name": name,
            "timeUnixNano": int(time.time() * 1e9),
            "time": time.time(),
            "data": data or {},
        })

    def add_link(self, trace_id: str, span_id: str, attributes: Optional[Dict] = None):
        """OTEL Link：关联其他 trace 的 span。"""
        self._links.append({
            "traceId": trace_id,
            "spanId": span_id,
            "attributes": attributes or {},
        })

    def finish(self, status: str = "ok"):
        self.end_time = time.time()
        self.status = status

    @property
    def duration_ms(self) -> float:
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000

    def to_dict(self) -> Dict[str, Any]:
        """v1 兼容格式。"""
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

    def to_otel(self) -> Dict[str, Any]:
        """OTEL 兼容格式。"""
        otel_status = {"OK": 1, "error": 2, "interrupted": 0}.get(self.status, 0)
        return {
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "parentSpanId": self.parent_id or "",
            "name": self.name,
            "kind": "SPAN_KIND_INTERNAL",
            "startTimeUnixNano": int(self.start_time * 1e9),
            "endTimeUnixNano": int((self.end_time or time.time()) * 1e9),
            "attributes": [
                {"key": k, "value": self._otel_value(v)}
                for k, v in self.attributes.items()
            ],
            "events": [
                {
                    "name": e["name"],
                    "timeUnixNano": e["timeUnixNano"],
                    "attributes": [
                        {"key": k, "value": self._otel_value(v)}
                        for k, v in e.get("data", {}).items()
                    ],
                }
                for e in self.events
            ],
            "status": {"code": otel_status, "message": ""},
            "links": self._links,
        }

    @staticmethod
    def _otel_value(v: Any) -> Dict[str, Any]:
        """转换为 OTEL AnyValue 格式。"""
        if isinstance(v, bool):
            return {"boolValue": v}
        elif isinstance(v, int):
            return {"intValue": v}
        elif isinstance(v, float):
            return {"doubleValue": v}
        elif isinstance(v, list):
            return {"arrayValue": {"values": [Span._otel_value(x) for x in v]}}
        else:
            return {"stringValue": str(v)}


# ── Metric 类型 ────────────────────────────────────────────

class MetricType:
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


class Metric:
    """单个指标。"""

    def __init__(self, name: str, metric_type: str, description: str = "", unit: str = ""):
        self.name = name
        self.type = metric_type
        self.description = description
        self.unit = unit
        self.value: float = 0
        self.labels: Dict[str, str] = {}
        self._history: List[Tuple[float, float, Dict[str, str]]] = []  # (timestamp, value, labels)

    def record(self, value: float, labels: Optional[Dict[str, str]] = None):
        now = time.time()
        self.value = value
        self.labels = labels or {}
        self._history.append((now, value, self.labels))

    def increment(self, amount: float = 1, labels: Optional[Dict[str, str]] = None):
        self.value += amount
        self.labels = labels or {}
        self._history.append((time.time(), self.value, self.labels))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "unit": self.unit,
            "value": self.value,
            "labels": self.labels,
            "history_count": len(self._history),
        }

    def to_otel(self) -> Dict[str, Any]:
        """OTEL Metrics 格式。"""
        base = {
            "name": self.name,
            "description": self.description,
            "unit": self.unit,
        }
        if self.type == MetricType.COUNTER:
            base["sum"] = {
                "dataPoints": [{"asDouble": self.value, "startTimeUnixNano": int((self._history[0][0] if self._history else time.time()) * 1e9), "timeUnixNano": int(time.time() * 1e9)}],
                "aggregationTemporality": "AGGREGATION_TEMPORALITY_CUMULATIVE",
                "isMonotonic": True,
            }
        elif self.type == MetricType.GAUGE:
            base["gauge"] = {
                "dataPoints": [{"asDouble": self.value, "timeUnixNano": int(time.time() * 1e9)}],
            }
        elif self.type == MetricType.HISTOGRAM:
            values = [h[1] for h in self._history]
            base["histogram"] = {
                "dataPoints": [{
                    "count": len(values),
                    "sum": sum(values),
                    "min": min(values) if values else 0,
                    "max": max(values) if values else 0,
                }],
                "aggregationTemporality": "AGGREGATION_TEMPORALITY_CUMULATIVE",
            }
        return base


# ── 执行追踪器 v2 ─────────────────────────────────────────

class ExecutionTracer:
    """
    执行追踪器 v2。兼容 v1 API + OTEL 扩展。

    v2 新增：
    - export_otel_json(): OTEL 格式导出
    - record_metric(): 记录指标
    - record_counter(): 计数器递增
    - record_gauge(): 仪表盘值
    - export_metrics(): 指标汇总导出
    - get_summary_dict(): 结构化摘要（供心跳仪表盘）
    """

    def __init__(self, task_id: Optional[str] = None, service_name: str = "destiny-engine"):
        self.task_id = task_id or uuid.uuid4().hex[:12]
        self.service_name = service_name
        self.spans: List[Span] = []
        self.metrics: Dict[str, Metric] = {}
        self._current_span_id: Optional[str] = None
        self._current_trace_id: str = uuid.uuid4().hex[:32]
        self.start_time = time.time()
        self._structured_logs: List[Dict] = []

    @contextmanager
    def span(self, name: str):
        """上下文管理器，自动管理 span 的开始和结束。与 v1 完全兼容。"""
        s = Span(name, parent_id=self._current_span_id, trace_id=self._current_trace_id)
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

    # ── 指标记录 ──────────────────────────────────────────

    def record_metric(self, name: str, value: float, labels: Optional[Dict[str, str]] = None,
                      description: str = "", unit: str = ""):
        """记录一个指标值。自动创建 gauge 类型。"""
        if name not in self.metrics:
            self.metrics[name] = Metric(name, MetricType.GAUGE, description, unit)
        self.metrics[name].record(value, labels)

    def record_counter(self, name: str, amount: float = 1, labels: Optional[Dict[str, str]] = None,
                       description: str = ""):
        """计数器递增。"""
        if name not in self.metrics:
            self.metrics[name] = Metric(name, MetricType.COUNTER, description)
        self.metrics[name].increment(amount, labels)

    def record_histogram(self, name: str, value: float, labels: Optional[Dict[str, str]] = None,
                         description: str = "", unit: str = "ms"):
        """直方图记录（如延迟分布）。"""
        if name not in self.metrics:
            self.metrics[name] = Metric(name, MetricType.HISTOGRAM, description, unit)
        self.metrics[name].record(value, labels)

    # ── 结构化日志 ────────────────────────────────────────

    def log(self, level: str, message: str, data: Optional[Dict] = None):
        """记录结构化日志。"""
        entry = {
            "timestamp": time.time(),
            "timeISO": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": message,
            "trace_id": self._current_trace_id,
            "span_id": self._current_span_id,
            "data": data or {},
        }
        self._structured_logs.append(entry)

    # ── 导出：OTEL JSON ──────────────────────────────────

    def export_otel_json(self, path: str):
        """
        导出 OTEL 兼容的 JSON 格式。
        可直接导入 Jaeger/Tempo/Grafana 等工具。
        """
        otel = {
            "resourceSpans": [{
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": self.service_name}},
                        {"key": "service.version", "value": {"stringValue": DESTINY_VERSION}},
                        {"key": "task.id", "value": {"stringValue": self.task_id}},
                    ]
                },
                "scopeSpans": [{
                    "scope": {"name": "destiny-engine", "version": DESTINY_VERSION},
                    "spans": [s.to_otel() for s in self.spans],
                }],
            }],
            "resourceMetrics": [{
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": self.service_name}},
                    ]
                },
                "scopeMetrics": [{
                    "scope": {"name": "destiny-engine-metrics", "version": DESTINY_VERSION},
                    "metrics": [m.to_otel() for m in self.metrics.values()],
                }],
            }],
        }
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(otel, f, ensure_ascii=False, indent=2)

    # ── 导出：v1 兼容 JSON ───────────────────────────────

    def export_json(self, path: str):
        """v1 兼容格式导出。"""
        data = {
            "task_id": self.task_id,
            "start_time": self.start_time,
            "spans": [s.to_dict() for s in self.spans],
            "total_duration_ms": round(sum(s.duration_ms for s in self.spans), 2),
        }
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── 导出：指标汇总 ───────────────────────────────────

    def export_metrics(self, path: str):
        """导出指标汇总。"""
        data = {
            "task_id": self.task_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": {name: m.to_dict() for name, m in self.metrics.items()},
            "summary": self.get_summary_dict(),
        }
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── 结构化摘要（供心跳仪表盘）──────────────────────

    def get_summary_dict(self) -> Dict[str, Any]:
        """返回结构化摘要，供 Protocol 6 心跳仪表盘使用。"""
        total_ms = sum(s.duration_ms for s in self.spans)
        error_count = sum(1 for s in self.spans if s.status == "error")
        return {
            "task_id": self.task_id,
            "service": self.service_name,
            "span_count": len(self.spans),
            "error_count": error_count,
            "total_duration_ms": round(total_ms, 2),
            "metric_count": len(self.metrics),
            "log_count": len(self._structured_logs),
            "health": "healthy" if error_count == 0 else "degraded",
            "spans": [
                {
                    "name": s.name,
                    "duration_ms": round(s.duration_ms, 2),
                    "status": s.status,
                    "attribute_count": len(s.attributes),
                    "event_count": len(s.events),
                }
                for s in self.spans
            ],
            "metrics": {
                name: {"value": m.value, "type": m.type}
                for name, m in self.metrics.items()
            },
        }

    # ── 文本摘要（保留 v1）───────────────────────────────

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

        # 指标摘要
        if self.metrics:
            lines.append(f"\n  指标 ({len(self.metrics)} 个):")
            for name, m in self.metrics.items():
                lines.append(f"    {name} [{m.type}] = {m.value}")

        return "\n".join(lines)


# ── 心跳仪表盘（Protocol 6 集成）─────────────────────────

class HeartbeatDashboard:
    """
    心跳仪表盘。聚合多个 tracer 的数据，输出诊断摘要。
    供 Protocol 6 心跳调用。
    """

    def __init__(self, diagnostics_dir: Optional[str] = None):
        self.diagnostics_dir = diagnostics_dir or os.path.expanduser("~/.clawdbot/heartbeat")
        self._tracers: List[ExecutionTracer] = []
        self._snapshots: List[Dict] = []

    def ingest(self, tracer: ExecutionTracer):
        """注入一个 tracer 的数据。"""
        self._tracers.append(tracer)

    def generate_diagnostics(self) -> Dict[str, Any]:
        """生成诊断摘要。"""
        total_spans = sum(len(t.spans) for t in self._tracers)
        total_errors = sum(sum(1 for s in t.spans if s.status == "error") for t in self._tracers)
        total_duration = sum(sum(s.duration_ms for s in t.spans) for t in self._tracers)

        # 聚合指标
        aggregated_metrics: Dict[str, float] = defaultdict(float)
        for t in self._tracers:
            for name, m in t.metrics.items():
                aggregated_metrics[name] += m.value

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tracer_count": len(self._tracers),
            "total_spans": total_spans,
            "total_errors": total_errors,
            "total_duration_ms": round(total_duration, 2),
            "health": "healthy" if total_errors == 0 else "degraded",
            "aggregated_metrics": dict(aggregated_metrics),
            "tracer_summaries": [t.get_summary_dict() for t in self._tracers],
        }

    def export_diagnostics(self, path: Optional[str] = None):
        """导出诊断数据。"""
        path = path or os.path.join(self.diagnostics_dir, "diagnostics.json")
        data = self.generate_diagnostics()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path


# ── CLI ────────────────────────────────────────────────────
if __name__ == "__main__":
    print("执行追踪器 v2 — OTEL 兼容演示\n")

    tracer = ExecutionTracer("demo-v2")

    with tracer.span("中书省") as s:
        s.set_attribute("confidence", 0.8)
        s.add_event("intent_parsed", {"intent": "搜索信息"})
        tracer.log("INFO", "中书省解析完成", {"confidence": 0.8})
        time.sleep(0.01)

    with tracer.span("门下省‖尚书省 (并行)") as s:
        s.set_attribute("parallel", True)
        tracer.record_counter("parallel_groups", 1)
        time.sleep(0.005)

    with tracer.span("执行节点") as s:
        s.set_attribute("tools", ["WebSearch", "WebFetch"])
        tracer.record_metric("tool_count", 2, {"task_type": "search"})
        tracer.record_histogram("tool_latency_ms", 45.2, {"tool": "WebSearch"})
        time.sleep(0.005)

    # 记录指标
    tracer.record_metric("task_duration_ms", sum(sp.duration_ms for sp in tracer.spans))
    tracer.record_counter("tasks_completed", 1)

    # 文本摘要
    print(tracer.summary())

    # OTEL JSON 导出
    otel_path = os.path.expanduser("~/.clawdbot/traces/otel_demo.json")
    tracer.export_otel_json(otel_path)
    print(f"\nOTEL JSON 已导出: {otel_path}")

    # 指标导出
    metrics_path = os.path.expanduser("~/.clawdbot/traces/metrics_demo.json")
    tracer.export_metrics(metrics_path)
    print(f"指标已导出: {metrics_path}")

    # 心跳仪表盘
    dashboard = HeartbeatDashboard()
    dashboard.ingest(tracer)
    diag_path = dashboard.export_diagnostics()
    print(f"诊断摘要已导出: {diag_path}")

    diag = dashboard.generate_diagnostics()
    print(f"\n仪表盘诊断:")
    print(f"  健康状态: {diag['health']}")
    print(f"  总 Span: {diag['total_spans']}")
    print(f"  总错误: {diag['total_errors']}")
    print(f"  总耗时: {diag['total_duration_ms']:.1f}ms")
    print(f"  指标数: {len(diag['aggregated_metrics'])}")
