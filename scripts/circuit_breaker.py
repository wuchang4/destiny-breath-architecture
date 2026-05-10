#!/usr/bin/env python3
"""
天命架构 — 电路断路器 (Circuit Breaker)
借鉴生产环境最佳实践的 Circuit Breaker 模式。

防止对挂掉的 API 持续发请求，避免级联故障。

状态机：
  CLOSED（正常） → 连续失败 ≥ threshold → OPEN（断开）
  OPEN（断开）   → 等待 timeout 秒     → HALF_OPEN（试探）
  HALF_OPEN（试探）→ 试探成功           → CLOSED（恢复正常）
                   → 试探失败           → OPEN（继续断开）

用法：
    from circuit_breaker import CircuitBreaker, CircuitState
    
    breaker = CircuitBreaker(failure_threshold=3, timeout=60)
    
    try:
        with breaker:
            result = call_api()
    except CircuitOpenError:
        result = fallback()

    # 或者用装饰器
    @breaker.protect
    def call_api():
        ...
"""

import time
import json
import os
from enum import Enum
from typing import Any, Callable, Dict, Optional


class CircuitState(Enum):
    CLOSED = "closed"       # 正常通行
    OPEN = "open"           # 断开，拒绝请求
    HALF_OPEN = "half_open" # 试探中


class CircuitOpenError(Exception):
    """断路器处于 OPEN 状态，请求被拒绝。"""
    def __init__(self, name: str, remaining_seconds: float):
        self.name = name
        self.remaining_seconds = remaining_seconds
        super().__init__(
            f"断路器 '{name}' 处于 OPEN 状态，"
            f"剩余 {remaining_seconds:.0f} 秒后可重试"
        )


