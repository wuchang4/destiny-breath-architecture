#!/usr/bin/env python3
"""
天命架构 — 模型路由层 (Model Router)
借鉴 Claw Code 的 Provider 抽象和模型别名系统。

功能：
1. 模型别名映射（fast/smart/multimodal/coding → 实际模型ID）
2. 任务类型自动选模型
3. 可用性降级（API不可用 → 本地模型兜底）
4. 配置文件读取（从 models.json 读取可用模型列表）

用法：
    from model_router import ModelRouter
    router = ModelRouter()
    model = router.auto_select(task_type="image_analysis")
    # → "mimo-v2.5"
"""

import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

# 导入电路断路器（如果存在）
try:
    from circuit_breaker import CircuitBreaker, CircuitOpenError, manager as cb_manager
    HAS_CIRCUIT_BREAKER = True
except ImportError:
    HAS_CIRCUIT_BREAKER = False


class ModelRouter:
    """统一模型路由层。参考 Claw Code 的 Provider 抽象 + 模型别名系统。
    集成电路断路器：API 连续失败后自动断开，避免级联故障。"""

    # ── 别名表 ─────────────────────────────────────────────
    ALIASES = {
        "fast":       "gemma4:e4b",
        "smart":      "deepseek-v4-flash",
        "multimodal": "mimo-v2.5",
        "coding":     "mimo-v2.5-pro",
        "local":      "gemma4:e4b",
    }

    # ── 任务类型 → 推荐别名 ─────────────────────────────────
    TASK_MODEL_MAP = {
        "simple_qa":       "fast",
        "code_generation": "smart",
        "code_review":     "smart",
        "image_analysis":  "multimodal",
        "audio_analysis":  "multimodal",
        "video_analysis":  "multimodal",
        "long_running":    "coding",
        "complex_reasoning": "coding",
        "default":         "smart",
    }

    # ── 降级链 ─────────────────────────────────────────────
    FALLBACK_CHAIN = {
        "deepseek-v4-flash": ["mimo-v2.5-pro", "gemma4:e4b"],
        "mimo-v2.5":         ["deepseek-v4-flash", "gemma4:e4b"],
        "mimo-v2.5-pro":     ["deepseek-v4-flash", "gemma4:e4b"],
        "gemma4:e4b":        [],  # 已是本地模型，无降级
    }

    def __init__(self, models_json_path: Optional[str] = None):
        """
        初始化路由层。
        
        Args:
            models_json_path: models.json 文件路径，默认 ~/.workbuddy/models.json
        """
        self.config_path = models_json_path or os.path.expanduser(
            "~/.workbuddy/models.json"
        )
        self.available_models = self._load_models()

        # 初始化断路器
        if HAS_CIRCUIT_BREAKER:
            self._breakers = cb_manager

    def _load_models(self) -> dict:
        """从 models.json 加载可用模型列表。"""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                models_list = json.load(f)
            return {m["id"]: m for m in models_list}
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"[ModelRouter] 警告: 无法加载 {self.config_path}: {e}", file=sys.stderr)
            return {}

    def resolve(self, model_spec: str) -> str:
        """
        解析模型别名或直接返回模型ID。
        
        Args:
            model_spec: 别名（如 "fast"）或模型ID（如 "gemma4:e4b"）
            
        Returns:
            实际模型ID
        """
        return self.ALIASES.get(model_spec, model_spec)

    def auto_select(self, task_type: str = "default") -> str:
        """
        根据任务类型自动选择最佳模型。
        
        Args:
            task_type: 任务类型（simple_qa/code_generation/image_analysis 等）
            
        Returns:
            推荐的模型ID
        """
        alias = self.TASK_MODEL_MAP.get(task_type, self.TASK_MODEL_MAP["default"])
        return self.resolve(alias)

    def check_availability(self, model_id: str, timeout: float = 5.0) -> bool:
        """
        检查模型 API 是否可达（带断路器保护）。
        
        检测策略（按优先级）：
        1. 先检查断路器状态（如果 OPEN，直接返回 False）
        2. 对于本地模型（gemma4:e4b），检查 Ollama 服务
        3. 对于支持 /v1/models 端点的远程API，查询模型列表验证
        4. 降级到简单 HTTP HEAD 检查
        5. 失败时记录到断路器
        
        Args:
            model_id: 模型ID
            timeout: 超时秒数
            
        Returns:
            是否可用
        """
        # 断路器检查
        if HAS_CIRCUIT_BREAKER:
            breaker = self._breakers.get_or_create(f"model:{model_id}")
            if not breaker.allow_request():
                return False

        model_info = self.available_models.get(model_id)
        if not model_info:
            return False

        url = model_info.get("url", "")

        # 本地模型 → 检查 Ollama
        if "localhost" in url or "127.0.0.1" in url:
            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=timeout):
                    if HAS_CIRCUIT_BREAKER:
                        breaker.record_success()
                    return True
            except (urllib.error.URLError, OSError):
                if HAS_CIRCUIT_BREAKER:
                    breaker.record_failure()
                return False

        # 远程模型 → 尝试 /v1/models 端点
        try:
            base_url = url.split("/v1")[0] if "/v1" in url else url
            models_url = f"{base_url}/v1/models"
            api_key = model_info.get("apiKey", "")
            req = urllib.request.Request(models_url, method="GET")
            if api_key:
                req.add_header("Authorization", f"Bearer {api_key}")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                available_ids = [
                    m.get("id", "") for m in data.get("data", [])
                ]
                if available_ids and model_id in available_ids:
                    if HAS_CIRCUIT_BREAKER:
                        breaker.record_success()
                    return True
                if available_ids:
                    if HAS_CIRCUIT_BREAKER:
                        breaker.record_failure()
                    return False
                if HAS_CIRCUIT_BREAKER:
                    breaker.record_success()
                return True
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            if HAS_CIRCUIT_BREAKER:
                breaker.record_failure()

        # 最后降级：简单 HEAD 检查
        try:
            base_url = url.split("/v1")[0] if "/v1" in url else url
            req = urllib.request.Request(base_url, method="HEAD")
            with urllib.request.urlopen(req, timeout=timeout):
                if HAS_CIRCUIT_BREAKER:
                    breaker.record_success()
                return True
        except (urllib.error.URLError, OSError):
            if HAS_CIRCUIT_BREAKER:
                breaker.record_failure()
            return True

    def select_with_fallback(
        self, 
        preferred: Optional[str] = None, 
        task_type: str = "default"
    ) -> str:
        """
        选择模型，带自动降级。
        
        流程：
        1. 如果指定了 preferred → 用它
        2. 否则根据 task_type 自动选择
        3. 检查可用性，不可用则沿降级链降级
        4. 所有都不可用 → 返回本地 gemma4:e4b
        
        Args:
            preferred: 用户指定的模型（优先级最高）
            task_type: 任务类型
            
        Returns:
            最终选择的模型ID
        """
        # 1. 用户指定优先
        if preferred:
            primary = self.resolve(preferred)
        else:
            primary = self.auto_select(task_type)

        # 2. 检查主模型
        if self.check_availability(primary):
            return primary

        # 3. 沿降级链降级
        fallbacks = self.FALLBACK_CHAIN.get(primary, ["gemma4:e4b"])
        for fallback in fallbacks:
            if self.check_availability(fallback):
                print(
                    f"[ModelRouter] {primary} 不可用，降级到 {fallback}",
                    file=sys.stderr,
                )
                return fallback

        # 4. 兜底
        print(
            f"[ModelRouter] 所有模型不可用，返回本地兜底 gemma4:e4b",
            file=sys.stderr,
        )
        return "gemma4:e4b"

    def get_model_info(self, model_id: str) -> Optional[dict]:
        """获取模型详细信息。"""
        resolved = self.resolve(model_id)
        return self.available_models.get(resolved)

    def list_aliases(self) -> dict:
        """列出所有别名映射。"""
        return dict(self.ALIASES)

    def list_available(self) -> list:
        """列出所有已配置的模型ID。"""
        return list(self.available_models.keys())


