#!/usr/bin/env python3
"""
天命架构 — Protocol 7: 工具执行安全验证链 (Tool Safety Chain)
借鉴 Claw Code 的 9 子模块 Bash 安全验证设计。

7 层验证：
  [1] 权限模式检查   → read-only / workspace-write / full-access
  [2] 路径安全检查   → 路径遍历、敏感目录
  [3] 命令语义分析   → 危险命令检测
  [4] 沙箱决策       → 是否需要隔离执行
  [5] 输出大小限制   → 大 stdout/文件截断
  [6] 用户确认       → 高风险操作需人工批准
  [7] 执行监控       → 超时、异常捕获

用法：
    from tool_safety_chain import ToolSafetyChain
    chain = ToolSafetyChain(permission_mode="workspace-write")
    result = chain.validate(tool_name="Bash", args={"command": "rm -rf /"})
    if not result.passed:
        print(result.block_reason)
"""

import os
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ── 枚举与数据类 ───────────────────────────────────────────

class PermissionMode(Enum):
    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"
    FULL_ACCESS = "full-access"


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKED = "blocked"


class Verdict(Enum):
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"
    NEED_CONFIRM = "need_confirm"


@dataclass
class LayerResult:
    """单层验证结果。"""
    layer: int
    name: str
    verdict: Verdict
    message: str = ""


@dataclass
class SafetyResult:
    """完整验证链结果。"""
    passed: bool
    verdict: Verdict
    risk_level: RiskLevel
    layers: List[LayerResult] = field(default_factory=list)
    block_reason: str = ""
    needs_user_confirm: bool = False
    needs_sandbox: bool = False
    output_truncate: bool = False

    def summary(self) -> str:
        lines = []
        for lr in self.layers:
            icon = {"pass": "✅", "warn": "⚠️", "block": "🔴", "need_confirm": "❓"}.get(
                lr.verdict.value, "❓"
            )
            lines.append(f"  L{lr.layer} {icon} {lr.name}: {lr.message}")
        status = "PASS" if self.passed else "BLOCKED"
        lines.append(f"\n  结论: {status} | 风险: {self.risk_level.value}")
        if self.block_reason:
            lines.append(f"  阻断原因: {self.block_reason}")
        return "\n".join(lines)


# ── 危险命令检测 ───────────────────────────────────────────

DANGEROUS_COMMANDS = {
    "block": [
        # 文件删除
        r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+.*|-rf\s+|--recursive\s+--force)",
        r"\bdel\s+/[sS]\b",
        r"\brmdir\s+/[sS]\b",
        r"shutil\.rmtree",
        # 系统修改
        r"\bregedit\b",
        r"\bbcdedit\b",
        r"\bformat\b\s+[a-zA-Z]:",
        r"\bmkfs\b",
        # 权限提升
        r"\bsudo\b",
        r"\brunas\b",
        r"\btakeown\b",
        r"\bicacls\b.*[/grant]",
    ],
    "warn": [
        # 网络外发
        r"\bcurl\b",
        r"\bwget\b",
        r"\bInvoke-WebRequest\b",
        # 批量操作
        r"\*\.tmp",
        r"\*\.log",
        r"\*\.bak",
        # 其他
        r"\bchmod\b\s+777",
        r"\bchown\b",
    ],
}

# ── 敏感目录 ─────────────────────────────────────────────

SENSITIVE_DIRS_WINDOWS = [
    "desktop", "downloads", "documents", "home",
    "appdata", "system32", "windows", "program files",
    "program files (x86)", "perflogs",
]

SENSITIVE_DIRS_UNIX = [
    "/system", "/usr/bin", "/usr/sbin", "/etc", "/var",
    "/root", "/boot", "/dev", "/proc", "/sys",
]

# ── 写操作工具 ─────────────────────────────────────────────

WRITE_TOOLS = {"Write", "Edit", "WriteFile", "EditFile", "Bash", "PowerShell"}
READ_TOOLS = {"Read", "Glob", "Grep", "GrepSearch", "GlobSearch", "WebSearch", "WebFetch"}


# ── 安全验证链 ─────────────────────────────────────────────