class CircuitBreaker:
    """
    电路断路器。
    
    Args:
        name: 断路器名称（用于日志和持久化）
        failure_threshold: 连续失败多少次后打开断路器
        timeout: 断路器打开后等待多少秒进入半开状态
        on_state_change: 状态变化回调函数
    """

    STATE_FILE = os.path.expanduser("~/.clawdbot/circuit_breakers.json")

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 3,
        timeout: float = 60.0,
        on_state_change: Optional[Callable] = None,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.on_state_change = on_state_change

        # 运行时状态
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._success_count = 0

        # 从磁盘恢复状态
        self._load_state()

    @property
    def state(self) -> CircuitState:
        """获取当前状态（自动检查 OPEN → HALF_OPEN 转换）。"""
        if self._state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self._transition(CircuitState.HALF_OPEN)
        return self._state

    def record_success(self):
        """记录一次成功调用。"""
        self._failure_count = 0
        self._success_count += 1
        if self._state == CircuitState.HALF_OPEN:
            self._transition(CircuitState.CLOSED)
        self._save_state()

    def record_failure(self):
        """记录一次失败调用。"""
        self._failure_count += 1
        self._last_failure_time = time.time()
        self._success_count = 0

        if self._state == CircuitState.HALF_OPEN:
            # 半开状态下失败 → 重新打开
            self._transition(CircuitState.OPEN)
        elif self._failure_count >= self.failure_threshold:
            # 连续失败达到阈值 → 打开断路器
            self._transition(CircuitState.OPEN)

        self._save_state()

    def allow_request(self) -> bool:
        """检查当前是否允许请求通过。"""
        current_state = self.state  # 触发自动转换检查
        return current_state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def __enter__(self):
        """上下文管理器入口。"""
        if not self.allow_request():
            remaining = self.timeout - (time.time() - self._last_failure_time)
            raise CircuitOpenError(self.name, max(0, remaining))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口。"""
        if exc_type is None:
            self.record_success()
        else:
            self.record_failure()
        return False  # 不吞异常

    def protect(self, func: Callable) -> Callable:
        """装饰器：用断路器保护函数调用。"""
        def wrapper(*args, **kwargs):
            with self:
                try:
                    result = func(*args, **kwargs)
                    self.record_success()
                    return result
                except Exception:
                    self.record_failure()
                    raise
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    def _should_attempt_reset(self) -> bool:
        """检查是否已过足够时间尝试重置。"""
        if self._last_failure_time == 0:
            return False
        return (time.time() - self._last_failure_time) >= self.timeout

    def _transition(self, new_state: CircuitState):
        """执行状态转换。"""
        old_state = self._state
        self._state = new_state
        if self.on_state_change and old_state != new_state:
            self.on_state_change(self.name, old_state, new_state)

    def _save_state(self):
        """持久化断路器状态到磁盘。"""
        try:
            os.makedirs(os.path.dirname(self.STATE_FILE), exist_ok=True)
            all_states = {}
            if os.path.exists(self.STATE_FILE):
                with open(self.STATE_FILE, "r", encoding="utf-8") as f:
                    all_states = json.load(f)

            all_states[self.name] = {
                "state": self._state.value,
                "failure_count": self._failure_count,
                "last_failure_time": self._last_failure_time,
                "success_count": self._success_count,
                "updated_at": time.time(),
            }

            with open(self.STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(all_states, f, indent=2, ensure_ascii=False)
        except (OSError, PermissionError):
            pass

    def _load_state(self):
        """从磁盘恢复断路器状态。"""
        try:
            if os.path.exists(self.STATE_FILE):
                with open(self.STATE_FILE, "r", encoding="utf-8") as f:
                    all_states = json.load(f)
                saved = all_states.get(self.name)
                if saved:
                    self._state = CircuitState(saved.get("state", "closed"))
                    self._failure_count = saved.get("failure_count", 0)
                    self._last_failure_time = saved.get("last_failure_time", 0)
                    self._success_count = saved.get("success_count", 0)
        except (OSError, json.JSONDecodeError):
            pass

    def status(self) -> Dict[str, Any]:
        """返回断路器状态摘要。"""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "timeout": self.timeout,
            "success_count": self._success_count,
            "last_failure_time": self._last_failure_time,
        }

    def reset(self):
        """手动重置断路器到 CLOSED 状态。"""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0
        self._save_state()


class CircuitBreakerManager:
    """
    断路器管理器。为每个 API 端点维护独立的断路器。
    """

    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}

    def get_or_create(
        self,
        name: str,
        failure_threshold: int = 3,
        timeout: float = 60.0,
    ) -> CircuitBreaker:
        """获取或创建断路器。"""
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                timeout=timeout,
            )
        return self._breakers[name]

    def status_all(self) -> Dict[str, Dict]:
        """返回所有断路器的状态。"""
        return {name: b.status() for name, b in self._breakers.items()}

    def reset_all(self):
        """重置所有断路器。"""
        for b in self._breakers.values():
            b.reset()


# 全局断路器管理器实例
manager = CircuitBreakerManager()


# ── CLI ────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="天命电路断路器")
    parser.add_argument("--status", action="store_true", help="查看所有断路器状态")
    parser.add_argument("--reset", type=str, help="重置指定断路器")
    parser.add_argument("--test", action="store_true", help="运行演示")
    parser.add_argument("--json", action="store_true", help="JSON 输出")

    args = parser.parse_args()

    if args.status:
        if os.path.exists(CircuitBreaker.STATE_FILE):
            with open(CircuitBreaker.STATE_FILE, "r", encoding="utf-8") as f:
                states = json.load(f)
            if args.json:
                print(json.dumps(states, indent=2, ensure_ascii=False))
            else:
                for name, data in states.items():
                    state = data.get("state", "unknown")
                    fails = data.get("failure_count", 0)
                    icon = {"closed": "🟢", "open": "🔴", "half_open": "🟡"}.get(state, "❓")
                    print(f"  {icon} {name}: {state} (失败{fails}次)")
        else:
            print("  暂无断路器记录")

    elif args.reset:
        cb = manager.get_or_create(args.reset)
        cb.reset()
        print(f"  ✅ 断路器 '{args.reset}' 已重置为 CLOSED")

    elif args.test:
        print("=== 电路断路器演示 ===\n")

        cb = CircuitBreaker("demo-api", failure_threshold=3, timeout=5)

        # 正常调用
        print("  1. 正常调用 3 次:")
        for i in range(3):
            with cb:
                pass  # 模拟成功
            print(f"     调用 {i+1}: ✅ {cb.state.value}")

        # 连续失败
        print("\n  2. 连续失败 3 次:")
        for i in range(3):
            try:
                with cb:
                    raise ConnectionError("模拟失败")
            except ConnectionError:
                pass
            print(f"     失败 {i+1}: {cb.state.value}")

        # 断路器打开后拒绝请求
        print("\n  3. 断路器打开后:")
        try:
            with cb:
                pass
        except CircuitOpenError as e:
            print(f"     拒绝: {e}")

        # 等待超时后恢复
        print(f"\n  4. 等待 {cb.timeout} 秒后:")
        cb._last_failure_time = time.time() - cb.timeout - 1
        with cb:
            pass  # 半开状态下成功
        print(f"     恢复: ✅ {cb.state.value}")

    else:
        parser.print_help()
