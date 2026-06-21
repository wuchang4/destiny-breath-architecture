#!/usr/bin/env python3
"""
天命架构 — 确定性测试框架 v2 (Deterministic Test Framework)
借鉴 Claw Code 的 Mock Parity Harness。

v2 新增测试：
  - 三省图 v2: interrupt/resume + 执行追踪 + 原子检查点
  - 执行追踪器: span/trace 系统
  - 工具结果缓存: TTL + LRU 淘汰
  - 集成测试: 全链路联动（配置→路由→安全→图→追踪）

覆盖测试场景：
  - tool_safety_chain: 7 层安全验证链测试 (10 场景)
  - model_router: 模型路由层测试 (6 场景)
  - config_merger: 配置层次化合并测试 (7 场景)
  - province_graph: 三省图 State Graph v2 测试 (14 场景)
  - execution_tracer: 执行追踪器测试 (5 场景)
  - tool_result_cache: 工具结果缓存测试 (6 场景)
  - integration: 全链路集成测试 (3 场景)

用法：
    python -m pytest tests/ --verbose
    python tests/test_all.py              # 直接运行
"""

import sys
import os
import json
import tempfile
import time

# Windows terminals often default to GBK; make direct test runs deterministic.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 将 scripts 目录加入路径
PROJECT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SCRIPTS_DIR)


def test_tool_safety_chain():
    """测试 Protocol 7 工具安全验证链。"""
    from tool_safety_chain import ToolSafetyChain, Verdict, RiskLevel

    print("\n=== 测试 Protocol 7: 工具安全验证链 ===")

    chain = ToolSafetyChain(permission_mode="workspace-write")

    # 场景 1: read-only 模式下写操作应被阻断
    read_only_chain = ToolSafetyChain(permission_mode="read-only")
    result = read_only_chain.validate("Write", {"file_path": "test.txt"})
    assert not result.passed, "read-only 模式下 Write 应被阻断"
    assert result.verdict == Verdict.BLOCK
    print("  ✅ 场景 1: read-only 阻断写操作")

    # 场景 2: read-only 模式下读操作应通过
    result = read_only_chain.validate("Read", {"file_path": "test.txt"})
    assert result.passed, "read-only 模式下 Read 应通过"
    print("  ✅ 场景 2: read-only 允许读操作")

    # 场景 3: 危险命令应被阻断
    result = chain.validate("Bash", {"command": "rm -rf /"})
    assert not result.passed, "rm -rf / 应被阻断"
    print("  ✅ 场景 3: 危险命令 rm -rf 阻断")

    # 场景 4: 危险命令 regedit 应被阻断
    result = chain.validate("Bash", {"command": "regedit"})
    assert not result.passed, "regedit 应被阻断"
    print("  ✅ 场景 4: regedit 阻断")

    # 场景 5: 路径遍历应被阻断
    result = chain.validate("Read", {"file_path": "../../../etc/passwd"})
    assert not result.passed, "路径遍历应被阻断"
    print("  ✅ 场景 5: 路径遍历阻断")

    # 场景 6: 正常命令应通过
    result = chain.validate("Bash", {"command": "ls -la"})
    assert result.passed, "ls -la 应通过"
    print("  ✅ 场景 6: 正常命令通过")

    # 场景 7: curl 需要用户确认
    result = chain.validate("Bash", {"command": "curl https://example.com"})
    assert result.needs_user_confirm, "curl 应需要用户确认"
    print("  ✅ 场景 7: curl 需要用户确认")

    # 场景 8: full-access 模式下写操作应通过
    full_chain = ToolSafetyChain(permission_mode="full-access")
    result = full_chain.validate("Write", {"file_path": "test.txt"})
    assert result.passed, "full-access 模式下 Write 应通过"
    print("  ✅ 场景 8: full-access 允许写操作")

    # 场景 9: JSON 输出格式
    result = chain.validate("Bash", {"command": "ls"})
    assert result.passed
    assert result.risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM)
    print("  ✅ 场景 9: 正常命令的风险等级正确")

    # 场景 10: 结果 summary 可输出
    summary = result.summary()
    assert "L1" in summary and "结论" in summary
    print("  ✅ 场景 10: 结果 summary 可输出")

    print("  🎉 Protocol 7 全部 10 个测试通过！")


def test_model_router():
    """测试模型路由层。"""
    from model_router import ModelRouter

    print("\n=== 测试模型路由层 ===")

    # 创建临时 models.json
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump([
            {"id": "gemma4:e4b", "name": "Gemma 4 E4B", "url": "http://localhost:11434/v1/chat/completions",
             "supportsImages": True, "supportsToolCall": True},
            {"id": "deepseek-v4-flash", "name": "DeepSeek V4 Flash", "url": "https://api.deepseek.com",
             "supportsImages": True, "supportsToolCall": True},
            {"id": "mimo-v2.5", "name": "MiMo V2.5", "url": "https://token-plan-cn.xiaomimimo.com/v1",
             "supportsImages": True, "supportsToolCall": True},
            {"id": "mimo-v2.5-pro", "name": "MiMo V2.5 Pro", "url": "https://token-plan-cn.xiaomimimo.com/v1",
             "supportsImages": False, "supportsToolCall": True},
        ], f)
        tmp_path = f.name

    try:
        router = ModelRouter(models_json_path=tmp_path)

        # 场景 1: 别名解析
        assert router.resolve("fast") == "gemma4:e4b"
        assert router.resolve("smart") == "deepseek-v4-flash"
        assert router.resolve("multimodal") == "mimo-v2.5"
        assert router.resolve("coding") == "mimo-v2.5-pro"
        print("  ✅ 场景 1: 别名解析正确 (4个别名)")

        # 场景 2: 非别名直接返回
        assert router.resolve("gemma4:e4b") == "gemma4:e4b"
        assert router.resolve("some-custom-model") == "some-custom-model"
        print("  ✅ 场景 2: 非别名直接返回")

        # 场景 3: 任务类型自动选择
        assert router.auto_select("simple_qa") == "gemma4:e4b"
        assert router.auto_select("code_generation") == "deepseek-v4-flash"
        assert router.auto_select("image_analysis") == "mimo-v2.5"
        assert router.auto_select("long_running") == "mimo-v2.5-pro"
        assert router.auto_select("unknown_task") == "deepseek-v4-flash"
        print("  ✅ 场景 3: 任务类型自动选择正确 (5种任务)")

        # 场景 4: 降级策略
        fallback = router.FALLBACK_CHAIN.get("deepseek-v4-flash", [])
        assert "gemma4:e4b" in fallback
        fallback = router.FALLBACK_CHAIN.get("gemma4:e4b", [])
        assert fallback == []
        # mimo 系列应可降级到 deepseek 或本地
        assert "gemma4:e4b" in router.FALLBACK_CHAIN.get("mimo-v2.5", [])
        assert "gemma4:e4b" in router.FALLBACK_CHAIN.get("mimo-v2.5-pro", [])
        print("  ✅ 场景 4: 降级策略正确 (4个模型链)")

        # 场景 5: 别名列表
        aliases = router.list_aliases()
        assert len(aliases) >= 4
        print("  ✅ 场景 5: 别名列表完整")

        # 场景 6: 可用模型列表
        available = router.list_available()
        assert len(available) == 4
        print("  ✅ 场景 6: 可用模型列表正确")

        # 场景 7: 不可达模型不能被误判为可用
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as unavailable_file:
            json.dump([
                {"id": "offline-model", "name": "Offline", "url": "http://127.0.0.1:1/v1/chat/completions"}
            ], unavailable_file)
            unavailable_path = unavailable_file.name
        try:
            offline_router = ModelRouter(models_json_path=unavailable_path)
            assert offline_router.check_availability("offline-model", timeout=0.1) is False
            print("  ✅ 场景 7: 不可达模型判定为不可用")
        finally:
            os.unlink(unavailable_path)

    finally:
        os.unlink(tmp_path)

    print("  🎉 模型路由层全部 7 个测试通过！")