class ToolSafetyChain:
    """
    7 层工具执行安全验证链。
    
    借鉴 Claw Code 的 9 子模块 Bash 验证：
    sedValidation → pathValidation → readOnlyValidation → 
    destructiveCommandWarning → commandSemantics → bashPermissions → 
    bashSecurity → modeValidation → shouldUseSandbox
    
    天命精简为 7 层：
    L1 权限模式 → L2 路径安全 → L3 命令语义 → L4 沙箱决策 → 
    L5 输出限制 → L6 用户确认 → L7 执行监控
    """

    def __init__(
        self,
        permission_mode: str = "workspace-write",
        workspace_root: Optional[str] = None,
        max_output_chars: int = 20000,
        default_timeout: int = 120,
    ):
        """
        Args:
            permission_mode: 权限模式 ("read-only" / "workspace-write" / "full-access")
            workspace_root: 工作区根路径
            max_output_chars: 输出截断字符数
            default_timeout: 默认超时秒数
        """
        self.permission_mode = PermissionMode(permission_mode)
        self.workspace_root = workspace_root or os.getcwd()
        self.max_output_chars = max_output_chars
        self.default_timeout = default_timeout

    def validate(self, tool_name: str, args: Optional[Dict] = None) -> SafetyResult:
        """
        执行完整 7 层安全验证。
        
        Args:
            tool_name: 工具名称
            args: 工具参数字典
            
        Returns:
            SafetyResult 验证结果
        """
        args = args or {}
        result = SafetyResult(
            passed=True,
            verdict=Verdict.PASS,
            risk_level=RiskLevel.LOW,
        )
        command = args.get("command", "")
        file_path = args.get("file_path", args.get("path", ""))

        # L1: 权限模式检查
        l1 = self._check_permission_mode(tool_name)
        result.layers.append(l1)
        if l1.verdict == Verdict.BLOCK:
            return self._block(result, l1.message)

        # L2: 路径安全检查
        if file_path:
            l2 = self._check_path_safety(file_path)
            result.layers.append(l2)
            if l2.verdict == Verdict.BLOCK:
                return self._block(result, l2.message)

        # L3: 命令语义分析
        if command:
            l3 = self._check_command_safety(command)
            result.layers.append(l3)
            if l3.verdict == Verdict.BLOCK:
                return self._block(result, l3.message)
            if l3.verdict == Verdict.WARN:
                result.risk_level = RiskLevel.MEDIUM

        # L4: 沙箱决策
        l4 = self._check_sandbox_needed(tool_name, command, result.risk_level)
        result.layers.append(l4)
        result.needs_sandbox = l4.verdict == Verdict.WARN

        # L5: 输出大小限制
        result.output_truncate = True  # 默认启用截断

        # L6: 用户确认
        l6 = self._check_user_confirmation_needed(tool_name, command, result.risk_level)
        result.layers.append(l6)
        if l6.verdict == Verdict.NEED_CONFIRM:
            result.needs_user_confirm = True
            result.risk_level = RiskLevel.HIGH

        # L7: 执行监控参数
        l7 = self._set_execution_monitoring(command)
        result.layers.append(l7)

        # 最终结论
        if result.needs_user_confirm:
            result.verdict = Verdict.NEED_CONFIRM
        elif result.risk_level == RiskLevel.MEDIUM:
            result.verdict = Verdict.WARN
        else:
            result.verdict = Verdict.PASS

        return result

    # ── L1: 权限模式检查 ───────────────────────────────────

    def _check_permission_mode(self, tool_name: str) -> LayerResult:
        if self.permission_mode == PermissionMode.READ_ONLY:
            if tool_name in WRITE_TOOLS:
                return LayerResult(
                    layer=1, name="权限模式",
                    verdict=Verdict.BLOCK,
                    message=f"read-only 模式下禁止 {tool_name}",
                )
        return LayerResult(layer=1, name="权限模式", verdict=Verdict.PASS,
                          message=self.permission_mode.value)

    # ── L2: 路径安全检查 ───────────────────────────────────

    def _check_path_safety(self, file_path: str) -> LayerResult:
        # 路径遍历检测
        normalized = os.path.normpath(file_path)
        if ".." in normalized:
            return LayerResult(
                layer=2, name="路径安全",
                verdict=Verdict.BLOCK,
                message=f"路径遍历检测: {file_path}",
            )

        # 敏感目录检测
        path_lower = normalized.lower().replace("\\", "/")
        for sensitive in SENSITIVE_DIRS_WINDOWS + SENSITIVE_DIRS_UNIX:
            if sensitive.lower() in path_lower:
                # 检查是否在工作区内
                try:
                    abs_path = os.path.abspath(file_path)
                    abs_workspace = os.path.abspath(self.workspace_root)
                    if not abs_path.startswith(abs_workspace):
                        return LayerResult(
                            layer=2, name="路径安全",
                            verdict=Verdict.BLOCK,
                            message=f"访问工作区外敏感目录: {file_path}",
                        )
                except (OSError, ValueError):
                    pass

        return LayerResult(layer=2, name="路径安全", verdict=Verdict.PASS,
                          message="路径安全")

    # ── L3: 命令语义分析 ───────────────────────────────────

    def _check_command_safety(self, command: str) -> LayerResult:
        # 阻断级命令
        for pattern in DANGEROUS_COMMANDS["block"]:
            if re.search(pattern, command, re.IGNORECASE):
                return LayerResult(
                    layer=3, name="命令语义",
                    verdict=Verdict.BLOCK,
                    message=f"危险命令匹配: {pattern}",
                )

        # 警告级命令
        for pattern in DANGEROUS_COMMANDS["warn"]:
            if re.search(pattern, command, re.IGNORECASE):
                return LayerResult(
                    layer=3, name="命令语义",
                    verdict=Verdict.WARN,
                    message=f"需注意命令: {pattern}",
                )

        return LayerResult(layer=3, name="命令语义", verdict=Verdict.PASS,
                          message="命令安全")

    # ── L4: 沙箱决策 ───────────────────────────────────────

    def _check_sandbox_needed(self, tool_name: str, command: str,
                               risk: RiskLevel) -> LayerResult:
        if risk in (RiskLevel.HIGH, RiskLevel.BLOCKED):
            return LayerResult(
                layer=4, name="沙箱决策",
                verdict=Verdict.WARN,
                message="高风险操作，建议沙箱隔离",
            )
        return LayerResult(layer=4, name="沙箱决策", verdict=Verdict.PASS,
                          message="无需沙箱")

    # ── L6: 用户确认 ───────────────────────────────────────

    def _check_user_confirmation_needed(self, tool_name: str, command: str,
                                         risk: RiskLevel) -> LayerResult:
        # 外部 API 调用
        if any(kw in command.lower() for kw in ["curl", "wget", "invoke-webrequest"]):
            return LayerResult(
                layer=6, name="用户确认",
                verdict=Verdict.NEED_CONFIRM,
                message="网络外发操作需用户确认",
            )

        # 删除操作
        if any(kw in command.lower() for kw in ["rm ", "del ", "rmdir", "rmtree"]):
            return LayerResult(
                layer=6, name="用户确认",
                verdict=Verdict.NEED_CONFIRM,
                message="删除操作需用户确认",
            )

        if risk == RiskLevel.HIGH:
            return LayerResult(
                layer=6, name="用户确认",
                verdict=Verdict.NEED_CONFIRM,
                message="高风险操作需用户确认",
            )

        return LayerResult(layer=6, name="用户确认", verdict=Verdict.PASS,
                          message="无需确认")

    # ── L7: 执行监控 ───────────────────────────────────────

    def _set_execution_monitoring(self, command: str) -> LayerResult:
        timeout = self.default_timeout
        # 长命令给更长超时
        if len(command) > 500:
            timeout = min(timeout * 2, 600)
        return LayerResult(
            layer=7, name="执行监控",
            verdict=Verdict.PASS,
            message=f"超时: {timeout}s, 输出截断: {self.max_output_chars} chars",
        )

    # ── 辅助 ───────────────────────────────────────────────

    def _block(self, result: SafetyResult, reason: str) -> SafetyResult:
        result.passed = False
        result.verdict = Verdict.BLOCK
        result.risk_level = RiskLevel.BLOCKED
        result.block_reason = reason
        return result


