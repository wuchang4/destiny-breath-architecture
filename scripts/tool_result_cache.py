#!/usr/bin/env python3
"""
天命架构 — 工具结果缓存 (Tool Result Cache)
WebSearch/WebFetch 结果哈希缓存，避免重复查询消耗。

缓存策略：
  - 键: 查询内容的 SHA256 哈希 + 工具名
  - TTL: 默认 30 分钟（WebSearch）/ 15 分钟（WebFetch）
  - 存储: ~/.clawdbot/cache/tool_results.json
  - 大小限制: 最多 200 条，LRU 淘汰

用法：
    from tool_result_cache import ToolResultCache
    cache = ToolResultCache()
    
    # 查询缓存
    cached = cache.get("WebSearch", "小米MiMo最新模型")
    if cached:
        return cached  # 命中，跳过API调用
    
    # 写入缓存
    cache.put("WebSearch", "小米MiMo最新模型", result_data)
"""

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional


class ToolResultCache:
    """
    工具结果缓存层。
    
    对 WebSearch 和 WebFetch 的查询结果做哈希缓存，
    避免在同一会话或短时间内重复发起相同的网络查询。
    """

    DEFAULT_CACHE_DIR = os.path.expanduser("~/.clawdbot/cache")
    DEFAULT_CACHE_FILE = "tool_results.json"
    MAX_ENTRIES = 200

    # TTL 秒数
    TTL = {
        "WebSearch": 30 * 60,   # 30 分钟
        "WebFetch":  15 * 60,   # 15 分钟
        "default":   10 * 60,   # 10 分钟
    }

    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = cache_dir or self.DEFAULT_CACHE_DIR
        self.cache_file = os.path.join(self.cache_dir, self.DEFAULT_CACHE_FILE)
        self.entries: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        """从磁盘加载缓存。"""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.entries = data.get("entries", {})
                # 启动时清理过期条目
                self._evict_expired()
        except (json.JSONDecodeError, PermissionError) as e:
            print(f"[Cache] 加载失败，重建缓存: {e}", file=sys.stderr)
            self.entries = {}

    def _save(self):
        """持久化缓存到磁盘。"""
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            data = {
                "version": 1,
                "updated_at": time.time(),
                "entries": self.entries,
            }
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except (PermissionError, OSError) as e:
            print(f"[Cache] 保存失败: {e}", file=sys.stderr)

    @staticmethod
    def _make_key(tool_name: str, query: str) -> str:
        """生成缓存键：工具名 + 查询内容的 SHA256。"""
        content = f"{tool_name}::{query}".encode("utf-8")
        return hashlib.sha256(content).hexdigest()[:16]

    def get(self, tool_name: str, query: str) -> Optional[Any]:
        """
        查询缓存。
        
        Args:
            tool_name: 工具名（如 "WebSearch"）
            query: 查询内容
            
        Returns:
            缓存的结果，或 None（未命中/已过期）
        """
        key = self._make_key(tool_name, query)
        entry = self.entries.get(key)
        if not entry:
            return None

        # 检查 TTL
        ttl = self.TTL.get(tool_name, self.TTL["default"])
        if time.time() - entry.get("created_at", 0) > ttl:
            # 过期，删除
            del self.entries[key]
            self._save()
            return None

        # 更新访问时间
        entry["last_access"] = time.time()
        return entry.get("result")

    def put(self, tool_name: str, query: str, result: Any):
        """
        写入缓存。
        
        Args:
            tool_name: 工具名
            query: 查询内容
            result: 要缓存的结果
        """
        key = self._make_key(tool_name, query)
        self.entries[key] = {
            "tool": tool_name,
            "query": query[:200],  # 只存前200字符用于调试
            "result": result,
            "created_at": time.time(),
            "last_access": time.time(),
        }

        # LRU 淘汰
        if len(self.entries) > self.MAX_ENTRIES:
            self._evict_lru()

        self._save()

    def invalidate(self, tool_name: str, query: str):
        """手动使某条缓存失效。"""
        key = self._make_key(tool_name, query)
        if key in self.entries:
            del self.entries[key]
            self._save()

    def clear(self):
        """清空所有缓存。"""
        self.entries.clear()
        self._save()

    def _evict_expired(self):
        """清理所有过期条目。"""
        now = time.time()
        expired_keys = []
        for key, entry in self.entries.items():
            tool = entry.get("tool", "default")
            ttl = self.TTL.get(tool, self.TTL["default"])
            if now - entry.get("created_at", 0) > ttl:
                expired_keys.append(key)
        for key in expired_keys:
            del self.entries[key]

    def _evict_lru(self):
        """LRU 淘汰：删除最久未访问的条目，直到不超过限制。"""
        while len(self.entries) > self.MAX_ENTRIES:
            # 找最旧的条目
            oldest_key = min(
                self.entries, 
                key=lambda k: self.entries[k].get("last_access", 0)
            )
            del self.entries[oldest_key]

    def stats(self) -> Dict[str, Any]:
        """返回缓存统计。"""
        if not self.entries:
            return {"total": 0, "by_tool": {}}

        by_tool: Dict[str, int] = {}
        for entry in self.entries.values():
            tool = entry.get("tool", "unknown")
            by_tool[tool] = by_tool.get(tool, 0) + 1

        return {
            "total": len(self.entries),
            "max": self.MAX_ENTRIES,
            "by_tool": by_tool,
            "cache_file": self.cache_file,
        }


# ── CLI 入口 ───────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="天命工具结果缓存")
    parser.add_argument("--stats", action="store_true", help="显示缓存统计")
    parser.add_argument("--clear", action="store_true", help="清空缓存")
    parser.add_argument("--get", nargs=2, metavar=("TOOL", "QUERY"), help="查询缓存")
    parser.add_argument("--put", nargs=3, metavar=("TOOL", "QUERY", "RESULT"), help="写入缓存")

    args = parser.parse_args()
    cache = ToolResultCache()

    if args.stats:
        s = cache.stats()
        print(f"缓存统计:")
        print(f"  条目数: {s['total']} / {s['max']}")
        print(f"  按工具: {s.get('by_tool', {})}")
        print(f"  存储位置: {s['cache_file']}")
    elif args.clear:
        cache.clear()
        print("缓存已清空")
    elif args.get:
        result = cache.get(args.get[0], args.get[1])
        if result:
            print(f"✅ 缓存命中:")
            print(json.dumps(result, indent=2, ensure_ascii=False)[:2000])
        else:
            print("❌ 未命中")
    elif args.put:
        cache.put(args.put[0], args.put[1], args.put[2])
        print("✅ 已缓存")
    else:
        parser.print_help()