def test_config_merger():
    """测试配置层次化合并。"""
    from config_merger import ConfigMerger, deep_merge

    print("\n=== 测试配置层次化合并 ===")

    # 场景 1: 基础递归合并
    base = {"a": 1, "b": {"c": 2, "d": 3}, "e": [1, 2]}
    override = {"b": {"c": 99}, "e": [3, 4]}
    merged = deep_merge(base, override)
    assert merged["a"] == 1
    assert merged["b"]["c"] == 99
    assert merged["b"]["d"] == 3
    assert merged["e"] == [3, 4]
    print("  ✅ 场景 1: 基础递归合并正确")

    # 场景 2: 默认配置应有所有必需键
    merger = ConfigMerger()
    config = merger.merge()
    for key in ["model_aliases", "default_permission_mode", "memory", "heartbeat", "tool_safety", "evolution"]:
        assert key in config, f"缺少配置键: {key}"
    print("  ✅ 场景 2: 默认配置完整 (6个必需键)")

    # 场景 3: 默认值正确
    assert config["default_model"] == "smart"
    assert config["default_permission_mode"] == "workspace-write"
    assert config["language"] == "zh-CN"
    assert config["heartbeat"]["interval_hours"] == 4
    assert config["tool_safety"]["enabled"] == True
    print("  ✅ 场景 3: 默认值正确")

    # 场景 4: 运行时参数覆盖
    merger_with_args = ConfigMerger(runtime_args={"default_model": "fast"})
    config = merger_with_args.merge()
    assert config["default_model"] == "fast"
    print("  ✅ 场景 4: 运行时参数覆盖正确")

    # 场景 5: 嵌套覆盖不破坏其他键
    merger_nested = ConfigMerger(runtime_args={"memory": {"vector_search_threshold": 0.5}})
    config = merger_nested.merge()
    assert config["memory"]["vector_search_threshold"] == 0.5
    assert config["memory"]["max_context_tokens"] == 8192
    print("  ✅ 场景 5: 嵌套覆盖不破坏其他键")

    # 场景 6: dot-notation get
    merger = ConfigMerger()
    assert merger.get("memory.vector_search_threshold") == 0.25
    assert merger.get("heartbeat.enabled") == True
    assert merger.get("nonexistent.key", "default") == "default"
    print("  ✅ 场景 6: dot-notation get 正确")

    # 场景 7: diff_layers 返回各层快照
    layers = merger.diff_layers()
    assert len(layers) == 5
    print("  ✅ 场景 7: diff_layers 返回 5 层快照")

    print("  🎉 配置层次化合并全部 7 个测试通过！")


def test_province_graph():
    """测试三省图 State Graph v3。"""
    from province_graph import ProvinceGraph

    print("\n=== 测试三省图 State Graph v3 ===")

    # 场景 1: 创建图
    graph = ProvinceGraph()
    assert graph.current_node == "START"
    assert not graph.is_interrupted()
    print("  ✅ 场景 1: 图创建成功，当前节点 START")

    # 场景 2: START → 中书省（无条件）
    graph.step()
    assert graph.current_node == "中书省"
    print("  ✅ 场景 2: START → 中书省")

    # 场景 3: 中书省 → 门下省‖尚书省 → 执行节点（confidence ≥ 0.6）
    graph.step({"confidence": 0.8})
    assert graph.current_node == "执行节点"
    assert "[门下省‖尚书省]" in graph.node_history
    print("  ✅ 场景 3: v3 并行组执行并合并到执行节点 (confidence=0.8)")

    # 场景 4: 默认并行节点会给出路由规划
    assert graph.state["risk_level"] == "low"
    assert graph.state["route"] == "default"
    print("  ✅ 场景 4: 并行 reducer 合并风险与路由状态")

    # 场景 5: 执行节点 → AAR/Checkpt
    graph.step()
    assert graph.current_node == "AAR/Checkpt"
    print("  ✅ 场景 5: 执行节点 → AAR/Checkpt")

    # 场景 6: AAR/Checkpt → END
    graph.step()
    assert graph.current_node == "END"
    assert graph.is_finished()
    print("  ✅ 场景 6: AAR/Checkpt → END")

    # 场景 7: 低置信度走澄清分支
    g2 = ProvinceGraph()
    g2.step()
    g2.step({"confidence": 0.3})
    assert g2.current_node == "澄清分支"
    print("  ✅ 场景 7: 低置信度走澄清分支 (confidence=0.3)")

    # 场景 8: 高风险在 v3 并行路径后仍会触发中断
    g3 = ProvinceGraph()
    g3.step()
    g3.step({"confidence": 0.9, "risk_level": "high"})
    assert g3.current_node == "阻断/预警"
    assert g3.is_interrupted(), "高风险应触发中断"
    assert "用户确认" in g3.get_interrupt_reason()
    print("  ✅ 场景 8: 高风险触发中断 (v3 并行路径)")

    # 场景 9: 中断后恢复
    g3.resume({"user_confirmed": True})
    assert not g3.is_interrupted()
    g3.step()
    assert g3.is_finished()
    print("  ✅ 场景 9: 中断后恢复执行")

    # 场景 10: 重置
    graph.reset()
    assert graph.current_node == "START"
    assert not graph.is_finished()
    assert not graph.is_interrupted()
    print("  ✅ 场景 10: 图重置成功")

    # 场景 11: 执行追踪
    g4 = ProvinceGraph()
    g4.step()
    g4.step({"confidence": 0.8})
    trace = g4.trace
    assert len(trace.spans) > 0, "应有执行 span"
    print("  ✅ 场景 11: 执行追踪记录 span")

    # 场景 12: 序列化/反序列化
    data = g4.serialize()
    assert data["version"] == 3
    assert "current_node" in data
    assert "state" in data
    g5 = ProvinceGraph.deserialize(data)
    assert g5.current_node == g4.current_node
    print("  ✅ 场景 12: 序列化/反序列化 (v3)")

    # 场景 13: run() 自动执行
    g6 = ProvinceGraph()
    g6.run()
    assert g6.is_finished()
    print("  ✅ 场景 13: run() 自动执行到 END")

    print("  🎉 三省图 v3 全部 13 个测试通过！")


