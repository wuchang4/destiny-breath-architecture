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

# 将 scripts 目录加入路径
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
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

    finally:
        os.unlink(tmp_path)

    print("  🎉 模型路由层全部 6 个测试通过！")


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
    """测试三省图 State Graph v2。"""
    from province_graph import ProvinceGraph

    print("\n=== 测试三省图 State Graph v2 ===")

    # 场景 1: 创建图
    graph = ProvinceGraph()
    assert graph.current_node == "START"
    assert not graph.is_interrupted()
    print("  ✅ 场景 1: 图创建成功，当前节点 START")

    # 场景 2: START → 中书省（无条件）
    graph.step()
    assert graph.current_node == "中书省"
    print("  ✅ 场景 2: START → 中书省")

    # 场景 3: 中书省 → 门下省（confidence ≥ 0.6）
    graph.step({"confidence": 0.8})
    assert graph.current_node == "门下省"
    print("  ✅ 场景 3: 中书省 → 门下省 (confidence=0.8)")

    # 场景 4: 门下省 → 尚书省（risk=low）
    graph.step({"risk_level": "low"})
    assert graph.current_node == "尚书省"
    print("  ✅ 场景 4: 门下省 → 尚书省 (risk=low)")

    # 场景 5: 尚书省 → 执行节点
    graph.step()
    assert graph.current_node == "执行节点"
    print("  ✅ 场景 5: 尚书省 → 执行节点")

    # 场景 6: 执行节点 → AAR/Checkpt
    graph.step()
    assert graph.current_node == "AAR/Checkpt"
    print("  ✅ 场景 6: 执行节点 → AAR/Checkpt")

    # 场景 7: AAR/Checkpt → END
    graph.step()
    assert graph.current_node == "END"
    assert graph.is_finished()
    print("  ✅ 场景 7: AAR/Checkpt → END")

    # 场景 8: 低置信度走澄清分支
    g2 = ProvinceGraph()
    g2.step()
    g2.step({"confidence": 0.3})
    assert g2.current_node == "澄清分支"
    print("  ✅ 场景 8: 低置信度走澄清分支 (confidence=0.3)")

    # 场景 9: 高风险走阻断（v2：应触发中断）
    g3 = ProvinceGraph()
    g3.step()
    g3.step({"confidence": 0.9})
    g3.step({"risk_level": "high"})
    assert g3.current_node == "阻断/预警"
    assert g3.is_interrupted(), "高风险应触发中断"
    assert "用户确认" in g3.get_interrupt_reason()
    print("  ✅ 场景 9: 高风险触发中断 (v2 新增)")

    # 场景 10: 中断后恢复
    g3.resume({"user_confirmed": True})
    assert not g3.is_interrupted()
    g3.step()
    assert g3.is_finished()
    print("  ✅ 场景 10: 中断后恢复执行 (v2 新增)")

    # 场景 11: 重置
    graph.reset()
    assert graph.current_node == "START"
    assert not graph.is_finished()
    assert not graph.is_interrupted()
    print("  ✅ 场景 11: 图重置成功")

    # 场景 12: 执行追踪 (v2 新增)
    g4 = ProvinceGraph()
    g4.step()
    g4.step({"confidence": 0.8})
    g4.step({"risk_level": "low"})
    trace = g4.trace
    assert len(trace.spans) > 0, "应有执行 span"
    print("  ✅ 场景 12: 执行追踪记录 span (v2 新增)")

    # 场景 13: 序列化/反序列化
    data = g4.serialize()
    assert data["version"] == 2
    assert "current_node" in data
    assert "state" in data
    g5 = ProvinceGraph.deserialize(data)
    assert g5.current_node == g4.current_node
    print("  ✅ 场景 13: 序列化/反序列化 (v2)")

    # 场景 14: run() 自动执行
    g6 = ProvinceGraph()
    g6.run()
    assert g6.is_finished()
    print("  ✅ 场景 14: run() 自动执行到 END (v2 新增)")

    print("  🎉 三省图 v2 全部 14 个测试通过！")


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

    print("\n=== 全链路集成测试 ===")

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

    with tracer.span("尚书省"):
        graph.step()  # 门下省 → 尚书省

    with tracer.span("执行"):
        graph.step()  # 尚书省 → 执行节点

    assert graph.current_node == "执行节点"
    print("  ✅ 场景 1: 配置→安全链→图→追踪 全链路")

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
    g.step({"confidence": 0.9})
    g.step({"risk_level": "high"})
    assert g.is_interrupted()
    g.resume({"user_confirmed": True})
    g.step()
    assert g.is_finished()
    print("  ✅ 场景 3: 中断→确认→恢复→完成")

    # 追踪摘要
    print(f"\n{tracer.summary()}")

    print("  🎉 全链路集成测试 3 个场景全部通过！")


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
        ("全链路集成", test_integration),
    ]

    passed = 0
    failed = 0
    total_scenarios = 0
    scenario_counts = [10, 6, 7, 14, 5, 6, 3]

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
