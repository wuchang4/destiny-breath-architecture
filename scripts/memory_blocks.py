#!/usr/bin/env python3
"""
天命架构 — Memory Blocks 记忆系统
借鉴 Letta 的 Memory Blocks 设计。

核心概念：
  Core Blocks（常驻上下文）：
    - persona block → SOUL.md（我的人设/架构规则）
    - human block   → USER.md（你的信息）
    - memories block → MEMORY.md（偏好/习惯/经验）

  Archival Memory（向量存储）：
    - 历史记忆（旧日志/复盘）
    - 按需检索，不常驻上下文

  Compaction（自动压缩）：
    - Core Block 太大时 → LLM 自评重要性
    - 低频低价值信息降入 Archival Memory

用法：
    from memory_blocks import MemorySystem
    ms = MemorySystem()
    
    # 读取 Core Blocks
    blocks = ms.get_core_blocks()
    print(blocks["persona"]["content"])
    
    # 写入 Block
    ms.update_block("human", "name", "用户")
    
    # 检索 Archival Memory
    results = ms.search_archival("上次讨论的架构")
"""

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ── 数据模型 ─────────────────────────────────────────────

@dataclass
class MemoryBlock:
    """Core Memory 的一个块。"""
    label: str          # "persona" | "human" | "memories"
    content: str        # 内容
    importance: float   # 重要性 0.0-1.0
    updated_at: float   # 最后更新时间
    created_at: float   # 创建时间

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ArchivalEntry:
    """Archival Memory 的一条记录。"""
    id: str
    label: str          # 来源 block 标签
    content: str        # 内容
    importance: float   # 原始重要性
    archived_at: float  # 归档时间
    source: str         # 来源文件或上下文

    def to_dict(self) -> dict:
        return asdict(self)