def test_execution_tracer():
    """测试执行追踪器（v2 新增）。"""
    from execution_tracer import ExecutionTracer

    print("\n=== 测试执行追踪器 ===")

    # 场景 1: span 上下文管理器
    tracer = ExecutionTracer("test-001")
    with tracer.span("中书省") as s:
        s.set_attribute("confidence", 0.8)
        s.add_event("parsed", {"intent": "测试"})
    assert len(tracer.spans) == 1
    assert tracer.spans[0].status == "ok"
    assert tracer.spans[0].attributes["confidence"] == 0.8
    print("  ✅ 场景 1: span 上下文管理器")

    # 场景 2: 嵌套 span
    with tracer.span("门下省") as s:
        s.set_attribute("risk", "low")
        with tracer.span("记忆检索") as inner:
            inner.set_attribute("hits", 3)
    assert len(tracer.spans) == 3
    # 内层 span 的 parent 应该是外层
    assert tracer.spans[2].parent_id == tracer.spans[1].span_id
    print("  ✅ 场景 2: 嵌套 span (parent 链)")

    # 场景 3: 错误捕获
    try:
        with tracer.span("出错节点") as s:
            raise ValueError("测试错误")
    except ValueError:
        pass
    error_span = tracer.spans[-1]
    assert error_span.status == "error"
    assert "error" in error_span.attributes
    print("  ✅ 场景 3: 错误 span 状态标记")

    # 场景 4: summary 输出
    summary = tracer.summary()
    assert "test-001" in summary
    assert "中书省" in summary
    assert "总耗时" in summary
    print("  ✅ 场景 4: summary 输出正确")

    # 场景 5: JSON 导出
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        tmp_path = f.name
    try:
        tracer.export_json(tmp_path)
        with open(tmp_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["task_id"] == "test-001"
        assert len(data["spans"]) == 4
        print("  ✅ 场景 5: JSON 导出正确")
    finally:
        os.unlink(tmp_path)

    print("  🎉 执行追踪器全部 5 个测试通过！")


def test_tool_result_cache():
    """测试工具结果缓存（v2 新增）。"""
    from tool_result_cache import ToolResultCache

    print("\n=== 测试工具结果缓存 ===")

    # 使用临时目录
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = ToolResultCache(cache_dir=tmpdir)

        # 场景 1: 写入并读取
        cache.put("WebSearch", "测试查询", {"results": ["a", "b"]})
        result = cache.get("WebSearch", "测试查询")
        assert result is not None
        assert result["results"] == ["a", "b"]
        print("  ✅ 场景 1: 写入并读取缓存")

        # 场景 2: 不同查询不命中
        result = cache.get("WebSearch", "其他查询")
        assert result is None
        print("  ✅ 场景 2: 不同查询不命中")

        # 场景 3: 不同工具不命中
        result = cache.get("WebFetch", "测试查询")
        assert result is None
        print("  ✅ 场景 3: 不同工具不命中")

        # 场景 4: 手动失效
        cache.invalidate("WebSearch", "测试查询")
        result = cache.get("WebSearch", "测试查询")
        assert result is None
        print("  ✅ 场景 4: 手动失效")

        # 场景 5: 缓存统计
        cache.put("WebSearch", "查询1", "结果1")
        cache.put("WebFetch", "http://example.com", "页面内容")
        stats = cache.stats()
        assert stats["total"] == 2
        assert "WebSearch" in stats["by_tool"]
        assert "WebFetch" in stats["by_tool"]
        print("  ✅ 场景 5: 缓存统计正确")

        # 场景 6: 清空
        cache.clear()
        stats = cache.stats()
        assert stats["total"] == 0
        print("  ✅ 场景 6: 清空缓存")

    print("  🎉 工具结果缓存全部 6 个测试通过！")


def test_integration():
    """集成测试：全链路联动。"""
    from model_router import ModelRouter
    from tool_safety_chain import ToolSafetyChain
    from config_merger import ConfigMerger
    from province_graph import ProvinceGraph
    from execution_tracer import ExecutionTracer
    from destiny_engine import parse_tool_args

    print("\n=== 全链路集成测试 ===")

    # 场景 0: CLI 参数解析兼容 JSON 与 KEY=VALUE
    parsed_args = parse_tool_args('{"query":"AI"}', ["limit=3", "fresh=true"])
    assert parsed_args == {"query": "AI", "limit": 3, "fresh": True}
    print("  ✅ 场景 0: CLI 参数解析兼容 JSON 与 KEY=VALUE")

    # 场景 1: 配置 → 安全链 → 图 → 追踪
    merger = ConfigMerger()
    config = merger.merge()
    chain = ToolSafetyChain(
        permission_mode=config["default_permission_mode"],
        max_output_chars=config["tool_safety"]["max_output_chars"],
    )

    tracer = ExecutionTracer("integration-test")
    graph = ProvinceGraph()

    # 模拟完整流程
    with tracer.span("中书省") as s:
        s.set_attribute("confidence", 0.85)
        graph.step({"confidence": 0.85})

    with tracer.span("门下省") as s:
        # 安全检查
        safety = chain.validate("Bash", {"command": "git status"})
        assert safety.passed
        s.set_attribute("risk_level", "low")
        graph.step({"risk_level": "low"})

    assert graph.current_node == "执行节点"
    assert "[门下省‖尚书省]" in graph.node_history
    print("  ✅ 场景 1: 配置→安全链→v3并行图→追踪 全链路")

    # 场景 2: 模型路由 + 安全链 + 中断恢复
    router = ModelRouter()
    model = router.auto_select("image_analysis")
    assert "mimo" in model.lower()

    danger_result = chain.validate("Bash", {"command": "sudo rm -rf /"})
    assert not danger_result.passed
    print("  ✅ 场景 2: 模型路由 + 安全链联动")

    # 场景 3: 高风险路径触发中断 → 用户确认 → 恢复
    g = ProvinceGraph()
    g.step()
    g.step({"confidence": 0.9, "risk_level": "high"})
    assert g.is_interrupted()
    g.resume({"user_confirmed": True})
    g.step()
    assert g.is_finished()
    print("  ✅ 场景 3: 中断→确认→恢复→完成")

    # 追踪摘要
    print(f"\n{tracer.summary()}")

    print("  🎉 全链路集成测试 4 个场景全部通过！")


def test_public_runtime_api():
    """测试公开 Runtime API（生产级嵌入入口）。"""
    import tomllib
    from destiny import FunctionTool, HttpGetTool, Runtime, RuntimeConfig, RunStatus, __version__
    from scripts.execution_tracer import DESTINY_VERSION

    print("\n=== 测试公开 Runtime API ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        def echo(args, context):
            return {"echo": args["message"], "history": context["node_history"]}

        runtime = Runtime.from_config(
            RuntimeConfig(workspace_root=tmpdir, state_dir=os.path.join(tmpdir, ".destiny")),
            tools=[
                FunctionTool(
                    name="Echo",
                    required=("message",),
                    handler=echo,
                    description="Echo one message.",
                )
            ],
        )

        result = runtime.run(
            task="echo message",
            tool_name="Echo",
            tool_args={"message": "hello"},
            run_id="test-runtime",
        )
        assert result.status == RunStatus.SUCCEEDED
        assert result.tool_results["Echo"].ok
        assert result.tool_results["Echo"].data["echo"] == "hello"
        state_dir = os.path.join(tmpdir, ".destiny")
        assert os.path.exists(os.path.join(state_dir, "runs", "test-runtime.json"))
        assert os.path.exists(os.path.join(state_dir, "audit.jsonl"))
        assert result.trace_path and os.path.abspath(result.trace_path).startswith(os.path.abspath(state_dir))
        assert os.path.exists(os.path.join(state_dir, "checkpoints", "province_graph.json"))
        assert os.path.exists(os.path.join(state_dir, "checkpoints", "destiny_engine.json"))

        cache_probe = runtime.run(
            task="cache probe",
            tool_name="WebSearch",
            tool_args={"query": "runtime cache probe"},
            run_id="cache-probe",
        )
        assert cache_probe.status == RunStatus.SUCCEEDED
        assert os.path.exists(os.path.join(state_dir, "cache", "tool_results.json"))
        print("  ✅ 场景 1: 注册工具执行并持久化 run/audit")

        missing_tool = runtime.run(
            task="missing tool",
            tool_name="NotRegistered",
            tool_args={},
            run_id="missing-tool",
        )
        assert missing_tool.status == RunStatus.SUCCEEDED
        assert not missing_tool.tool_results["NotRegistered"].ok
        assert "not registered" in missing_tool.tool_results["NotRegistered"].error
        print("  ✅ 场景 2: 未注册工具返回可解释结果")

        invalid_args = runtime.run(
            task="bad args",
            tool_name="Echo",
            tool_args={},
            run_id="bad-args",
        )
        assert not invalid_args.tool_results["Echo"].ok
        assert "missing required" in invalid_args.tool_results["Echo"].error
        print("  ✅ 场景 3: 工具参数校验错误被标准化")

        assert runtime.list_tools() == ["Echo"]
        assert runtime.get_tool("Echo") is not None
        manifest = runtime.tool_manifest()
        assert manifest[0]["name"] == "Echo"
        assert manifest[0]["schema"]["required"] == ["message"]
        function_manifest = runtime.tool_manifest(format="function")
        assert function_manifest[0]["type"] == "function"
        assert function_manifest[0]["function"]["name"] == "Echo"
        try:
            runtime.tool_manifest(format="unknown")
            assert False, "非法 manifest format 应报错"
        except ValueError as e:
            assert "format" in str(e)
        print("  ✅ 场景 4: Runtime 可导出稳定工具注册表和 manifest")

        with open(os.path.join(PROJECT_ROOT, "pyproject.toml"), "rb") as f:
            project = tomllib.load(f)
        assert project["project"]["version"] == __version__
        assert DESTINY_VERSION == __version__
        assert HttpGetTool().user_agent.endswith(f"/{__version__}")
        print("  ✅ 场景 5: 包版本、trace version 与工具 User-Agent 保持一致")

    print("  🎉 公开 Runtime API 5 个场景全部通过！")


def test_standard_tool_adapters():
    """测试标准工具 Adapter。"""
    import http.server
    import threading
    from destiny import (
        FileReadTool,
        FileWriteTool,
        HttpGetTool,
        Runtime,
        RuntimeConfig,
        RunStatus,
        ShellCommandTool,
        standard_tools,
    )

    print("\n=== 测试标准工具 Adapter ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        runtime = Runtime.from_config(
            RuntimeConfig(workspace_root=tmpdir, state_dir=os.path.join(tmpdir, ".destiny")),
            tools=[FileWriteTool(), FileReadTool(), ShellCommandTool()],
        )

        write_result = runtime.run(
            "write file",
            tool_name="WriteFile",
            tool_args={"path": "notes/out.txt", "content": "adapter file content"},
            run_id="adapter-write",
        )
        assert write_result.tool_results["WriteFile"].ok
        read_result = runtime.run(
            "read file",
            tool_name="Read",
            tool_args={"path": "notes/out.txt"},
            run_id="adapter-read",
        )
        assert read_result.tool_results["Read"].ok
        assert read_result.tool_results["Read"].data["content"] == "adapter file content"
        print("  ✅ 场景 1: FileWriteTool/FileReadTool 可通过 Runtime 写读工作区文件")

        readonly_runtime = Runtime.from_config(
            RuntimeConfig(
                workspace_root=tmpdir,
                state_dir=os.path.join(tmpdir, ".readonly"),
                permission_mode="read-only",
            ),
            tools=[FileWriteTool()],
        )
        blocked_write = readonly_runtime.run(
            "blocked write",
            tool_name="WriteFile",
            tool_args={"path": "blocked.txt", "content": "no"},
            run_id="blocked-write",
        )
        assert blocked_write.status == RunStatus.INTERRUPTED
        assert not blocked_write.tool_results["WriteFile"].ok
        assert blocked_write.tool_results["WriteFile"].metadata["stage"] == "orchestration"
        print("  ✅ 场景 2: read-only Runtime 阻断写入 Adapter")

        outside_path = os.path.abspath(os.path.join(tmpdir, "..", "outside.txt"))
        direct_read = FileReadTool().execute({"path": outside_path}, {"workspace_root": tmpdir})
        assert not direct_read.ok
        assert "escapes workspace" in direct_read.error
        print("  ✅ 场景 3: Adapter 自身阻断工作区外路径")

        command = f'"{sys.executable}" -c "print(\'adapter-ok\')"'
        shell_result = runtime.run(
            "run safe shell command",
            tool_name="Bash",
            tool_args={"command": command, "timeout": 5},
            run_id="adapter-shell",
        )
        assert shell_result.tool_results["Bash"].ok
        assert "adapter-ok" in shell_result.tool_results["Bash"].data["stdout"]
        print("  ✅ 场景 4: ShellCommandTool 可执行安全命令并捕获输出")

        blocked_http = HttpGetTool().execute({"url": "http://127.0.0.1:1"}, {"workspace_root": tmpdir})
        assert not blocked_http.ok
        assert "private or local host" in blocked_http.error
        print("  ✅ 场景 5: HttpGetTool 默认阻断 private/local host")

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"adapter-http-ok")

            def log_message(self, format, *args):
                return

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/"
            http_runtime = Runtime.from_config(
                RuntimeConfig(workspace_root=tmpdir, state_dir=os.path.join(tmpdir, ".http")),
                tools=[HttpGetTool(allow_private_hosts=True)],
            )
            http_result = http_runtime.run(
                "fetch local fixture",
                tool_name="WebFetch",
                tool_args={"url": url, "timeout": 5, "max_bytes": 1000},
                run_id="adapter-http",
            )
            assert http_result.tool_results["WebFetch"].ok
            assert http_result.tool_results["WebFetch"].data["content"] == "adapter-http-ok"
            print("  ✅ 场景 6: HttpGetTool 显式允许时可抓取本地测试服务")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        default_tool_names = {tool.name for tool in standard_tools()}
        assert default_tool_names == {"Read", "WriteFile"}
        expanded_tool_names = {tool.name for tool in standard_tools(shell=True, http=True)}
        assert {"Read", "WriteFile", "Bash", "WebFetch"} <= expanded_tool_names
        print("  ✅ 场景 7: standard_tools 默认保守，shell/http 显式启用")

    print("  🎉 标准工具 Adapter 7 个场景全部通过！")


def test_runtime_config_file():
    """测试 destiny.toml 配置加载。"""
    from destiny import Runtime, RuntimeConfig, SqliteVectorMemoryProvider, VectorMemoryProvider

    print("\n=== 测试 Runtime TOML 配置 ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "destiny.toml")
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(
                "\n".join([
                    "[runtime]",
                    f"workspace_root = {json.dumps(tmpdir)}",
                    'state_dir = ".custom-state"',
                    'permission_mode = "read-only"',
                    "audit_log = false",
                    "persist_runs = false",
                    'default_risk_level = "medium"',
                    'memory_backend = "vector"',
                ])
            )

        config = RuntimeConfig.from_file(config_path)
        assert config.workspace_root == tmpdir
        assert config.state_dir == ".custom-state"
        assert config.permission_mode == "read-only"
        assert config.audit_log is False
        assert config.persist_runs is False
        assert config.default_risk_level == "medium"
        assert config.memory_backend == "vector"
        runtime = Runtime.from_config(config_path)
        assert runtime.config.permission_mode == "read-only"
        assert isinstance(runtime.memory_provider, VectorMemoryProvider)
        print("  ✅ 场景 1: 从 [runtime] TOML 加载配置")

        default_state_path = os.path.join(tmpdir, "default-state.toml")
        with open(default_state_path, "w", encoding="utf-8") as f:
            f.write('permission_mode = "workspace-write"\n')
        default_config = RuntimeConfig.from_file(default_state_path)
        assert default_config.state_dir == os.path.join(tmpdir, ".destiny")
        print("  ✅ 场景 2: 未设置 state_dir 时相对配置文件目录生成 .destiny")

        bad_key_path = os.path.join(tmpdir, "bad-key.toml")
        with open(bad_key_path, "w", encoding="utf-8") as f:
            f.write("[runtime]\nunknown = true\n")
        try:
            RuntimeConfig.from_file(bad_key_path)
            assert False, "未知键应报错"
        except ValueError as e:
            assert "unknown runtime config keys" in str(e)
        print("  ✅ 场景 3: 未知配置键会报错")

        bad_value_path = os.path.join(tmpdir, "bad-value.toml")
        with open(bad_value_path, "w", encoding="utf-8") as f:
            f.write('[runtime]\npermission_mode = "root"\n')
        try:
            RuntimeConfig.from_file(bad_value_path)
            assert False, "非法 permission_mode 应报错"
        except ValueError as e:
            assert "permission_mode" in str(e)
        print("  ✅ 场景 4: 非法枚举值会报错")

        bad_memory_backend_path = os.path.join(tmpdir, "bad-memory-backend.toml")
        with open(bad_memory_backend_path, "w", encoding="utf-8") as f:
            f.write('[runtime]\nmemory_backend = "remote"\n')
        try:
            RuntimeConfig.from_file(bad_memory_backend_path)
            assert False, "非法 memory_backend 应报错"
        except ValueError as e:
            assert "memory_backend" in str(e)
        print("  ✅ 场景 5: 非法 memory backend 会报错")

        sqlite_config = RuntimeConfig.from_mapping({
            "workspace_root": tmpdir,
            "state_dir": os.path.join(tmpdir, ".sqlite-memory"),
            "memory_backend": "sqlite-vector",
        })
        sqlite_runtime = Runtime.from_config(sqlite_config)
        assert isinstance(sqlite_runtime.memory_provider, SqliteVectorMemoryProvider)
        sqlite_runtime.close()
        print("  ✅ 场景 6: sqlite-vector memory backend 可通过 RuntimeConfig 启用")

    print("  🎉 Runtime TOML 配置 6 个场景全部通过！")


def test_agent_enhancement_api():
    """测试智能体增强 API。"""
    from destiny import AgentPlan, FunctionTool, Runtime, RuntimeConfig, RunStatus

    print("\n=== 测试智能体增强 API ===")

    class DemoAgent:
        name = "demo-agent"

        def plan(self, task, context):
            return AgentPlan(
                task=task,
                tool_name="Echo",
                tool_args={"message": task, "agent": context["agent_name"]},
                rationale="echo through guarded runtime",
            )

        def reflect(self, plan, run, context):
            result = run.tool_results[plan.tool_name]
            return {
                "status": run.status.value,
                "ok": result.ok,
                "payload": result.data,
                "rationale": plan.rationale,
            }

    with tempfile.TemporaryDirectory() as tmpdir:
        def echo(args, context):
            return {"message": args["message"], "agent": args["agent"], "nodes": context["node_history"]}

        runtime = Runtime.from_config(
            RuntimeConfig(workspace_root=tmpdir, state_dir=os.path.join(tmpdir, ".destiny")),
            tools=[FunctionTool(name="Echo", required=("message", "agent"), handler=echo)],
        )
        enhanced = runtime.enhance(DemoAgent())
        outcome = enhanced.run("improve this agent", run_id="enhanced-agent")

        assert outcome.run.status == RunStatus.SUCCEEDED
        assert outcome.plan.tool_name == "Echo"
        assert outcome.answer["ok"] is True
        assert outcome.answer["payload"]["agent"] == "demo-agent"
        assert "执行节点" in outcome.answer["payload"]["nodes"]
        assert os.path.exists(os.path.join(tmpdir, ".destiny", "runs", "enhanced-agent.json"))
        print("  ✅ 场景 1: AgentAdapter 被 Runtime 增强并完成工具执行/反思")

        class BadAgent:
            name = "bad-agent"

            def plan(self, task, context):
                return {"not": "a plan"}

            def reflect(self, plan, run, context):
                return None

        bad = runtime.enhance(BadAgent())
        try:
            bad.run("bad")
            assert False, "非 AgentPlan 应报错"
        except TypeError as e:
            assert "AgentPlan" in str(e)
        print("  ✅ 场景 2: 非结构化 plan 会被拒绝")

    print("  🎉 智能体增强 API 2 个场景全部通过！")


def test_benchmark_api():
    """测试增强智能体评估 API。"""
    from destiny import AgentPlan, Benchmark, EvalCase, FunctionTool, Runtime, RuntimeConfig, RunStatus

    print("\n=== 测试 Benchmark API ===")

    class EvalAgent:
        name = "eval-agent"

        def plan(self, task, context):
            return AgentPlan(
                task=task,
                tool_name=context.get("tool", "Echo"),
                tool_args=context.get("tool_args", {"message": task}),
                risk_level=context.get("risk_level"),
            )

        def reflect(self, plan, run, context):
            return {"status": run.status.value, "tool": plan.tool_name}

    with tempfile.TemporaryDirectory() as tmpdir:
        def echo(args, context):
            return {"message": args["message"], "path": context["node_history"]}

        runtime = Runtime.from_config(
            RuntimeConfig(workspace_root=tmpdir, state_dir=os.path.join(tmpdir, ".destiny")),
            tools=[FunctionTool(name="Echo", required=("message",), handler=echo)],
        )
        agent = runtime.enhance(EvalAgent())
        benchmark = Benchmark([
            EvalCase(
                name="echo-success",
                task="hello",
                expect_tool="Echo",
                judge=lambda outcome, case: outcome.run.tool_results["Echo"].data["message"] == "hello",
            ),
            EvalCase(
                name="danger-blocked",
                task="delete root",
                context={"tool": "Bash", "tool_args": {"command": "rm -rf /"}},
                expect_status=RunStatus.INTERRUPTED,
                expect_tool="Bash",
            ),
        ])
        report = benchmark.run(agent)
        assert report.total == 2
        assert report.passed == 2
        assert report.failed == 0
        assert report.interrupted == 1
        assert report.tool_success_rate == 1.0
        assert "2/2 passed" in report.summary()
        print("  ✅ 场景 1: Benchmark 汇总成功率/中断/工具成功率")

        bad_benchmark = Benchmark([
            EvalCase(
                name="wrong-tool",
                task="hello",
                expect_tool="Missing",
            )
        ])
        bad_report = bad_benchmark.run(agent)
        assert bad_report.failed == 1
        assert bad_report.success_rate == 0.0
        print("  ✅ 场景 2: Benchmark 能识别失败用例")

    print("  🎉 Benchmark API 2 个场景全部通过！")


def test_enhancement_hooks():
    """测试可插拔增强 hooks。"""
    from destiny import AgentPlan, FunctionTool, RecordingHook, Runtime, RuntimeConfig

    print("\n=== 测试 Enhancement Hooks ===")

    class HookAgent:
        name = "hook-agent"

        def plan(self, task, context):
            return AgentPlan(task=task, tool_name="Echo", tool_args={"message": task})

        def reflect(self, plan, run, context):
            return run.tool_results[plan.tool_name].data

    with tempfile.TemporaryDirectory() as tmpdir:
        def echo(args, context):
            return {"message": args["message"]}

        hook = RecordingHook()
        runtime = Runtime.from_config(
            RuntimeConfig(workspace_root=tmpdir, state_dir=os.path.join(tmpdir, ".destiny")),
            tools=[FunctionTool(name="Echo", required=("message",), handler=echo)],
            hooks=[hook],
        )
        outcome = runtime.enhance(HookAgent()).run("hook task", run_id="hook-run")

        assert outcome.answer["message"] == "hook task"
        event_names = [event for event, _ in hook.events]
        expected = [
            "before_plan",
            "after_plan",
            "before_run",
            "before_tool",
            "after_tool",
            "after_run",
            "before_reflect",
            "after_reflect",
        ]
        for event in expected:
            assert event in event_names, f"missing hook event: {event}"
        assert event_names.index("before_plan") < event_names.index("after_plan")
        assert event_names.index("before_tool") < event_names.index("after_tool")
        print("  ✅ 场景 1: hooks 覆盖 plan/run/tool/reflect 生命周期")

        second_hook = RecordingHook(name="second")
        runtime.register_hook(second_hook)
        runtime.run("direct runtime", tool_name="Echo", tool_args={"message": "direct"}, run_id="direct-hook")
        assert any(event == "before_run" for event, _ in second_hook.events)
        print("  ✅ 场景 2: Runtime 可动态注册 hook")

    print("  🎉 Enhancement Hooks 2 个场景全部通过！")


def test_policy_hook():
    """测试策略 hook 的阻断能力。"""
    from destiny import FunctionTool, PolicyHook, RecordingHook, Runtime, RuntimeConfig, RunStatus

    print("\n=== 测试 Policy Hook ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        executed = {"count": 0}

        def echo(args, context):
            executed["count"] += 1
            return {"message": args["message"]}

        runtime = Runtime.from_config(
            RuntimeConfig(workspace_root=tmpdir, state_dir=os.path.join(tmpdir, ".destiny")),
            tools=[FunctionTool(name="Echo", required=("message",), handler=echo)],
            hooks=[PolicyHook(denied_task_keywords={"forbidden"})],
        )

        blocked_run = runtime.run("this is forbidden", tool_name="Echo", tool_args={"message": "nope"}, run_id="blocked")
        assert blocked_run.status == RunStatus.FAILED
        assert blocked_run.current_node == "POLICY_BLOCKED"
        assert "policy blocked" in blocked_run.errors[0]
        assert executed["count"] == 0
        assert os.path.exists(os.path.join(tmpdir, ".destiny", "runs", "blocked.json"))
        print("  ✅ 场景 1: before_run 策略阻断返回标准 RunResult")

        recording = RecordingHook()
        tool_policy_runtime = Runtime.from_config(
            RuntimeConfig(workspace_root=tmpdir, state_dir=os.path.join(tmpdir, ".destiny2")),
            tools=[FunctionTool(name="Echo", required=("message",), handler=echo)],
            hooks=[PolicyHook(denied_tools={"Echo"}), recording],
        )
        tool_blocked = tool_policy_runtime.run(
            "allowed task",
            tool_name="Echo",
            tool_args={"message": "blocked tool"},
            run_id="tool-blocked",
        )
        assert tool_blocked.status == RunStatus.SUCCEEDED
        assert not tool_blocked.tool_results["Echo"].ok
        assert "policy blocked" in tool_blocked.tool_results["Echo"].error
        assert executed["count"] == 0
        assert any(event == "after_tool" for event, _ in recording.events)
        print("  ✅ 场景 2: before_tool 策略阻断返回标准 ToolResult")

        risk_runtime = Runtime.from_config(
            RuntimeConfig(workspace_root=tmpdir, state_dir=os.path.join(tmpdir, ".destiny3")),
            hooks=[PolicyHook(max_risk_level="medium")],
        )
        high_risk = risk_runtime.run("high risk task", risk_level="high", run_id="high-risk")
        assert high_risk.status == RunStatus.FAILED
        assert "risk level denied" in high_risk.errors[0]
        print("  ✅ 场景 3: 风险等级策略阻断生效")

    print("  🎉 Policy Hook 3 个场景全部通过！")


def test_provider_api():
    """测试模型/记忆 Provider API。"""
    from destiny import (
        AgentPlan,
        FileMemoryProvider,
        HashEmbeddingProvider,
        FunctionTool,
        KeywordMemoryProvider,
        Runtime,
        RuntimeConfig,
        SqliteVectorMemoryProvider,
        StaticModelProvider,
        VectorMemoryProvider,
    )

    print("\n=== 测试 Provider API ===")

    class ProviderAgent:
        name = "provider-agent"

        def plan(self, task, context):
            message = context["model"].complete(task, context)
            return AgentPlan(task=task, tool_name="Remember", tool_args={"message": message})

        def reflect(self, plan, run, context):
            hits = context["memory"].search("framework memory")
            return {"hits": [hit.content for hit in hits], "tool_ok": run.tool_results["Remember"].ok}

    with tempfile.TemporaryDirectory() as tmpdir:
        model = StaticModelProvider("framework memory saved")
        memory = KeywordMemoryProvider()

        def remember(args, context):
            record = context["memory"].put("last", args["message"], {"source": "tool"})
            return {"key": record.key}

        runtime = Runtime.from_config(
            RuntimeConfig(workspace_root=tmpdir, state_dir=os.path.join(tmpdir, ".destiny")),
            tools=[FunctionTool(name="Remember", required=("message",), handler=remember)],
            model_provider=model,
            memory_provider=memory,
        )
        outcome = runtime.enhance(ProviderAgent()).run("use provider", run_id="provider")
        assert outcome.answer["tool_ok"] is True
        assert outcome.answer["hits"] == ["framework memory saved"]
        assert memory.search("saved")[0].metadata["source"] == "tool"
        print("  ✅ 场景 1: Agent/Tool 可通过 context 使用 model 和 memory provider")

        memory.put("a", "alpha framework")
        memory.put("b", "beta framework")
        results = memory.search("framework", top_k=1)
        assert len(results) == 1
        assert results[0].key in {"a", "b", "last"}
        assert model.complete("anything") == "framework memory saved"
        print("  ✅ 场景 2: 基础 provider 实现可独立使用")

        memory_path = os.path.join(tmpdir, "memory.json")
        file_memory = FileMemoryProvider(memory_path)
        file_memory.put("persisted", "persistent framework memory", {"source": "file"})
        reloaded = FileMemoryProvider(memory_path)
        assert reloaded.search("persistent")[0].metadata["source"] == "file"
        print("  ✅ 场景 3: FileMemoryProvider 可持久化并重新加载")

        default_runtime = Runtime.from_config(
            RuntimeConfig(workspace_root=tmpdir, state_dir=os.path.join(tmpdir, ".default-memory")),
        )
        default_runtime.memory_provider.put("default", "default runtime memory")
        assert os.path.exists(os.path.join(tmpdir, ".default-memory", "memory", "memory.json"))
        assert default_runtime.memory_provider.search("runtime")[0].key == "default"
        print("  ✅ 场景 4: Runtime 默认提供项目级持久 memory provider")

        vector_path = os.path.join(tmpdir, "vector-memory.json")
        vector_memory = VectorMemoryProvider(
            vector_path,
            embedding_provider=HashEmbeddingProvider(dimensions=64),
        )
        vector_memory.put(
            "agent-runtime",
            "agent runtime checkpoint trace memory",
            {"kind": "architecture"},
        )
        vector_memory.put(
            "recipe",
            "recipe salt oil dinner",
            {"kind": "irrelevant"},
        )
        scored = vector_memory.search_with_scores("runtime checkpoint trace", top_k=2)
        assert scored[0][0].key == "agent-runtime"
        assert scored[0][1] > 0
        print("  ✅ 场景 5: VectorMemoryProvider 支持向量相似度检索")

        reloaded_vector_memory = VectorMemoryProvider(
            vector_path,
            embedding_provider=HashEmbeddingProvider(dimensions=64),
        )
        assert reloaded_vector_memory.search("runtime checkpoint", top_k=1)[0].key == "agent-runtime"
        print("  ✅ 场景 6: VectorMemoryProvider 可持久化并重新加载")

        vector_runtime = Runtime.from_config(
            RuntimeConfig(
                workspace_root=tmpdir,
                state_dir=os.path.join(tmpdir, ".vector-runtime"),
                memory_backend="vector",
            ),
        )
        vector_runtime.memory_provider.put("runtime-vector", "runtime vector backend memory")
        assert os.path.exists(os.path.join(tmpdir, ".vector-runtime", "memory", "vector-memory.json"))
        assert vector_runtime.memory_provider.search("vector backend", top_k=1)[0].key == "runtime-vector"
        print("  ✅ 场景 7: Runtime 可通过 memory_backend=vector 启用向量记忆")

        sqlite_path = os.path.join(tmpdir, "sqlite-vector-memory.sqlite")
        sqlite_memory = SqliteVectorMemoryProvider(
            sqlite_path,
            embedding_provider=HashEmbeddingProvider(dimensions=64),
        )
        sqlite_memory.put(
            "sqlite-agent-runtime",
            "sqlite vector memory stores agent runtime checkpoints and traces",
            {"kind": "architecture"},
        )
        sqlite_memory.put(
            "sqlite-recipe",
            "sqlite dinner recipe salt oil",
            {"kind": "irrelevant"},
        )
        sqlite_hits = sqlite_memory.search_with_scores("runtime checkpoint trace", top_k=1)
        assert sqlite_hits[0][0].key == "sqlite-agent-runtime"
        sqlite_memory.close()
        reloaded_sqlite_memory = SqliteVectorMemoryProvider(
            sqlite_path,
            embedding_provider=HashEmbeddingProvider(dimensions=64),
        )
        assert reloaded_sqlite_memory.search("runtime checkpoint", top_k=1)[0].key == "sqlite-agent-runtime"
        reloaded_sqlite_memory.close()
        print("  ✅ 场景 8: SqliteVectorMemoryProvider 支持持久化向量检索")

        sqlite_runtime = Runtime.from_config(
            RuntimeConfig(
                workspace_root=tmpdir,
                state_dir=os.path.join(tmpdir, ".sqlite-runtime"),
                memory_backend="sqlite-vector",
            ),
        )
        sqlite_runtime.memory_provider.put("runtime-sqlite", "runtime sqlite vector backend memory")
        assert os.path.exists(os.path.join(tmpdir, ".sqlite-runtime", "memory", "vector-memory.sqlite"))
        assert sqlite_runtime.memory_provider.search("sqlite vector", top_k=1)[0].key == "runtime-sqlite"
        sqlite_runtime.close()
        print("  ✅ 场景 9: Runtime 可通过 memory_backend=sqlite-vector 启用 SQLite 向量记忆")

    print("  🎉 Provider API 9 个场景全部通过！")


def test_token_budget_api():
    """Test runtime token budget controls."""
    from destiny import (
        AgentPlan,
        FunctionTool,
        KeywordMemoryProvider,
        Runtime,
        RuntimeConfig,
        compact_value,
        estimate_tokens,
        truncate_text,
    )

    print("\n=== Testing Token Budget API ===")

    # Scenario 1: rough estimates and text truncation are deterministic.
    assert estimate_tokens("abcd", chars_per_token=4) == 1
    truncated, was_truncated = truncate_text("x" * 100, 10, chars_per_token=1)
    assert was_truncated
    assert len(truncated) == 10
    print("  OK scenario 1: estimate_tokens/truncate_text are deterministic")

    # Scenario 2: nested values are compacted with metadata.
    compacted, report = compact_value({"content": "x" * 100, "tail": "y" * 50}, 20, chars_per_token=1)
    assert report["truncated"] is True
    assert report["estimated_tokens_before"] > report["estimated_tokens_after"]
    assert "_token_budget_truncated" in compacted or len(compacted["content"]) < 100
    print("  OK scenario 2: compact_value shrinks nested payloads")

    # Scenario 3: memory retrieved through runtime context is compacted.
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = KeywordMemoryProvider()
        memory.put("long-memory", "long " + ("memory " * 80), {"source": "test"})
        runtime = Runtime.from_config(
            RuntimeConfig(
                workspace_root=tmpdir,
                state_dir=os.path.join(tmpdir, ".destiny-memory-budget"),
                token_chars_per_token=1,
                max_memory_record_tokens=40,
            ),
            memory_provider=memory,
        )
        context = runtime.agent_context(agent_name="budget-agent")
        hit = context["memory"].search("long", top_k=1)[0]
        assert len(hit.content) <= 40
        assert hit.metadata["token_budget"]["truncated"] is True
        print("  OK scenario 3: runtime memory context returns compact records")

    # Scenario 4: model provider wrapper compacts prompts and responses.
    class CapturingModel:
        name = "capturing"

        def __init__(self):
            self.prompt = ""
            self.context = {}

        def complete(self, prompt, context=None):
            self.prompt = prompt
            self.context = context or {}
            return "response-" + ("z" * 100)

    with tempfile.TemporaryDirectory() as tmpdir:
        model = CapturingModel()
        runtime = Runtime.from_config(
            RuntimeConfig(
                workspace_root=tmpdir,
                state_dir=os.path.join(tmpdir, ".destiny-model-budget"),
                token_chars_per_token=1,
                max_model_prompt_tokens=25,
                max_model_response_tokens=20,
                max_context_tokens=30,
            ),
            model_provider=model,
        )
        response = runtime.agent_context({"blob": "b" * 100}, agent_name="budget-agent")["model"].complete(
            "p" * 100,
            {"blob": "b" * 100},
        )
        assert len(model.prompt) <= 25
        assert len(response) <= 20
        assert model.context["token_budget_report"]["prompt"]["truncated"] is True
        print("  OK scenario 4: model prompts/responses are compacted")

    # Scenario 5: tool result payloads are compacted before reflection/storage.
    class BudgetAgent:
        name = "budget-agent"

        def plan(self, task, context):
            return AgentPlan(task=task, tool_name="Large", tool_args={})

        def reflect(self, plan, run, context):
            result = run.tool_results[plan.tool_name]
            return {"data": result.data, "metadata": result.metadata}

    with tempfile.TemporaryDirectory() as tmpdir:
        def large_tool(args, context):
            return {"content": "x" * 200, "keep": "small"}

        runtime = Runtime.from_config(
            RuntimeConfig(
                workspace_root=tmpdir,
                state_dir=os.path.join(tmpdir, ".destiny-tool-budget"),
                token_chars_per_token=1,
                max_tool_result_tokens=50,
            ),
            tools=[FunctionTool(name="Large", handler=large_tool)],
        )
        outcome = runtime.enhance(BudgetAgent()).run("large result", run_id="token-budget-tool")
        assert outcome.answer["metadata"]["token_budget"]["truncated"] is True
        assert len(outcome.answer["data"]["content"]) < 200
        assert outcome.answer["metadata"]["token_budget"]["estimated_tokens_after"] < outcome.answer["metadata"]["token_budget"]["estimated_tokens_before"]
        print("  OK scenario 5: tool results are compacted")

    # Scenario 6: token budget fields can be loaded from TOML.
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "destiny.toml")
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(
                "\n".join([
                    "[runtime]",
                    "token_budget_enabled = true",
                    "token_chars_per_token = 2",
                    "max_context_tokens = 1234",
                    "max_task_tokens = 234",
                    "max_model_prompt_tokens = 345",
                    "max_model_response_tokens = 456",
                    "max_tool_result_tokens = 567",
                    "max_memory_record_tokens = 678",
                ])
            )
        config = RuntimeConfig.from_file(config_path)
        assert config.token_chars_per_token == 2
        assert config.max_context_tokens == 1234
        assert config.token_budget_policy().max_tool_result_tokens == 567
        print("  OK scenario 6: token budget config loads from TOML")

    print("  Token Budget API 6 scenarios passed!")


def test_quality_evaluator_api():
    """Test deterministic quality evaluator and quality gate."""
    from destiny import (
        AgentPlan,
        Benchmark,
        EvalCase,
        FunctionTool,
        QualityEvaluator,
        QualityRubric,
        Runtime,
        RuntimeConfig,
        quality_gate,
    )

    print("\n=== Testing Quality Evaluator API ===")

    class QualityAgent:
        name = "quality-agent"

        def __init__(self, answer):
            self.answer = answer

        def plan(self, task, context):
            return AgentPlan(task=task, tool_name="Answer", tool_args={"answer": self.answer})

        def reflect(self, plan, run, context):
            return run.tool_results[plan.tool_name].data

    with tempfile.TemporaryDirectory() as tmpdir:
        def answer_tool(args, context):
            return args["answer"]

        runtime = Runtime.from_config(
            RuntimeConfig(workspace_root=tmpdir, state_dir=os.path.join(tmpdir, ".quality")),
            tools=[FunctionTool(name="Answer", required=("answer",), handler=answer_tool)],
        )
        rubric = QualityRubric(
            min_score=0.8,
            min_answer_chars=40,
            required_terms=("Destiny", "runtime", "OpenClaw"),
            forbidden_terms=("unsafe",),
        )
        evaluator = QualityEvaluator(rubric)
        agent = runtime.enhance(QualityAgent(
            "Destiny runtime improves OpenClaw agents with guarded tools and memory."
        ))
        outcome = agent.run("Explain Destiny runtime OpenClaw integration.", run_id="quality-pass")
        assessment = evaluator.evaluate(task="Explain Destiny runtime OpenClaw integration.", outcome=outcome)
        assert assessment.passed is True
        assert assessment.score >= 0.8
        assert "failed=none" in assessment.summary
        print("  OK scenario 1: quality evaluator passes good outcome")

        bad_agent = runtime.enhance(QualityAgent("unsafe short"))
        bad_outcome = bad_agent.run("Explain Destiny runtime OpenClaw integration.", run_id="quality-fail")
        bad_assessment = evaluator.evaluate(task="Explain Destiny runtime OpenClaw integration.", outcome=bad_outcome)
        assert bad_assessment.passed is False
        assert bad_assessment.score < assessment.score
        assert any(item.name == "safety" and not item.passed for item in bad_assessment.criteria)
        print("  OK scenario 2: quality evaluator explains failed outcome")

        benchmark = Benchmark([
            EvalCase(
                name="quality-gate",
                task="Explain Destiny runtime OpenClaw integration.",
                expect_tool="Answer",
                judge=evaluator.judge(),
            )
        ])
        report = benchmark.run(agent)
        assert report.passed == 1
        assert "1/1 passed" in report.summary()
        print("  OK scenario 3: evaluator judge plugs into Benchmark")

        artifact_path = os.path.join(tmpdir, "report.md")
        with open(artifact_path, "w", encoding="utf-8") as f:
            f.write("# Report\n")
        artifact_rubric = QualityRubric(
            min_score=0.8,
            required_terms=("report",),
            required_artifact_keys=("report_path",),
        )
        artifact_assessment = QualityEvaluator(artifact_rubric).evaluate(
            task="write report",
            answer={"answer": "report written", "report_path": artifact_path},
        )
        assert artifact_assessment.passed is True
        print("  OK scenario 4: evaluator validates required artifact keys")

        gate = quality_gate(rubric)
        assert gate(outcome, EvalCase(name="gate-helper", task="Explain Destiny runtime OpenClaw integration.")) is True
        runtime.close()
        print("  OK scenario 5: quality_gate helper returns EvalCase-compatible judge")

    print("  Quality Evaluator API 5 scenarios passed!")


def test_mcp_bridge_api():
    """Test MCP-style JSON-RPC tool bridge."""
    import io
    from destiny import FunctionTool, McpStdioTransport, McpToolBridge, Runtime, RuntimeConfig, mcp_tool_manifest

    print("\n=== Testing MCP Bridge API ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        def echo(args, context):
            return {"echo": args["message"], "path": context["node_history"]}

        def fail(args, context):
            raise ValueError("planned failure")

        runtime = Runtime.from_config(
            RuntimeConfig(workspace_root=tmpdir, state_dir=os.path.join(tmpdir, ".mcp")),
            tools=[
                FunctionTool(
                    name="Echo",
                    required=("message",),
                    handler=echo,
                    description="Echo one MCP message.",
                ),
                FunctionTool(name="Fail", handler=fail, description="Fail deterministically."),
            ],
        )
        bridge = McpToolBridge(runtime)

        initialize = bridge.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert initialize["result"]["serverInfo"]["name"] == "destiny-runtime"
        assert initialize["result"]["capabilities"]["tools"]["listChanged"] is False
        ping = bridge.handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})
        assert ping["result"] == {}
        print("  OK scenario 1: initialize and ping return MCP-style results")

        listed = bridge.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        tool_names = {tool["name"] for tool in listed["result"]["tools"]}
        assert {"Echo", "Fail"} <= tool_names
        assert "inputSchema" in listed["result"]["tools"][0]
        helper_manifest = mcp_tool_manifest(runtime)
        assert helper_manifest["tools"]
        print("  OK scenario 2: tools/list exposes Runtime tools")

        called = bridge.handle({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "Echo", "arguments": {"message": "hello mcp"}},
        })
        result = called["result"]
        assert result["isError"] is False
        assert result["structuredContent"]["echo"] == "hello mcp"
        assert result["content"][0]["type"] == "text"
        print("  OK scenario 3: tools/call executes a registered tool")

        failed = bridge.handle({
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "Fail", "arguments": {}},
        })
        assert failed["result"]["isError"] is True
        assert "planned failure" in failed["result"]["structuredContent"]["error"]
        print("  OK scenario 4: tool failure returns MCP tool error result")

        unknown_method = bridge.handle({"jsonrpc": "2.0", "id": 6, "method": "unknown/method"})
        assert unknown_method["error"]["code"] == -32601
        unknown_tool = bridge.handle({
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "Missing", "arguments": {}},
        })
        assert unknown_tool["error"]["code"] == -32602
        notification = bridge.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert notification is None
        print("  OK scenario 5: bridge handles protocol errors and notifications")

        transport = McpStdioTransport(bridge, input_stream=io.StringIO(), output_stream=io.StringIO())
        parse_error = transport.handle_line("{not-json}\n")
        assert parse_error["error"]["code"] == -32700
        invalid_request = transport.handle_line("[]\n")
        assert invalid_request["error"]["code"] == -32600
        print("  OK scenario 6: stdio transport reports parse and invalid-request errors")

        input_stream = io.StringIO(
            "\n".join([
                json.dumps({"jsonrpc": "2.0", "id": 8, "method": "initialize"}),
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                json.dumps({
                    "jsonrpc": "2.0",
                    "id": 9,
                    "method": "tools/call",
                    "params": {"name": "Echo", "arguments": {"message": "stdio"}},
                }),
                "",
            ])
        )
        output_stream = io.StringIO()
        streamed = McpStdioTransport(bridge, input_stream=input_stream, output_stream=output_stream)
        assert streamed.serve() == 3
        lines = [json.loads(line) for line in output_stream.getvalue().splitlines()]
        assert [line["id"] for line in lines] == [8, 9]
        assert lines[1]["result"]["structuredContent"]["echo"] == "stdio"
        print("  OK scenario 7: stdio transport processes JSON Lines requests")

        from scripts.mcp_stdio import build_parser
        parser = build_parser()
        args = parser.parse_args(["--workspace", tmpdir, "--enable-shell", "--server-name", "demo"])
        assert args.workspace == tmpdir
        assert args.enable_shell is True
        assert args.enable_http is False
        assert args.server_name == "demo"
        runtime.close()
        print("  OK scenario 8: stdio CLI parser keeps shell/http opt-in")

    print("  MCP Bridge API 8 scenarios passed!")


