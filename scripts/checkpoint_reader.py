#!/usr/bin/env python3
"""三省图检查点读取器 — 被 Protocol 4 调用"""

import json
import os
import glob

CHECKPOINT_DIR = os.path.expanduser("~/.clawdbot/checkpoints")

def get_latest_checkpoint():
    """获取最新的检查点文件"""
    pattern = os.path.join(CHECKPOINT_DIR, "ckpt-*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        return None
    latest = files[-1]
    with open(latest, "r", encoding="utf-8") as f:
        return json.load(f)

def format_summary(checkpoint):
    """格式化为 Protocol 4 可读的简报"""
    ctx = checkpoint["session_context"]
    pending = ctx.get("pending_tasks", [])
    completed = ctx.get("completed_work", [])
    
    lines = []
    lines.append(f"📌 检查点: {checkpoint['checkpoint_id']}")
    lines.append(f"  状态: {ctx['status']}")
    lines.append(f"  图节点: {ctx['graph_node']}")
    lines.append(f"  用户意图: {ctx['user_intent']}")
    
    if pending:
        lines.append(f"  ⏳ 未完成 ({len(pending)}项):")
        for t in pending:
            lines.append(f"    · {t}")
    
    if completed:
        lines.append(f"  ✅ 已完成 ({len(completed)}项):")
        for t in completed[-3:]:  # 只显示最近3项
            lines.append(f"    · {t}")
    
    return "\n".join(lines)

def clear_checkpoints():
    """清理所有检查点"""
    pattern = os.path.join(CHECKPOINT_DIR, "ckpt-*.json")
    for f in glob.glob(pattern):
        os.remove(f)
    return f"已清除 {CHECKPOINT_DIR}/ 下的所有检查点"

if __name__ == "__main__":
    cp = get_latest_checkpoint()
    if cp:
        print(format_summary(cp))
    else:
        print("无检查点 — 无未完成任务")