class MemorySystem:
    """
    记忆系统。
    
    管理 Core Blocks（常驻）和 Archival Memory（向量存储）两层。
    """

    # 文件路径
    MEMORY_DIR = os.path.expanduser("~/.clawdbot/memory_blocks")
    CORE_FILE = os.path.join(MEMORY_DIR, "core_blocks.json")
    ARCHIVAL_FILE = os.path.join(MEMORY_DIR, "archival_store.json")

    # Block 标签定义
    BLOCK_LABELS = {
        "persona": {
            "source_file": os.path.expanduser("~/.workbuddy/SOUL.md"),
            "description": "我的人设、架构规则、Core Truths、Logic Anchors",
            "max_tokens": 4000,
        },
        "human": {
            "source_file": os.path.expanduser("~/.workbuddy/USER.md"),
            "description": "你的信息、称呼、偏好",
            "max_tokens": 1000,
        },
        "memories": {
            "source_file": None,  # 由多个来源聚合（MEMORY.md + daily logs）
            "description": "你的偏好、习惯、经验教训、重大事件",
            "max_tokens": 2000,
        },
    }

    def __init__(self):
        os.makedirs(self.MEMORY_DIR, exist_ok=True)
        self._core_blocks: Dict[str, MemoryBlock] = {}
        self._archival_store: List[ArchivalEntry] = []
        self._load()

    # ── 核心 Block 管理 ──────────────────────────────────

    def get_core_blocks(self) -> Dict[str, MemoryBlock]:
        """获取所有 Core Blocks（读取 + 自动加载源文件）。"""
        # 确保源文件同步
        for label in list(self.BLOCK_LABELS.keys()):
            if label not in self._core_blocks:
                self._load_from_source(label)
        return dict(self._core_blocks)

    def get_block(self, label: str) -> Optional[str]:
        """获取指定 Block 的内容。"""
        blocks = self.get_core_blocks()
        if label in blocks:
            return blocks[label].content
        return None

    def update_block(self, label: str, content: str, importance: float = 0.5):
        """更新指定 Block 的内容。"""
        now = time.time()
        if label in self._core_blocks:
            old = self._core_blocks[label]
            old.content = content
            old.importance = importance
            old.updated_at = now
        else:
            self._core_blocks[label] = MemoryBlock(
                label=label,
                content=content,
                importance=importance,
                updated_at=now,
                created_at=now,
            )
        self._save_core()

    def append_to_block(self, label: str, text: str, importance: float = 0.3):
        """追加内容到指定 Block。"""
        existing = self.get_block(label) or ""
        new_content = existing + "\n" + text if existing else text
        self.update_block(label, new_content.strip(), importance)

    def add_memory(self, category: str, content: str, importance: float = 0.5):
        """
        添加一条记忆（自动决定放 Core 还是 Archival）。
        
        Args:
            category: "persona" | "human" | "memories" — 属于哪个块
            content: 记忆内容
            importance: 重要性 0.0-1.0（≥0.4 放 Core，<0.4 放 Archival）
        """
        if importance >= 0.4 and category in self.BLOCK_LABELS:
            self.append_to_block(category, content, importance)
        else:
            self._add_archival(category, content, importance)

    # ── Compaction（借鉴 Letta）───────────────────────────

    def auto_compact(self, threshold: float = 0.3):
        """
        自动压缩 Core Blocks。
        
        参照 Letta 的 Compaction 机制：
        1. 扫描所有 Core Blocks
        2. 提取低频/低价值信息
        3. 移入 Archival Memory
        
        Args:
            threshold: 重要性阈值，低于此值的移入 Archival
        """
        changed = False
        for label, block in list(self._core_blocks.items()):
            if block.importance < threshold and label != "persona":
                # person 块不降级（始终重要）
                self._add_archival(
                    label=label,
                    content=block.content,
                    importance=block.importance,
                    source=f"auto_compact: {label}"
                )
                del self._core_blocks[label]
                changed = True
                print(f"[MemoryBlocks] 已归档: {label} (重要性={block.importance})")

        if changed:
            self._save_core()
            self._save_archival()

    def suggest_importance(self, content: str) -> float:
        """
        建议内容的重要性分数（规则评估）。
        
        天命的规则引擎版本（非 LLM 调用）：
        - 包含频繁提及的关键词 → 高
        - 短的/一次性的信息 → 低
        - 用户明确说的偏好 → 中高
        
        Args:
            content: 要评估的内容
            
        Returns:
            0.0-1.0 的重要性分数
        """
        high_keywords = ["记住", "重要", "偏好", "习惯", "规则", "永远", "总是", "不"]
        low_keywords = ["昨天", "今天", "刚刚", "临时", "大概"]

        content_lower = content.lower()
        score = 0.5  # 默认中等

        for kw in high_keywords:
            if kw in content_lower:
                score += 0.1
        for kw in low_keywords:
            if kw in content_lower:
                score -= 0.1

        # 较长的内容可能更重要
        if len(content) > 200:
            score += 0.1
        if len(content) < 20:
            score -= 0.1

        return max(0.0, min(1.0, score))

    # ── Archival Memory ────────────────────────────────

    def search_archival(self, query: str, top_k: int = 5) -> List[ArchivalEntry]:
        """
        在 Archival Memory 中搜索（简单关键词匹配）。
        
        真正的语义搜索依赖 vector_memory.py，
        这里是基础的关键词匹配实现。
        
        Args:
            query: 搜索关键词
            top_k: 返回结果数量
            
        Returns:
            匹配的 ArchivalEntry 列表
        """
        query_lower = query.lower()
        keywords = query_lower.split()

        scored = []
        for entry in self._archival_store:
            content_lower = entry.content.lower()
            score = sum(1 for kw in keywords if kw in content_lower)
            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:top_k]]

    def _add_archival(self, label: str, content: str,
                      importance: float, source: str = "manual"):
        """添加一条归档记录。"""
        entry = ArchivalEntry(
            id=f"arch_{int(time.time())}_{len(self._archival_store)}",
            label=label,
            content=content,
            importance=importance,
            archived_at=time.time(),
            source=source,
        )
        self._archival_store.append(entry)
        # 限制 Archival 大小
        if len(self._archival_store) > 500:
            self._archival_store = self._archival_store[-500:]
        self._save_archival()

    # ── 持久化 ──────────────────────────────────────────

    def _load(self):
        """从磁盘加载所有数据。"""
        self._load_core()
        self._load_archival()
        # 确保源文件同步
        for label in self.BLOCK_LABELS:
            if label not in self._core_blocks:
                self._load_from_source(label)

    def _load_from_source(self, label: str):
        """从源文件加载 Block。"""
        info = self.BLOCK_LABELS.get(label)
        if not info:
            return

        source_file = info["source_file"]
        content = ""
        importance = 0.7 if label in ("persona", "human") else 0.5

        if source_file and os.path.exists(source_file):
            try:
                with open(source_file, "r", encoding="utf-8") as f:
                    content = f.read()
                print(f"[MemoryBlocks] 从 {source_file} 加载 {label} block")
            except (PermissionError, OSError) as e:
                print(f"[MemoryBlocks] 加载 {source_file} 失败: {e}")

        self._core_blocks[label] = MemoryBlock(
            label=label,
            content=content,
            importance=importance,
            updated_at=time.time(),
            created_at=time.time(),
        )

    def _load_core(self):
        """从文件加载 Core Blocks。"""
        try:
            if os.path.exists(self.CORE_FILE):
                with open(self.CORE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for label, item in data.items():
                    self._core_blocks[label] = MemoryBlock(**item)
        except (json.JSONDecodeError, OSError):
            pass

    def _load_archival(self):
        """从文件加载 Archival Memory。"""
        try:
            if os.path.exists(self.ARCHIVAL_FILE):
                with open(self.ARCHIVAL_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._archival_store = [ArchivalEntry(**item) for item in data]
        except (json.JSONDecodeError, OSError):
            pass

    def _save_core(self):
        """持久化 Core Blocks。"""
        data = {label: block.to_dict()
                for label, block in self._core_blocks.items()}
        with open(self.CORE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _save_archival(self):
        """持久化 Archival Memory。"""
        data = [entry.to_dict() for entry in self._archival_store]
        with open(self.ARCHIVAL_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── 工具 ────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """返回记忆系统统计。"""
        core_blocks = self.get_core_blocks()
        return {
            "core_blocks": {
                label: {
                    "content_chars": len(block.content),
                    "importance": block.importance,
                    "age_hours": round((time.time() - block.updated_at) / 3600, 1),
                }
                for label, block in core_blocks.items()
            },
            "archival_count": len(self._archival_store),
            "total_memories": len(core_blocks) + len(self._archival_store),
        }

    def summary(self) -> str:
        """返回可读的记忆摘要。"""
        stats = self.stats()
        lines = ["📦 Memory System Status", "=" * 30]
        for label, info in stats["core_blocks"].items():
            icon = {"persona": "🧠", "human": "👤", "memories": "📝"}.get(label, "📦")
            lines.append(f"  {icon} {label}: {info['content_chars']}字，"
                        f"重要性{info['importance']}，{info['age_hours']}h前更新")

        lines.append(f"  📚 Archival: {stats['archival_count']}条")
        lines.append(f"  📊 总计: {stats['total_memories']}条记忆")
        return "\n".join(lines)


# ── CLI 入口 ───────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="天命 Memory Blocks 记忆系统")
    parser.add_argument("--status", action="store_true", help="查看记忆状态")
    parser.add_argument("--blocks", action="store_true", help="列出所有 Core Blocks")
    parser.add_argument("--get", type=str, help="获取指定 Block 的内容")
    parser.add_argument("--update", nargs=3, metavar=("LABEL", "KEY", "VALUE"),
                        help="更新 Block")
    parser.add_argument("--add", nargs=2, metavar=("LABEL", "CONTENT"),
                        help="添加一条记忆")
    parser.add_argument("--search", type=str, help="搜索 Archival Memory")
    parser.add_argument("--compact", action="store_true", help="执行 Compaction")
    parser.add_argument("--json", action="store_true", help="JSON 输出")

    args = parser.parse_args()
    ms = MemorySystem()

    if args.status:
        if args.json:
            print(json.dumps(ms.stats(), indent=2, ensure_ascii=False))
        else:
            print(ms.summary())

    elif args.blocks:
        blocks = ms.get_core_blocks()
        for label, block in blocks.items():
            print(f"\n{'='*40}")
            print(f"  [{label}] 重要性={block.importance}")
            print(f"{'='*40}")
            print(block.content[:2000])
            if len(block.content) > 2000:
                print(f"\n  ... (共{len(block.content)}字，截断显示)")

    elif args.get:
        content = ms.get_block(args.get)
        if content:
            print(content)
        else:
            print(f"Block '{args.get}' 不存在")

    elif args.update:
        ms.update_block(args.update[0], args.update[2], float(args.update[1]))
        print(f"✅ {args.update[0]} 已更新")

    elif args.add:
        importance = ms.suggest_importance(args.add[1])
        ms.add_memory(args.add[0], args.add[1], importance)
        print(f"✅ 已添加记忆到 {args.add[0]}（重要性={importance:.2f}）")

    elif args.search:
        results = ms.search_archival(args.search)
        if results:
            print(f"找到 {len(results)} 条匹配:\n")
            for r in results:
                icon = {"persona": "🧠", "human": "👤", "memories": "📝"}.get(r.label, "📦")
                print(f"  {icon} [{r.label}] (重要性={r.importance:.2f})")
                print(f"  {r.content[:200]}...")
                print()
        else:
            print("未找到匹配")

    elif args.compact:
        ms.auto_compact()
        print("✅ Compaction 完成")

    else:
        parser.print_help()