def test_openclaw_bridge_api():
    """Test OpenClaw-style bridge integration."""
    from destiny import (
        FunctionTool,
        OpenClawBridge,
        OpenClawRequest,
        Runtime,
        RuntimeConfig,
        openclaw_skill_manifest,
    )

    print("\n=== Testing OpenClaw Bridge API ===")

    # Scenario 1: request aliases and defaults are normalized.
    request = OpenClawRequest.from_mapping({
        "text": "hello bridge",
        "conversation_id": "conv-1",
        "user": "operator",
        "args": {"mode": "brief"},
    })
    assert request.message == "hello bridge"
    assert request.session_id == "conv-1"
    assert request.sender == "operator"
    assert request.tool_args["mode"] == "brief"
    print("  OK scenario 1: OpenClawRequest normalizes common payload aliases")

    # Scenario 2: bridge routes a chat payload through Runtime and a registered tool.
    with tempfile.TemporaryDirectory() as tmpdir:
        def reply_tool(args, context):
            record = context["memory"].put(
                f"session:{args['session_id']}",
                f"{args['channel']}:{args['message']}",
                {"sender": args["sender"]},
            )
            return {"reply": f"reply to {args['message']}", "memory_key": record.key}

        runtime = Runtime.from_config(
            RuntimeConfig(workspace_root=tmpdir, state_dir=os.path.join(tmpdir, ".openclaw")),
            tools=[
                FunctionTool(
                    name="Reply",
                    required=("message", "channel", "session_id", "sender"),
                    handler=reply_tool,
                )
            ],
        )
        bridge = OpenClawBridge(runtime, default_tool="Reply")
        response = bridge.handle({
            "message": "ship status",
            "channel": "openclaw",
            "session_id": "session-1",
            "sender": "tester",
        }, run_id="openclaw-success")
        assert response.ok is True
        assert response.message == "reply to ship status"
        assert response.tool_name == "Reply"
        assert response.data["memory_key"] == "session:session-1"
        assert runtime.memory_provider.search("ship status", top_k=1)[0].key == "session:session-1"
        runtime.close()
        print("  OK scenario 2: bridge executes registered Runtime tool")

    # Scenario 3: bridge exposes a serializable skill manifest.
    manifest = openclaw_skill_manifest(name="destiny-openclaw", default_tool="Reply")
    assert manifest["name"] == "destiny-openclaw"
    assert manifest["default_tool"] == "Reply"
    assert "message" in manifest["input_schema"]["required"]
    assert manifest["output_schema"]["properties"]["ok"]["type"] == "boolean"
    print("  OK scenario 3: OpenClaw skill manifest is serializable")

    # Scenario 4: unregistered tool failure is returned as an OpenClaw response.
    with tempfile.TemporaryDirectory() as tmpdir:
        runtime = Runtime.from_config(
            RuntimeConfig(workspace_root=tmpdir, state_dir=os.path.join(tmpdir, ".openclaw-missing")),
        )
        bridge = OpenClawBridge(runtime, default_tool="MissingTool")
        response = bridge.handle({"message": "call missing"}, run_id="openclaw-missing")
        assert response.ok is False
        assert "not registered" in response.message
        assert response.errors
        runtime.close()
        print("  OK scenario 4: missing tool becomes structured bridge error")

    # Scenario 5: no-tool bridge can still return a safe passthrough response.
    with tempfile.TemporaryDirectory() as tmpdir:
        runtime = Runtime.from_config(
            RuntimeConfig(workspace_root=tmpdir, state_dir=os.path.join(tmpdir, ".openclaw-passthrough")),
        )
        bridge = OpenClawBridge(runtime)
        response = bridge.handle({"message": "no tool needed"}, run_id="openclaw-passthrough")
        assert response.ok is True
        assert response.message == "no tool needed"
        assert response.tool_name == ""
        runtime.close()
        print("  OK scenario 5: bridge supports no-tool passthrough")

    print("  OpenClaw Bridge API 5 scenarios passed!")


