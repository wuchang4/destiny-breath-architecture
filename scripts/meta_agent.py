#!/usr/bin/env python3
"""
天命架构 — Meta-Agent 动态调度系统
参考 Strands Agents 的 Meta-Agent 模式。

核心能力：
  - 总管Agent根据任务动态spawn临时子Agent
  - 子Agent自动分配工具、能力、生命周期
  - 执行完毕后自动销毁，资源回收
  - 支持固定编队（斥候/谋士/文官）+ 临时按需创建

用法：
    from meta_agent import MetaAgentOrchestrator
    orchestrator = MetaAgentOrchestrator()

    # 固定编队（保留天行军传统）
    orchestrator.spawn_scout("搜索AI最新动态")
    orchestrator.spawn_strategist("分析市场趋势")
    orchestrator.spawn_scribe("撰写报告")

    # 动态创建（v3新增）
    orchestrator.spawn_dynamic("调研XX公司技术栈", tools=["web_search", "file_read"])

    # 批量执行
    results = orchestrator.execute_all()
"""

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set
from enum import Enum


class AgentRole(Enum):
    """预定义角色（保留天行军传统）"""
    SCOUT = "斥候"           # 信息采集
    STRATEGIST = "谋士"      # 分析决策
    SCRIBE = "文官"          # 内容产出
    ORCHESTRATOR = "总管"    # 调度中心
    DYNAMIC = "动态"         # 按需创建


class AgentStatus(Enum):
    """子Agent生命周期状态"""
    CREATED = "created"       # 已创建
    RUNNING = "running"       # 执行中
    COMPLETED = "completed"   # 已完成
    FAILED = "failed"         # 失败
    DESTROYED = "destroyed"   # 已销毁


@dataclass
class AgentCapability:
    """Agent能力定义"""
    tools: List[str] = field(default_factory=list)        # 可用工具列表
    skills: List[str] = field(default_factory=list)        # 可用技能列表
    max_tool_calls: int = 20                               # 最大工具调用次数
    timeout_seconds: int = 300                             # 超时时间
    risk_level: str = "low"                                # 风险等级
    can_spawn_children: bool = False                       # 是否可以再spawn子Agent


@dataclass
class AgentTask:
    """子Agent任务定义"""
    task_id: str = ""
    description: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0   # 0=普通, 1=高, 2=紧急


@dataclass
class SubAgent:
    """子Agent实例"""
    agent_id: str = ""
    name: str = ""
    role: AgentRole = AgentRole.DYNAMIC
    status: AgentStatus = AgentStatus.CREATED
    capability: AgentCapability = field(default_factory=AgentCapability)
    task: AgentTask = field(default_factory=AgentTask)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: float = 0.0
    started_at: float = 0.0
    completed_at: float = 0.0
    tool_calls_made: int = 0
    parent_id: Optional[str] = None  # 父Agent ID（支持嵌套）

    @property
    def duration_ms(self) -> float:
        if self.started_at == 0:
            return 0
        end = self.completed_at or time.time()
        return (end - self.started_at) * 1000

    @property
    def is_alive(self) -> bool:
        return self.status in (AgentStatus.CREATED, AgentStatus.RUNNING)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "role": self.role.value,
            "status": self.status.value,
            "tools": self.capability.tools,
            "task": self.task.description,
            "duration_ms": round(self.duration_ms, 2),
            "tool_calls": self.tool_calls_made,
            "error": self.error,
        }