# ── CLI 入口 ───────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    import json as json_mod

    parser = argparse.ArgumentParser(description="天命 Protocol 7 — 工具安全验证链")
    parser.add_argument("--tool", type=str, required=True, help="工具名称")
    parser.add_argument("--command", type=str, default="", help="Bash 命令")
    parser.add_argument("--file-path", type=str, default="", help="文件路径")
    parser.add_argument("--permission", type=str, default="workspace-write",
                        choices=["read-only", "workspace-write", "full-access"],
                        help="权限模式")
    parser.add_argument("--json", action="store_true", help="JSON 输出")

    args = parser.parse_args()

    chain = ToolSafetyChain(permission_mode=args.permission)
    tool_args = {}
    if args.command:
        tool_args["command"] = args.command
    if args.file_path:
        tool_args["file_path"] = args.file_path

    result = chain.validate(tool_name=args.tool, args=tool_args)

    if args.json:
        output = {
            "passed": result.passed,
            "verdict": result.verdict.value,
            "risk_level": result.risk_level.value,
            "needs_user_confirm": result.needs_user_confirm,
            "needs_sandbox": result.needs_sandbox,
            "block_reason": result.block_reason,
            "layers": [
                {"layer": lr.layer, "name": lr.name, "verdict": lr.verdict.value, "message": lr.message}
                for lr in result.layers
            ],
        }
        print(json_mod.dumps(output, indent=2, ensure_ascii=False))
    else:
        print(result.summary())