def test_circuit_breaker():
    """测试电路断路器（新增）。"""
    from circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState

    print("\n=== 测试电路断路器 ===")

    # 场景 1: 初始状态为 CLOSED
    cb = CircuitBreaker("test-cb", failure_threshold=3, timeout=2)
    assert cb.state == CircuitState.CLOSED
    print("  ✅ 场景 1: 初始状态 CLOSED")

    # 场景 2: 成功调用不改变状态
    with cb:
        pass
    assert cb.state == CircuitState.CLOSED
    assert cb._success_count == 1
    print("  ✅ 场景 2: 成功调用不改变状态")

    # 场景 3: 连续失败未达阈值不打开
    for _ in range(2):
        try:
            with cb:
                raise ValueError("模拟失败")
        except ValueError:
            pass
    assert cb.state == CircuitState.CLOSED
    print("  ✅ 场景 3: 连续失败2次（阈值3）不打开")

    # 场景 4: 连续失败达到阈值后打开
    try:
        with cb:
            raise ValueError("第三次失败")
    except ValueError:
        pass
    assert cb.state == CircuitState.OPEN
    print("  ✅ 场景 4: 第3次失败后断路器 OPEN")

    # 场景 5: OPEN 状态拒绝请求
    try:
        with cb:
            pass
        assert False, "应该抛出 CircuitOpenError"
    except CircuitOpenError as e:
        assert "OPEN" in str(e)
        print("  ✅ 场景 5: OPEN 状态拒绝请求 (CircuitOpenError)")

    # 场景 6: 超时后进入 HALF_OPEN
    import time
    time.sleep(2.1)
    assert cb.state == CircuitState.HALF_OPEN
    print("  ✅ 场景 6: 超时后自动进入 HALF_OPEN")

    # 场景 7: HALF_OPEN 成功后恢复 CLOSED
    with cb:
        pass
    assert cb.state == CircuitState.CLOSED
    print("  ✅ 场景 7: HALF_OPEN 成功后恢复 CLOSED")

    # 场景 8: HALF_OPEN 失败后重新打开
    for _ in range(3):
        try:
            with cb:
                raise ValueError("失败")
        except ValueError:
            pass
    assert cb.state == CircuitState.OPEN
    time.sleep(2.1)
    assert cb.state == CircuitState.HALF_OPEN
    try:
        with cb:
            raise ValueError("试探失败")
    except ValueError:
        pass
    assert cb.state == CircuitState.OPEN
    print("  ✅ 场景 8: HALF_OPEN 失败后重新打开")

    # 场景 9: 手动重置
    cb.reset()
    assert cb.state == CircuitState.CLOSED
    assert cb._failure_count == 0
    print("  ✅ 场景 9: 手动重置")

    # 场景 10: 状态摘要
    status = cb.status()
    assert "name" in status
    assert "state" in status
    assert "failure_threshold" in status
    print("  ✅ 场景 10: 状态摘要")

    print("  🎉 电路断路器全部 10 个测试通过！")