class MetaAgentOrchestrator:
    """
    Meta-Agent 调度器。

    核心职责：
    1. 根据任务需求动态创建子Agent
    2. 为子Agent分配合适的工具和能力
    3. 管理子Agent生命周期（创建→执行→销毁）
    4. 收集子Agent结果并合并
    5. 支持固定编队（天行军传统）+ 临时按需创建
    """

    # 预定义角色的能力模板
    ROLE_TEMPLATES = {
        AgentRole.SCOUT: AgentCapability(
            tools=["web_search", "web_fetch", "file_read"],
            skills=["search-hub", "multi-search-engine"],
            max_tool_calls=15,
            timeout_seconds=120,
            risk_level="low",
        ),
        AgentRole.STRATEGIST: AgentCapability(
            tools=["file_read", "file_write", "bash"],
            skills=["deep-research", "content-ops"],
            max_tool_calls=10,
            timeout_seconds=180,
            risk_level="low",
        ),
        AgentRole.SCRIBE: AgentCapability(
            tools=["file_read", "file_write"],
            skills=["content-创作中心", "khazix-writer", "insight-writer"],
            max_tool_calls=10,
            timeout_seconds=180,
            risk_level="low",
        ),
        AgentRole.ORCHESTRATOR: AgentCapability(
            tools=["file_read", "file_write", "bash", "web_search"],
            skills=[],
            max_tool_calls=30,
            timeout_seconds=600,
            risk_level="medium",
            can_spawn_children=True,
        ),
    }

    def __init__(self, orchestrator_id: Optional[str] = None):
        self.orchestrator_id = orchestrator_id or f"orch-{uuid.uuid4().hex[:8]}"
        self._agents: Dict[str, SubAgent] = {}
        self._results: List[Dict[str, Any]] = []
        self._handlers: Dict[str, Callable] = {}  # role -> handler function
        self._dynamic_handler: Optional[Callable] = None

    # ── Handler 注册 ──────────────────────────────────────

    def register_handler(self, role: AgentRole, handler: Callable):
        """
        注册角色处理器。handler(agent: SubAgent) -> Dict[str, Any]
        """
        self._handlers[role] = handler

    def register_dynamic_handler(self, handler: Callable):
        """
        注册动态Agent处理器。handler(agent: SubAgent) -> Dict[str, Any]
        用于处理所有非预定义角色的临时Agent。
        """
        self._dynamic_handler = handler

    # ── 固定编队（天行军传统）─────────────────────────────

    def spawn_scout(self, task: str, context: Optional[Dict] = None) -> SubAgent:
        """创建斥候Agent（信息采集）"""
        return self._spawn_agent(
            name="斥候",
            role=AgentRole.SCOUT,
            task=task,
            context=context,
        )

    def spawn_strategist(self, task: str, context: Optional[Dict] = None) -> SubAgent:
        """创建谋士Agent（分析决策）"""
        return self._spawn_agent(
            name="谋士",
            role=AgentRole.STRATEGIST,
            task=task,
            context=context,
        )

    def spawn_scribe(self, task: str, context: Optional[Dict] = None) -> SubAgent:
        """创建文官Agent（内容产出）"""
        return self._spawn_agent(
            name="文官",
            role=AgentRole.SCRIBE,
            task=task,
            context=context,
        )

    # ── 动态创建（Meta-Agent 核心）────────────────────────

    def spawn_dynamic(
        self,
        task: str,
        name: Optional[str] = None,
        tools: Optional[List[str]] = None,
        skills: Optional[List[str]] = None,
        max_tool_calls: int = 15,
        timeout_seconds: int = 300,
        risk_level: str = "low",
        context: Optional[Dict] = None,
        parent_id: Optional[str] = None,
    ) -> SubAgent:
        """
        动态创建临时Agent。

        Meta-Agent 的核心能力：根据任务自动分配工具和能力。

        Args:
            task: 任务描述
            name: Agent名称（默认从任务自动生成）
            tools: 可用工具列表（默认根据任务自动推断）
            skills: 可用技能列表（默认根据任务自动推断）
            max_tool_calls: 最大工具调用次数
            timeout_seconds: 超时时间
            risk_level: 风险等级
            context: 额外上下文
            parent_id: 父Agent ID（支持嵌套spawn）

        Returns:
            创建的子Agent实例
        """
        # 自动推断工具和技能
        if tools is None:
            tools = self._infer_tools(task)
        if skills is None:
            skills = self._infer_skills(task)
        if name is None:
            name = self._generate_agent_name(task)

        capability = AgentCapability(
            tools=tools,
            skills=skills,
            max_tool_calls=max_tool_calls,
            timeout_seconds=timeout_seconds,
            risk_level=risk_level,
        )

        return self._spawn_agent(
            name=name,
            role=AgentRole.DYNAMIC,
            task=task,
            context=context,
            capability=capability,
            parent_id=parent_id,
        )

    def _infer_tools(self, task: str) -> List[str]:
        """根据任务描述自动推断需要的工具。"""
        task_lower = task.lower()
        tools = ["file_read"]  # 基础工具

        # 搜索类
        if any(kw in task_lower for kw in ["搜索", "查找", "调研", "search", "find", "查"]):
            tools.extend(["web_search", "web_fetch"])

        # 写作类
        if any(kw in task_lower for kw in ["写", "撰写", "文章", "报告", "write", "报告"]):
            tools.extend(["file_write"])

        # 代码类
        if any(kw in task_lower for kw in ["代码", "脚本", "code", "script", "编程", "程序"]):
            tools.extend(["bash", "file_write"])

        # 分析类
        if any(kw in task_lower for kw in ["分析", "对比", "评估", "analyze", "compare"]):
            tools.extend(["file_read", "file_write"])

        # 浏览器类
        if any(kw in task_lower for kw in ["网页", "浏览器", "截屏", "web", "browser"]):
            tools.extend(["web_fetch"])

        return list(set(tools))

    def _infer_skills(self, task: str) -> List[str]:
        """根据任务描述自动推断需要的技能。"""
        task_lower = task.lower()
        skills = []

        if any(kw in task_lower for kw in ["搜索", "新闻", "热点", "search"]):
            skills.append("search-hub")

        if any(kw in task_lower for kw in ["写", "文章", "公众号", "内容"]):
            skills.append("content-创作中心")

        if any(kw in task_lower for kw in ["抖音", "视频", "短视频"]):
            skills.append("douyin-抖音作战中心")

        if any(kw in task_lower for kw in ["浏览器", "网页", "爬虫"]):
            skills.append("browser-浏览器总控")

        if any(kw in task_lower for kw in ["深度研究", "调研", "research"]):
            skills.append("deep-research")

        return skills

    def _generate_agent_name(self, task: str) -> str:
        """从任务描述生成Agent名称。"""
        # 取前10个字符作为名称
        clean = task.replace(" ", "").replace("，", "").replace("。", "")[:10]
        return f"动态-{clean}"

    # ── 内部方法 ──────────────────────────────────────────

    def _spawn_agent(
        self,
        name: str,
        role: AgentRole,
        task: str,
        context: Optional[Dict] = None,
        capability: Optional[AgentCapability] = None,
        parent_id: Optional[str] = None,
    ) -> SubAgent:
        """创建子Agent的内部方法。"""
        agent_id = f"{role.value}-{uuid.uuid4().hex[:8]}"

        if capability is None:
            capability = self.ROLE_TEMPLATES.get(role, AgentCapability())

        agent = SubAgent(
            agent_id=agent_id,
            name=name,
            role=role,
            status=AgentStatus.CREATED,
            capability=capability,
            task=AgentTask(
                task_id=f"task-{uuid.uuid4().hex[:8]}",
                description=task,
                context=context or {},
            ),
            created_at=time.time(),
            parent_id=parent_id,
        )

        self._agents[agent_id] = agent
        return agent

    # ── 执行 ──────────────────────────────────────────────

    def execute_agent(self, agent: SubAgent) -> Dict[str, Any]:
        """执行单个子Agent。"""
        agent.status = AgentStatus.RUNNING
        agent.started_at = time.time()

        try:
            # 查找处理器
            handler = self._handlers.get(agent.role)
            if handler is None and agent.role == AgentRole.DYNAMIC:
                handler = self._dynamic_handler

            if handler is None:
                raise ValueError(f"未注册 {agent.role.value} 角色的处理器")

            # 执行
            result = handler(agent)
            agent.result = result
            agent.status = AgentStatus.COMPLETED
            agent.completed_at = time.time()

            return {
                "agent_id": agent.agent_id,
                "name": agent.name,
                "role": agent.role.value,
                "status": "completed",
                "result": result,
                "duration_ms": agent.duration_ms,
            }

        except Exception as e:
            agent.error = str(e)
            agent.status = AgentStatus.FAILED
            agent.completed_at = time.time()

            return {
                "agent_id": agent.agent_id,
                "name": agent.name,
                "role": agent.role.value,
                "status": "failed",
                "error": str(e),
                "duration_ms": agent.duration_ms,
            }

    def execute_all(self, parallel: bool = False) -> List[Dict[str, Any]]:
        """
        执行所有已创建的子Agent。

        Args:
            parallel: 是否并行执行（默认顺序执行）

        Returns:
            所有Agent的执行结果列表
        """
        results = []

        if parallel:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {
                    executor.submit(self.execute_agent, agent): agent
                    for agent in self._agents.values()
                    if agent.is_alive
                }
                for future in as_completed(futures):
                    result = future.result(timeout=600)
                    results.append(result)
        else:
            for agent in list(self._agents.values()):
                if agent.is_alive:
                    result = self.execute_agent(agent)
                    results.append(result)

        self._results.extend(results)

        # 自动销毁已完成的Agent
        self._cleanup_destroyed()

        return results

    def _cleanup_destroyed(self):
        """清理已完成/失败的Agent（资源回收）。"""
        for agent_id, agent in list(self._agents.items()):
            if agent.status in (AgentStatus.COMPLETED, AgentStatus.FAILED):
                agent.status = AgentStatus.DESTROYED

    # ── 查询 ──────────────────────────────────────────────

    def get_agent(self, agent_id: str) -> Optional[SubAgent]:
        return self._agents.get(agent_id)

    def get_alive_agents(self) -> List[SubAgent]:
        return [a for a in self._agents.values() if a.is_alive]

    def get_all_agents(self) -> List[SubAgent]:
        return list(self._agents.values())

    def get_results(self) -> List[Dict[str, Any]]:
        return self._results

    def summary(self) -> str:
        """输出调度摘要。"""
        lines = [
            f"=== Meta-Agent 调度摘要 ===",
            f"调度器ID: {self.orchestrator_id}",
            f"总Agent数: {len(self._agents)}",
        ]

        by_role = {}
        for agent in self._agents.values():
            role = agent.role.value
            by_role.setdefault(role, []).append(agent)

        for role, agents in by_role.items():
            completed = sum(1 for a in agents if a.status == AgentStatus.COMPLETED)
            failed = sum(1 for a in agents if a.status == AgentStatus.FAILED)
            alive = sum(1 for a in agents if a.is_alive)
            lines.append(f"  {role}: {len(agents)}个 (完成{completed}, 失败{failed}, 存活{alive})")

        lines.append(f"\n执行结果: {len(self._results)}条")
        for r in self._results:
            icon = "✅" if r.get("status") == "completed" else "❌"
            lines.append(f"  {icon} {r['name']} ({r.get('duration_ms', 0):.1f}ms)")

        return "\n".join(lines)


