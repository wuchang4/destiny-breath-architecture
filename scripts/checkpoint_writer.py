#!/usr/bin/env python3
"""三省图检查点写入器 — 由 checkpoint-manager skill 调用"""

import json
import os
import glob
from datetime import datetime, timezone, timedelta

CHECKPOINT_DIR = os.path.expanduser("~/.clawdbot/checkpoints")
MAX_CHECKPOINTS = 5

def write_checkpoint(session_context: dict, metric_baseline: dict = None):
    """写入一个检查点"""
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    
    # 生成 ID
    now = datetime.now(timezone(timedelta(hours=8)))
    date_str = now.strftime("%Y-%m-%d")
    
    # 找已有检查点的序号
    pattern = os.path.join(CHECKPOINT_DIR, f"ckpt-{date_str}-*.json")
    existing = glob.glob(pattern)
    next_num = len(existing) + 1
    
    checkpoint = {
        "checkpoint_id": f"ckpt-{date_str}-{next_num:02d}",
        "created": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "session_context": {
            "task_type": session_context.get("task_type", "unknown"),
            "description": session_context.get("description", ""),
            "status": session_context.get("status", "in_progress"),
            "graph_node": session_context.get("graph_node", "START"),
            "pending_tasks": session_context.get("pending_tasks", []),
            "completed_work": session_context.get("completed_work", []),
            "user_confirmed": session_context.get("user_confirmed", False),
            "user_intent": session_context.get("user_intent", "")
        },
        "infrastructure": {
            "workspace": os.getcwd(),
            "checkpoints_dir": CHECKPOINT_DIR
        }
    }
    
    if metric_baseline:
        checkpoint["metric_baseline"] = metric_baseline
    
    filepath = os.path.join(CHECKPOINT_DIR, f"{checkpoint['checkpoint_id']}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False, indent=2)
    
    # 清理旧检查点
    _cleanup_old()
    
    print(f"✅ 检查点已写入: {filepath}")
    return filepath

def _cleanup_old():
    """保持最近 MAX_CHECKPOINTS 个检查点"""
    pattern = os.path.join(CHECKPOINT_DIR, "ckpt-*.json")
    files = sorted(glob.glob(pattern))
    while len(files) > MAX_CHECKPOINTS:
        os.remove(files.pop(0))

if __name__ == "__main__":
    # 示例用法
    write_checkpoint({
        "task_type": "example",
        "description": "测试检查点写入",
        "status": "in_progress",
        "graph_node": "执行节点 → AAR/Checkpt",
        "pending_tasks": ["完成测试"],
        "completed_work": ["写入检查点"],
        "user_confirmed": True,
        "user_intent": "测试检查点系统"
    })