def test_memory_blocks():
    """测试 Memory Blocks 记忆系统（新增 v3.2.2）。"""
    from memory_blocks import MemorySystem, MemoryBlock
    import tempfile, os, json

    print("\n=== 测试 Memory Blocks 记忆系统 ===")

    # 使用临时目录
    with tempfile.TemporaryDirectory() as tmpdir:
        ms = MemorySystem()
        ms.MEMORY_DIR = tmpdir
        ms.CORE_FILE = os.path.join(tmpdir, "core_blocks.json")
        ms.ARCHIVAL_FILE = os.path.join(tmpdir, "archival_store.json")
        # 重置内部状态（避免源文件加载干扰）
        ms._core_blocks = {}
        ms._archival_store = []

        # 场景 1: 添加高重要性记忆到 Core
        ms.add_memory("human", "用户喜欢简洁回答", 0.8)
        assert "human" in ms._core_blocks
        assert ms._core_blocks["human"].importance == 0.8
        print("  ✅ 场景 1: 添加高重要性记忆到 Core")

        # 场景 2: 低重要性记忆进 Archival
        ms.add_memory("memories", "今天天气不错", 0.2)
        assert len(ms._archival_store) == 1
        print("  ✅ 场景 2: 低重要性记忆自动进 Archival")

        # 场景 3: 追加到已有 Block
        ms.append_to_block("human", "用户使用中文交流", 0.6)
        content = ms.get_block("human")
        assert "中文交流" in content
        print("  ✅ 场景 3: 追加内容到 Block")

        # 场景 4: 重要性建议
        high_score = ms.suggest_importance("记住这个重要设置，永远不要修改")
        low_score = ms.suggest_importance("刚才试了一下")
        assert high_score > low_score, f"{high_score} should be > {low_score}"
        print("  ✅ 场景 4: 重要性建议（高频词更高分）")

        # 场景 5: 搜索 Archival
        from memory_blocks import ArchivalEntry
        ms._archival_store.append(ArchivalEntry(
            id="test1", label="memories", content="用户偏好：简洁回答",
            importance=0.6, archived_at=0, source="test"
        ))
        results = ms.search_archival("偏好")
        assert len(results) >= 1
        print("  ✅ 场景 5: Archival 搜索")

        # 场景 6: 持久化到磁盘
        ms._save_core()
        ms._save_archival()
        assert os.path.exists(ms.CORE_FILE), f"core file not found at {ms.CORE_FILE}"
        assert os.path.exists(ms.ARCHIVAL_FILE), f"archival file not found at {ms.ARCHIVAL_FILE}"
        # 验证 JSON 内容
        with open(ms.CORE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "human" in data
        print("  ✅ 场景 6: 持久化到磁盘")

        # 场景 7: stats 输出
        stats = ms.stats()
        assert "core_blocks" in stats
        assert "archival_count" in stats
        print("  ✅ 场景 7: stats 输出")

        # 场景 8: summary 输出
        summary = ms.summary()
        assert "Memory System" in summary
        print("  ✅ 场景 8: summary 输出")

        # 场景 9: update_block
        ms.update_block("persona", "我是天命人", 0.9)
        assert ms.get_block("persona") == "我是天命人"
        print("  ✅ 场景 9: update_block")

        # 场景 10: auto_compact（降级低重要性 block）
        ms._core_blocks["temp"] = MemoryBlock(
            label="temp", content="临时信息，不重要",
            importance=0.1, updated_at=0, created_at=0
        )
        ms.auto_compact(threshold=0.3)
        assert "temp" not in ms._core_blocks  # 应该被归档
        assert len(ms._archival_store) >= 1  # 归档后有内容
        print("  ✅ 场景 10: auto_compact 降级低重要性内容")

    print("  🎉 Memory Blocks 全部 10 个测试通过！")


# ── 主入口 ─────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  天命架构 · 确定性测试框架 v2 (Mock Parity Harness)")
    print("  借鉴 Claw Code Mock Parity Harness + LangGraph + OTEL")
    print("=" * 60)

    tests = [
        ("Protocol 7 安全验证链", test_tool_safety_chain),
        ("模型路由层", test_model_router),
        ("配置层次化合并", test_config_merger),
        ("三省图 State Graph v2", test_province_graph),
        ("执行追踪器", test_execution_tracer),
        ("工具结果缓存", test_tool_result_cache),
        ("电路断路器", test_circuit_breaker),
        ("Memory Blocks", test_memory_blocks),
        ("全链路集成", test_integration),
        ("公开 Runtime API", test_public_runtime_api),
        ("Standard Tool Adapters", test_standard_tool_adapters),
        ("Runtime TOML 配置", test_runtime_config_file),
        ("智能体增强 API", test_agent_enhancement_api),
        ("Benchmark API", test_benchmark_api),
        ("Enhancement Hooks", test_enhancement_hooks),
        ("Policy Hook", test_policy_hook),
        ("Provider API", test_provider_api),
        ("Token Budget API", test_token_budget_api),
        ("Quality Evaluator API", test_quality_evaluator_api),
        ("MCP Bridge API", test_mcp_bridge_api),
        ("OpenClaw Bridge API", test_openclaw_bridge_api),
    ]

    passed = 0
    failed = 0
    total_scenarios = 0
    scenario_counts = [10, 7, 7, 13, 5, 6, 10, 10, 4, 5, 7, 6, 2, 2, 2, 3, 9, 6, 5, 8, 5]

    for i, (name, test_fn) in enumerate(tests):
        try:
            test_fn()
            passed += 1
            total_scenarios += scenario_counts[i]
        except Exception as e:
            failed += 1
            print(f"\n  ❌ {name} 失败: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'=' * 60}")
    print(f"  测试结果: {passed} 模块通过 / {failed} 模块失败")
    print(f"  覆盖场景: {total_scenarios} 个")
    print(f"{'=' * 60}")

    sys.exit(1 if failed > 0 else 0)
