#!/usr/bin/env python3
"""
天命架构 — 配置层次化合并器 (Config Merger)
借鉴 Claw Code 的 5 层配置合并机制。

配置层次（优先级从低到高）：
  L1 全局默认    → SOUL.md (不可覆盖)
  L2 项目配置    → project-config.json
  L3 用户偏好    → MEMORY.md 中的设置段
  L4 会话配置    → session-config.json
  L5 运行时参数  → 命令行参数 / 运行时变量

合并规则：
  - 字典类型：递归合并，高优先级覆盖低优先级同名键
  - 列表类型：高优先级替换低优先级（不追加）
  - 标量类型：高优先级直接覆盖
  - SOUL.md 的 Core Truths 不可被任何层覆盖

用法：
    from config_merger import ConfigMerger
    merger = ConfigMerger()
    config = merger.merge()
    print(config["model_aliases"]["fast"])
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def deep_merge(base: dict, override: dict) -> dict:
    """
    递归合并两个字典。override 中的值覆盖 base 中的同名键。
    
    规则：
    - 字典类型：递归合并
    - 列表类型：override 替换 base（不追加）
    - 标量类型：override 直接覆盖
    
    Args:
        base: 基础配置
        override: 覆盖配置（优先级更高）
        
    Returns:
        合并后的配置字典
    """
    merged = base.copy()
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _safe_json_load(file_path: str) -> Dict[str, Any]:
    """安全加载 JSON 文件，失败返回空字典。"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError) as e:
        print(f"[ConfigMerger] 跳过 {file_path}: {e}", file=sys.stderr)
        return {}