# ── CLI 测试 ──────────────────────────────────────────────
if __name__ == "__main__":
    print("Meta-Agent 动态调度系统测试\n")

    orchestrator = MetaAgentOrchestrator()

    # 注册处理器
    def scout_handler(agent: SubAgent):
        time.sleep(0.05)
        return {"data": f"斥候采集: {agent.task.description}", "sources": 3}

    def strategist_handler(agent: SubAgent):
        time.sleep(0.03)
        return {"analysis": f"谋士分析: {agent.task.description}", "confidence": 0.85}

    def scribe_handler(agent: SubAgent):
        time.sleep(0.04)
        return {"output": f"文官产出: {agent.task.description}", "word_count": 1500}

    def dynamic_handler(agent: SubAgent):
        time.sleep(0.02)
        return {"result": f"动态Agent完成: {agent.task.description}", "tools_used": agent.capability.tools}

    orchestrator.register_handler(AgentRole.SCOUT, scout_handler)
    orchestrator.register_handler(AgentRole.STRATEGIST, strategist_handler)
    orchestrator.register_handler(AgentRole.SCRIBE, scribe_handler)
    orchestrator.register_dynamic_handler(dynamic_handler)

    # 1. 固定编队
    print("=== 固定编队（天行军传统）===")
    orchestrator.spawn_scout("搜索AI最新动态")
    orchestrator.spawn_strategist("分析AI Coding趋势")
    orchestrator.spawn_scribe("撰写AI日报")

    # 2. 动态创建
    print("=== 动态创建（Meta-Agent）===")
    orchestrator.spawn_dynamic("调研OpenAI Codex定价策略", tools=["web_search", "web_fetch", "file_write"])
    orchestrator.spawn_dynamic("对比Claude Code vs Cursor性能", skills=["deep-research"])
    orchestrator.spawn_dynamic("生成产品对比表格", name="表格生成器")

    # 执行所有
    print("\n=== 执行所有Agent ===")
    results = orchestrator.execute_all(parallel=True)

    print(f"\n{orchestrator.summary()}")

    # 3. 嵌套spawn测试
    print("\n=== 嵌套spawn测试 ===")
    orchestrator2 = MetaAgentOrchestrator("nested-test")
    orchestrator2.register_dynamic_handler(dynamic_handler)

    parent = orchestrator2.spawn_dynamic("总任务：调研矿山数字化", name="总调度")
    orchestrator2.spawn_dynamic("子任务1：搜索矿山传感器", parent_id=parent.agent_id)
    orchestrator2.spawn_dynamic("子任务2：分析矿山市场", parent_id=parent.agent_id)

    results2 = orchestrator2.execute_all()
    print(f"\n{orchestrator2.summary()}")