# ── CLI 入口 ───────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="天命模型路由层")
    parser.add_argument("--list", action="store_true", help="列出所有可用模型")
    parser.add_argument("--aliases", action="store_true", help="列出别名映射")
    parser.add_argument("--select", type=str, help="根据任务类型选择模型")
    parser.add_argument("--check", type=str, help="检查模型可用性")
    parser.add_argument("--resolve", type=str, help="解析别名到模型ID")
    parser.add_argument("--auto", action="store_true", help="自动选择（带降级）")
    parser.add_argument("--task", type=str, default="default", help="任务类型")
    parser.add_argument(
        "--models-json", type=str, help="models.json 路径"
    )

    args = parser.parse_args()
    router = ModelRouter(args.models_json)

    if args.list:
        print("可用模型:")
        for mid in router.list_available():
            info = router.get_model_info(mid)
            imgs = "✅ 图片" if info and info.get("supportsImages") else "❌ 图片"
            print(f"  {mid:25s} {imgs}")
    elif args.aliases:
        print("别名映射:")
        for alias, model in router.list_aliases().items():
            print(f"  {alias:15s} → {model}")
    elif args.select:
        model = router.auto_select(args.select)
        print(f"任务类型 '{args.select}' → 模型: {model}")
    elif args.check:
        available = router.check_availability(args.check)
        print(f"{args.check}: {'✅ 可用' if available else '❌ 不可用'}")
    elif args.resolve:
        print(f"{args.resolve} → {router.resolve(args.resolve)}")
    elif args.auto:
        model = router.select_with_fallback(task_type=args.task)
        print(f"最终选择: {model}")
    else:
        parser.print_help()