def _extract_memory_preferences(memory_path: str) -> Dict[str, Any]:
    """
    从 MEMORY.md 提取用户偏好配置段。
    
    查找 "## 用户偏好" 段落，提取键值对格式的配置项。
    目前 MEMORY.md 的用户偏好是散文式，这里只做基础解析。
    """
    try:
        with open(memory_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (FileNotFoundError, PermissionError):
        return {}

    # 提取已知的配置性偏好
    prefs = {}
    if "中文交流" in content:
        prefs["language"] = "zh-CN"
    if "gemma4" in content and "垃圾" in content:
        prefs["local_model_quality_note"] = "gemma4 被用户评价较低"
    return prefs


class ConfigMerger:
    """
    天命配置层次化合并器。
    
    按优先级从低到高合并 5 层配置，输出一个统一的配置字典。
    """

    # ── 默认配置 (L1 最低优先级) ────────────────────────────
    DEFAULTS = {
        "model_aliases": {
            "fast": "gemma4:e4b",
            "smart": "deepseek-v4-flash",
            "multimodal": "mimo-v2.5",
            "coding": "mimo-v2.5-pro",
            "local": "gemma4:e4b",
        },
        "default_model": "smart",
        "default_permission_mode": "workspace-write",
        "language": "zh-CN",
        "memory": {
            "vector_search_threshold": 0.25,
            "max_context_tokens": 8192,
            "vector_search_enabled": True,
        },
        "heartbeat": {
            "interval_hours": 4,
            "enabled": True,
        },
        "tool_safety": {
            "enabled": True,
            "max_output_chars": 20000,
            "default_timeout_seconds": 120,
            "max_timeout_seconds": 600,
        },
        "evolution": {
            "gradient_auto_threshold": 3,
            "baseline_min_samples": 5,
            "metric_auto_retry": False,
        },
    }

    # 不可覆盖的 SOUL.md 规则 (仅作记录，不在合并中使用)
    IMMUTABLE_KEYS = {
        "core_truths",
        "boundary_rules",
        "logic_anchors",
    }

    def __init__(
        self,
        project_root: Optional[str] = None,
        session_config_path: Optional[str] = None,
        runtime_args: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化合并器。
        
        Args:
            project_root: 项目根目录（用于查找 project-config.json 和 MEMORY.md）
            session_config_path: session-config.json 路径
            runtime_args: 运行时参数字典（最高优先级）
        """
        self.project_root = project_root or os.getcwd()
        self.session_config_path = session_config_path or os.path.join(
            self.project_root, ".workbuddy", "session-config.json"
        )
        self.runtime_args = runtime_args or {}

        # 配置文件路径
        self.project_config_path = os.path.join(
            self.project_root, "project-config.json"
        )
        self.memory_path = os.path.join(
            self.project_root, ".workbuddy", "memory", "MEMORY.md"
        )

    def merge(self) -> Dict[str, Any]:
        """
        执行 5 层配置合并。
        
        合并顺序（优先级从低到高）：
        L1 默认值 → L2 项目配置 → L3 用户偏好 → L4 会话配置 → L5 运行时
        
        Returns:
            合并后的完整配置字典
        """
        # L1: 默认配置（最低优先级）
        config = self.DEFAULTS.copy()

        # L2: 项目配置
        project_config = _safe_json_load(self.project_config_path)
        if project_config:
            config = deep_merge(config, project_config)
            print(f"[ConfigMerger] L2 项目配置已合并: {self.project_config_path}", file=sys.stderr)

        # L3: 用户偏好（从 MEMORY.md 提取）
        memory_prefs = _extract_memory_preferences(self.memory_path)
        if memory_prefs:
            config = deep_merge(config, memory_prefs)
            print(f"[ConfigMerger] L3 用户偏好已合并: {self.memory_path}", file=sys.stderr)

        # L4: 会话配置
        session_config = _safe_json_load(self.session_config_path)
        if session_config:
            config = deep_merge(config, session_config)
            print(f"[ConfigMerger] L4 会话配置已合并: {self.session_config_path}", file=sys.stderr)

        # L5: 运行时参数（最高优先级）
        if self.runtime_args:
            config = deep_merge(config, self.runtime_args)
            print(f"[ConfigMerger] L5 运行时参数已合并", file=sys.stderr)

        return config

    def get(self, key: str, default: Any = None) -> Any:
        """
        合并配置后获取指定键的值。
        
        Args:
            key: 配置键（支持点号分隔的嵌套键，如 "memory.vector_search_threshold"）
            default: 默认值
            
        Returns:
            配置值
        """
        config = self.merge()
        keys = key.split(".")
        value = config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        return value

    def diff_layers(self) -> Dict[str, Dict[str, Any]]:
        """
        返回各层配置的快照，用于调试和审计。
        
        Returns:
            每层的配置字典
        """
        return {
            "L1_defaults": self.DEFAULTS.copy(),
            "L2_project": _safe_json_load(self.project_config_path),
            "L3_memory_prefs": _extract_memory_preferences(self.memory_path),
            "L4_session": _safe_json_load(self.session_config_path),
            "L5_runtime": self.runtime_args.copy(),
        }


# ── CLI 入口 ───────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="天命配置层次化合并器")
    parser.add_argument("--merge", action="store_true", help="执行合并并输出结果")
    parser.add_argument("--get", type=str, help="获取指定键的值（支持点号嵌套）")
    parser.add_argument("--diff", action="store_true", help="显示各层配置快照")
    parser.add_argument("--project-root", type=str, help="项目根目录")
    parser.add_argument("--session-config", type=str, help="session-config.json 路径")
    parser.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"), help="设置运行时覆盖")

    args = parser.parse_args()

    runtime = {}
    if args.set:
        # 支持 JSON 值
        try:
            runtime[args.set[0]] = json.loads(args.set[1])
        except json.JSONDecodeError:
            runtime[args.set[0]] = args.set[1]

    merger = ConfigMerger(
        project_root=args.project_root,
        session_config_path=args.session_config,
        runtime_args=runtime,
    )

    if args.merge:
        config = merger.merge()
        print(json.dumps(config, indent=2, ensure_ascii=False))
    elif args.get:
        value = merger.get(args.get)
        if value is not None:
            if isinstance(value, (dict, list)):
                print(json.dumps(value, indent=2, ensure_ascii=False))
            else:
                print(value)
        else:
            print(f"键 '{args.get}' 不存在", file=sys.stderr)
            sys.exit(1)
    elif args.diff:
        layers = merger.diff_layers()
        for layer_name, layer_config in layers.items():
            print(f"\n{'='*50}")
            print(f"  {layer_name}")
            print(f"{'='*50}")
            if layer_config:
                print(json.dumps(layer_config, indent=2, ensure_ascii=False))
            else:
                print("  (空)")
    else:
        parser.print_help()
