#!/usr/bin/env python3
"""
天命架构 — 确定性测试框架 (Deterministic Test Framework)
借鉴 Claw Code 的 Mock Parity Harness。

覆盖测试场景：
  - tool_safety_chain: 7 层安全验证链测试
  - model_router: 模型路由层测试
  - config_merger: 配置层次化合并测试
  - province_graph: 三省图 State Graph 测试

用法：
    python -m pytest tests/ --verbose
    python tests/test_all.py              # 直接运行
"""

import sys
import os
import json
import tempfile

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

    print("  ✅ 场景 10: 结果 summary 可输出")
    summary = result.summary()
    assert "L1" in summary and "结论" in summary

    print("  🎉 Protocol 7 全部测试通过！")


def test_model_router():
    """测试模型路由层。"""
    from model_router import ModelRouter

    print("\n=== 测试模型路由层 ===")

    # 创建临时 models.json
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump([
            {
                "id": "gemma4:e4b",
                "name": "Gemma 4 E4B",
                "url": "http://localhost:11434/v1/chat/completions",
                "supportsImages": True,
                "supportsToolCall": True,
            },
            {
                "id": "deepseek-v4-flash",
                "name": "DeepSeek V4 Flash",
                "url": "https://api.deepseek.com",
                "supportsImages": True,
                "supportsToolCall": True,
            },
            {
                "id": "mimo-v2.5",
                "name": "MiMo V2.5",
                "url": "https://token-plan-cn.xiaomimimo.com/v1",
                "supportsImages": True,
                "supportsToolCall": True,
            },
        ], f)
        tmp_path = f.name

    try:
        router = ModelRouter(models_json_path=tmp_path)

        # 场景 1: 别名解析
        assert router.resolve("fast") == "gemma4:e4b", "fast 应映射到 gemma4:e4b"
        assert router.resolve("smart") == "deepseek-v4-flash", "smart 应映射到 deepseek-v4-flash"
        assert router.resolve("multimodal") == "mimo-v2.5", "multimodal 应映射到 mimo-v2.5"
        print("  ✅ 场景 1: 别名解析正确")

        # 场景 2: 非别名直接返回
        assert router.resolve("gemma4:e4b") == "gemma4:e4b"
        assert router.resolve("some-custom-model") == "some-custom-model"
        print("  ✅ 场景 2: 非别名直接返回")

        # 场景 3: 任务类型自动选择
        assert router.auto_select("simple_qa") == "gemma4:e4b"
        assert router.auto_select("code_generation") == "deepseek-v4-flash"
        assert router.auto_select("image_analysis") == "mimo-v2.5"
        assert router.auto_select("long_running") == "mimo-v2.5-pro"
        assert router.auto_select("unknown_task") == "deepseek-v4-flash"  # default
        print("  ✅ 场景 3: 任务类型自动选择正确")

        # 场景 4: 降级策略
        fallback = router.FALLBACK_CHAIN.get("deepseek-v4-flash", [])
        assert "gemma4:e4b" in fallback, "deepseek-v4-flash 应可降级到 gemma4:e4b"
        fallback = router.FALLBACK_CHAIN.get("gemma4:e4b", [])
        assert fallback == [], "gemma4:e4b 不应有降级"
        print("  ✅ 场景 4: 降级策略正确")

        # 场景 5: 别名列表
        aliases = router.list_aliases()
        assert "fast" in aliases
        assert "smart" in aliases
        assert "multimodal" in aliases
        assert "coding" in aliases
        print("  ✅ 场景 5: 别名列表完整")

        # 场景 6: 可用模型列表
        available = router.list_available()
        assert "gemma4:e4b" in available
        assert "deepseek-v4-flash" in available
        print("  ✅ 场景 6: 可用模型列表正确")

    finally:
        os.unlink(tmp_path)

    print("  🎉 模型路由层全部测试通过！")


def test_config_merger():
    """测试配置层次化合并。"""
    from config_merger import ConfigMerger, deep_merge

    print("\n=== 测试配置层次化合并 ===")

    # 场景 1: 基础递归合并
    base = {"a": 1, "b": {"c": 2, "d": 3}, "e": [1, 2]}
    override = {"b": {"c": 99}, "e": [3, 4]}
    merged = deep_merge(base, override)
    assert merged["a"] == 1, "未覆盖的键应保留"
    assert merged["b"]["c"] == 99, "嵌套字典应递归合并"
    assert merged["b"]["d"] == 3, "未覆盖的嵌套键应保留"
    assert merged["e"] == [3, 4], "列表应完全替换"
    print("  ✅ 场景 1: 基础递归合并正确")

    # 场景 2: 默认配置应有所有必需键
    merger = ConfigMerger()
    config = merger.merge()
    assert "model_aliases" in config
    assert "default_permission_mode" in config
    assert "memory" in config
    assert "heartbeat" in config
    assert "tool_safety" in config
    assert "evolution" in config
    print("  ✅ 场景 2: 默认配置完整")

    # 场景 3: 默认值正确
    assert config["default_model"] == "smart"
    assert config["default_permission_mode"] == "workspace-write"
    assert config["language"] == "zh-CN"
    assert config["heartbeat"]["interval_hours"] == 4
    print("  ✅ 场景 3: 默认值正确")

    # 场景 4: 运行时参数覆盖
    merger_with_args = ConfigMerger(runtime_args={"default_model": "fast"})
    config = merger_with_args.merge()
    assert config["default_model"] == "fast", "运行时参数应覆盖默认值"
    print("  ✅ 场景 4: 运行时参数覆盖正确")

    # 场景 5: 嵌套覆盖不破坏其他键
    merger_nested = ConfigMerger(
        runtime_args={"memory": {"vector_search_threshold": 0.5}}
    )
    config = merger_nested.merge()
    assert config["memory"]["vector_search_threshold"] == 0.5
    assert config["memory"]["max_context_tokens"] == 8192  # 未被覆盖
    print("  ✅ 场景 5: 嵌套覆盖不破坏其他键")

    # 场景 6: dot-notation get
    merger = ConfigMerger()
    assert merger.get("memory.vector_search_threshold") == 0.25
    assert merger.get("heartbeat.enabled") == True
    assert merger.get("nonexistent.key", "default") == "default"
    print("  ✅ 场景 6: dot-notation get 正确")

    # 场景 7: diff_layers 返回各层快照
    layers = merger.diff_layers()
    assert "L1_defaults" in layers
    assert "L5_runtime" in layers
    print("  ✅ 场景 7: diff_layers 返回各层快照")

    print("  🎉 配置层次化合并全部测试通过！")


