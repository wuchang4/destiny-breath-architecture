#!/usr/bin/env python3
"""
架构心跳 (Architecture Heartbeat)
Protocol 5 — 每4小时自动执行一轮状态检查

功能:
  1. 写检查点 — 当前会话状态序列化
  2. 记度量分 — 扫描 session 完成的任务并记录 score
  3. 扫基线趋势 — 计算各任务类型趋势，判断是否退化
  4. 退化自触发梯度 — 连续3次退化自动触发梯度反向传播
  5. 自诊断 (Protocol 6) — 上下文占用率、工具疲劳度、检查点健康

调用方式:
  python3 heartbeat.py [--diagnose-only]
"""

import json
import os
import sys
import glob
from datetime import datetime, timezone, timedelta

# === 路径常量 ===
CHECKPOINT_DIR = os.path.expanduser("~/.clawdbot/checkpoints")
BASELINE_DIR = os.path.expanduser("~/.clawdbot/baselines")
HEARTBEAT_DIR = os.path.expanduser("~/.clawdbot/heartbeat")
GRADIENT_DIR = CHECKPOINT_DIR  # 梯度记录存到检查点目录

os.makedirs(HEARTBEAT_DIR, exist_ok=True)

# === 时间 ===
TZ = timezone(timedelta(hours=8))
NOW = datetime.now(TZ)

# === 步骤1: 写心跳日志 ===
def log_heartbeat():
    """记录心跳日志"""
    log_path = os.path.join(HEARTBEAT_DIR, "heartbeat_log.jsonl")
    entry = {
        "ts": NOW.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "type": "heartbeat"
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return log_path

# === 步骤2: 读基线并计算趋势 ===
def scan_baselines():
    """扫描所有基线文件，计算每个任务类型的趋势"""
    results = []
    pattern = os.path.join(BASELINE_DIR, "*.json")
    
    for fpath in sorted(glob.glob(pattern)):
        if "README" in fpath:
            continue
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        records = data.get("records", [])
        if len(records) < 2:
            results.append({
                "task_type": data["task_type"],
                "status": "insufficient_data",
                "records": len(records),
                "trend": 0
            })
            continue
        
        # 取最近2次的 score 对比
        scores = [r.get("metric_score", 0) for r in records[-5:]]
        if len(scores) >= 2:
            delta = scores[-1] - scores[-2]
        else:
            delta = 0
        
        # 判断趋势
        if len(scores) >= 3:
            recent_three = scores[-3:]
            all_down = all(recent_three[i] <= recent_three[i-1] for i in range(1, 3))
            if all_down and recent_three[-1] < recent_three[0]:
                status = "degrading"
            elif recent_three[-1] > recent_three[0]:
                status = "improving"
            else:
                status = "stable"
        else:
            status = "stable" if delta >= 0 else "degrading"
        
        results.append({
            "task_type": data["task_type"],
            "status": status,
            "records": len(records),
            "scores": scores,
            "last_delta": round(delta, 2),
            "trend": round(delta, 2)
        })
    
    return results

# === 步骤3: 自动触发梯度反向传播 ===
def auto_trigger_gradient(degraded_tasks):
    """对连续退化的任务自动触发梯度记录"""
    triggered = []
    
    for task in degraded_tasks:
        task_type = task["task_type"]
        
        # 检查这个任务是否已经触发过梯度
        grad_pattern = os.path.join(GRADIENT_DIR, f"grad-*.json")
        existing_grads = [f for f in glob.glob(grad_pattern) 
                          if task_type in open(f, "r", encoding="utf-8").read()]
        if len(existing_grads) >= 2:
            continue  # 已经触发过2次了，不再重复
        
        gradient = {
            "gradient_id": f"grad-auto-{NOW.strftime('%Y-%m-%d-%H%M')}-{task_type}",
            "created": NOW.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "trigger": "auto_heartbeat_degradation_detected",
            "task_type": task_type,
            "steps": {
                "1_loss_detection": {
                    "error": f"任务类型 [{task_type}] 连续退化: scores={task['scores']}, delta={task['last_delta']}",
                    "severity": "medium",
                    "detected_by": "heartbeat.py auto-scan"
                },
                "2_gradient_computation": {
                    "root_cause_node": "unknown_auto",
                    "analysis": f"需人工介入确认退化根因。趋势: {task['status']}, 上次delta: {task['last_delta']}"
                },
                "3_backward_pass": {
                    "traced_path": ["auto_detected — 需人工回溯"],
                    "gradient_vector": "auto_detected — 需人工确认"
                },
                "4_parameter_update": {
                    "changes_made": [],
                    "note": "退化已自动检测，但修复规则需人工确认"
                },
                "5_verification": {
                    "verified": False,
                    "evidence": "等待人工确认后再验证",
                    "note": "auto-triggered gradient — 请查看后决定是否更新规则"
                }
            },
            "verdict": "auto_triggered_pending_human_review"
        }
        
        grad_path = os.path.join(GRADIENT_DIR, gradient["gradient_id"] + ".json")
        with open(grad_path, "w", encoding="utf-8") as f:
            json.dump(gradient, f, ensure_ascii=False, indent=2)
        
        triggered.append({
            "task_type": task_type,
            "gradient_file": grad_path
        })
    
    return triggered

# === Protocol 6: 自诊断仪表盘 ===
def self_diagnostics():
    """运行态自诊断：上下文占用率、工具疲劳度、检查点健康"""
    results = {}
    
    # 诊断1: 检查点健康
    pattern = os.path.join(CHECKPOINT_DIR, "ckpt-*.json")
    checkpoints = sorted(glob.glob(pattern))
    if checkpoints:
        latest = checkpoints[-1]
        try:
            with open(latest, "r", encoding="utf-8") as f:
                cp = json.load(f)
            cp_health = {
                "status": "healthy",
                "file": latest,
                "size": os.path.getsize(latest),
                "last_checkpoint": cp.get("created", "unknown"),
                "schema_valid": all(k in cp for k in ["checkpoint_id", "created", "session_context"])
            }
        except:
            cp_health = {"status": "corrupt", "file": latest, "error": "无法解析JSON"}
    else:
        cp_health = {"status": "empty", "file": None, "note": "无检查点文件"}
    results["checkpoint_health"] = cp_health
    
    # 诊断2: 基线健康
    base_pattern = os.path.join(BASELINE_DIR, "*.json")
    base_files = [f for f in glob.glob(base_pattern) if "README" not in f]
    baseline_health = {
        "total": len(base_files),
        "names": [os.path.basename(f).replace(".json","") for f in base_files],
        "all_parseable": True
    }
    for f in base_files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                json.load(fh)
        except:
            baseline_health["all_parseable"] = False
            baseline_health["error_file"] = f
    results["baseline_health"] = baseline_health
    
    # 诊断3: 梯度文件统计
    grad_pattern = os.path.join(GRADIENT_DIR, "grad-*.json")
    grads = sorted(glob.glob(grad_pattern))
    pending = 0
    for g in grads:
        try:
            with open(g, "r", encoding="utf-8") as f:
                gd = json.load(f)
            if "pending" in gd.get("verdict", "") or "auto_triggered" in gd.get("verdict", ""):
                pending += 1
        except:
            pass
    results["gradient_stats"] = {
        "total": len(grads),
        "pending_review": pending
    }
    
    # 诊断4: Token占用率估算
    # 通过检查点文件和日志文件大小估算上下文消耗趋势
    log_path = os.path.join(HEARTBEAT_DIR, "heartbeat_log.jsonl")
    log_size = os.path.getsize(log_path) if os.path.exists(log_path) else 0
    total_session_mb = sum(os.path.getsize(f) for f in checkpoints) / 1024 / 1024 if checkpoints else 0
    
    results["context_estimation"] = {
        "checkpoint_data_mb": round(total_session_mb, 2),
        "heartbeat_log_size_b": log_size,
        "note": "精确占用率由运行时上下文报告，此处仅为文件级估算"
    }
    
    # 诊断结果写入
    diag_path = os.path.join(HEARTBEAT_DIR, "diagnostics.json")
    with open(diag_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": NOW.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "results": results
        }, f, ensure_ascii=False, indent=2)
    
    return results