def test_province_graph():
    """测试三省图 State Graph。"""
    from province_graph import ProvinceGraph, GraphState

    print("\n=== 测试三省图 State Graph ===")

    # 场景 1: 创建图
    graph = ProvinceGraph()
    assert graph.current_node == "START"
    print("  ✅ 场景 1: 图创建成功，当前节点 START")

    # 场景 2: START → 中书省（无条件）
    state = graph.step()
    assert graph.current_node == "中书省"
    print("  ✅ 场景 2: START → 中书省")

    # 场景 3: 中书省 → 门下省（confidence ≥ 0.6）
    state["confidence"] = 0.8
    state = graph.step(state)
    assert graph.current_node == "门下省"
    print("  ✅ 场景 3: 中书省 → 门下省 (confidence=0.8)")

    # 场景 4: 门下省 → 尚书省（risk=low）
    state["risk_level"] = "low"
    state = graph.step(state)
    assert graph.current_node == "尚书省"
    print("  ✅ 场景 4: 门下省 → 尚书省 (risk=low)")

    # 场景 5: 尚书省 → 执行节点
    state = graph.step(state)
    assert graph.current_node == "执行节点"
    print("  ✅ 场景 5: 尚书省 → 执行节点")

    # 场景 6: 执行节点 → AAR/Checkpt
    state = graph.step(state)
    assert graph.current_node == "AAR/Checkpt"
    print("  ✅ 场景 6: 执行节点 → AAR/Checkpt")

    # 场景 7: AAR/Checkpt → END
    state = graph.step(state)
    assert graph.current_node == "END"
    assert graph.is_finished()
    print("  ✅ 场景 7: AAR/Checkpt → END")

    # 场景 8: 低置信度走澄清分支
    graph2 = ProvinceGraph()
    graph2.step()  # START → 中书省
    state2 = graph2.state
    state2["confidence"] = 0.3
    graph2.step(state2)
    assert graph2.current_node == "澄清分支"
    print("  ✅ 场景 8: 低置信度走澄清分支 (confidence=0.3)")

    # 场景 9: 高风险走阻断
    graph3 = ProvinceGraph()
    graph3.step()  # START → 中书省
    state3 = graph3.state
    state3["confidence"] = 0.9
    graph3.step(state3)  # → 门下省
    state3["risk_level"] = "high"
    graph3.step(state3)
    assert graph3.current_node == "阻断/预警"
    print("  ✅ 场景 9: 高风险走阻断/预警")

    # 场景 10: 重置
    graph.reset()
    assert graph.current_node == "START"
    assert not graph.is_finished()
    print("  ✅ 场景 10: 图重置成功")

    print("  🎉 三省图 State Graph 全部测试通过！")


def test_integration():
    """集成测试：模型路由 + 安全验证链 + 配置合并联动。"""
    from model_router import ModelRouter
    from tool_safety_chain import ToolSafetyChain
    from config_merger import ConfigMerger

    print("\n=== 集成测试 ===")

    # 场景 1: 配置合并 → 安全验证链参数
    merger = ConfigMerger()
    config = merger.merge()
    chain = ToolSafetyChain(
        permission_mode=config["default_permission_mode"],
        max_output_chars=config["tool_safety"]["max_output_chars"],
    )
    result = chain.validate("Bash", {"command": "ls"})
    assert result.passed
    print("  ✅ 场景 1: 配置合并 → 安全验证链联动")

    # 场景 2: 模型路由 + 任务类型
    router = ModelRouter()
    model = router.auto_select("image_analysis")
    assert "mimo" in model.lower() or "mimo-v2.5" == model
    print("  ✅ 场景 2: 图片任务自动选择多模态模型")

    # 场景 3: 安全验证链 + 危险命令
    result = chain.validate("Bash", {"command": "sudo rm -rf /"})
    assert not result.passed
    print("  ✅ 场景 3: 危险命令被安全验证链阻断")

    print("  🎎 集成测试全部通过！")


# ── 主入口 ─────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  天命架构 · 确定性测试框架 (Mock Parity Harness)")
    print("  借鉴 Claw Code 的 Mock Parity Harness 设计")
    print("=" * 60)

    tests = [
        test_tool_safety_chain,
        test_model_router,
        test_config_merger,
        test_province_graph,
        test_integration,
    ]

    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"\n  ❌ {test_fn.__name__} 失败: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'=' * 60}")
    print(f"  测试结果: {passed} 通过 / {failed} 失败 / {passed + failed} 总计")
    print(f"{'=' * 60}")

    sys.exit(1 if failed > 0 else 0)