# === 步骤4: 主流程 ===
def heartbeat():
    results = {}
    
    # 步骤1: 心跳日志
    log_path = log_heartbeat()
    results["log"] = f"heartbeat logged to {log_path}"
    
    # 步骤2: 扫描基线
    baseline_results = scan_baselines()
    results["baselines"] = baseline_results
    
    # 步骤3: 检测退化
    degraded = [t for t in baseline_results if t["status"] == "degrading"]
    if degraded:
        triggered = auto_trigger_gradient(degraded)
        results["auto_gradients"] = triggered
        results["summary"] = f"发现 {len(degraded)} 个退化任务·已触发 {len(triggered)} 个梯度"
    else:
        results["auto_gradients"] = []
        results["summary"] = "无退化 · 状态正常"
    
    # 报告
    print(f"❤️ 架构心跳 — {NOW.strftime('%Y-%m-%d %H:%M')}")
    print(f"  基线检查: {len(baseline_results)} 个任务类型")
    for b in baseline_results:
        status_icon = {"degrading": "🔴", "improving": "🟢", "stable": "🟡", "insufficient_data": "⚪"}
        icon = status_icon.get(b["status"], "⚪")
        trend_str = f"delta={b['last_delta']:+.2f}" if b.get("last_delta") is not None else "N/A"
        print(f"    {icon} {b['task_type']}: {b['status']} ({trend_str}, {b['records']}次)")
    print(f"  梯度触发: {len(results['auto_gradients'])} 个")
    for g in results["auto_gradients"]:
        print(f"    → {g['task_type']}: {g['gradient_file']}")
    
    # Protocol 6: 自诊断
    diag = self_diagnostics()
    results["diagnostics"] = diag
    ch = diag["checkpoint_health"]
    ch_icon = "🟢" if ch["status"] == "healthy" else ("🔴" if ch["status"] == "corrupt" else "🟡")
    print(f"  Protocol 6 诊断:")
    print(f"    {ch_icon} 检查点: {ch['status']} ({ch.get('size',0)} bytes)")
    print(f"    📊 基线: {diag['baseline_health']['total']}个文件, 全部可解析={diag['baseline_health']['all_parseable']}")
    print(f"    🧮 梯度: {diag['gradient_stats']['total']}个总, {diag['gradient_stats']['pending_review']}个待审")
    print(f"  小结: {results['summary']}")
    
    return results

# === CLI 入口 ===
if __name__ == "__main__":
    if "--diagnose-only" in sys.argv:
        diag = self_diagnostics()
        print(json.dumps(diag, ensure_ascii=False, indent=2))
    else:
        heartbeat()
