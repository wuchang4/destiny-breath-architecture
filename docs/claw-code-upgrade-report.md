# 天命架构基于 Claw Code 的升级报告

## 一、升级背景

基于对 GitHub 仓库 `ultraworkers/claw-code`（191K Stars，Claude Code CLI 的 Rust 重写）的全面扫描，提取 5 个可借鉴的核心设计，融合进天命·生息架构。

**借鉴来源：** Claw Code（Rust CLI 代理框架）
**借鉴日期：** 2026-05-10
**借鉴深度：** 🔵 深度融合（成为架构核心组件）

---

## 二、升级内容

### 1. 模块化工作区（借鉴 Crate 职责分离）

**原状：** 天命架构的组件（三省图、技能系统、记忆系统等）在逻辑上是分离的，但没有明确的模块边界定义。

**升级：** 参考 Claw Code 的 9-Crate 工作区设计，天命按功能域划分为 6 个独立模块，每个模块有明确的单一职责。

**新增内容：**
```markdown
## 模块化工作区设计（Claw Code 融合）

天命架构按功能域划分为 6 个独立模块，每个模块有明确的单一职责，参考 Claw Code 的 Crate 职责分离设计：

| 模块 | 职责 | 包含组件 |
|------|------|---------|
| **core** | 核心状态管理 | 三省图 State Graph、ProvinceGraph、会话状态 |
| **cognition** | 认知与推理 | 中书省（意图解析）、门下省（验证）、尚书省（规划） |
| **memory** | 记忆系统 | 五层记忆、向量检索、检查点、会话持久化 |
| **tools** | 工具与技能 | 130技能、7个Hub、工具执行引擎 |
| **evolution** | 自进化引擎 | 4引擎、度量系统、梯度反向传播、基线对比 |
| **military** | 天行军子系统 | 斥候/谋士/文官/总管、EventBus、DDGS搜索 |

**模块间通信：** 通过 EventBus 事件总线（SQLite 持久化）进行异步通信，参考 Claw Code 的 crate 间依赖单向设计。
```

**更新位置：** SOUL.md → 天行军子系统章节之后

---

### 2. 确定性测试框架（借鉴 Mock Parity Harness）

**原状：** 天命架构没有独立的测试框架，三省图节点和工具链的行为验证依赖手动执行。

**升级：** 参考 Claw Code 的 Mock Parity Harness，为天命设计确定性测试框架。

**新增内容：**
```markdown
## 确定性测试框架（Claw Code 融合 · 计划中）

借鉴 Claw Code 的 Mock Parity Harness 设计，为三省图节点和工具链提供确定性测试。

### 测试架构

```
┌─────────────────────────────────────────────┐
│  天命测试框架                                 │
│  ┌─────────────┐  ┌─────────────────────────┐│
│  │ MockProvider │  │ 三省图节点测试套件       ││
│  │ (确定性API)  │  │ - 中书省意图解析测试     ││
│  └─────────────┘  │ - 门下省验证逻辑测试     ││
│  ┌─────────────┐  │ - 尚书省工具选择测试     ││
│  │ 工具链测试   │  │ - 执行节点工具调用测试   ││
│  │ 套件        │  │ - AAR/梯度反向传播测试   ││
│  └─────────────┘  └─────────────────────────┘│
└─────────────────────────────────────────────┘
```

### 已规划的测试场景

| 场景 | 验证内容 | 状态 |
|------|---------|------|
| `intent_parsing_roundtrip` | 中书省意图解析完整往返 | 待实现 |
| `verification_logic` | 门下省风险判断逻辑 | 待实现 |
| `tool_selection_accuracy` | 尚书省工具选择准确率 | 待实现 |
| `multi_tool_execution` | 多工具执行链路 | 待实现 |
| `gradient_backpropagation` | 梯度反向传播正确性 | 待实现 |
| `checkpoint_recovery` | 检查点恢复可靠性 | 待实现 |

### 测试执行方式

```bash
# 运行全部测试
python -m pytest tests/ --verbose

# 运行单个模块测试
python -m pytest tests/test_cognition/ -v

# 运行对等性测试（对比预期输出）
python scripts/run_parity_test.py --scenario intent_parsing
```
```

**更新位置：** SOUL.md → 确定性测试框架条目

---

### 3. 工具执行安全验证链（借鉴 Bash 安全验证）

**原状：** 天命架构的工具执行只有简单的 risk_level 判断（low/medium/high），没有细粒度的安全验证链。

**升级：** 参考 Claw Code 的 9 子模块 Bash 安全验证链，天命设计 7 层工具执行安全链。

**新增内容：**
```markdown
## Protocol 7 — 工具执行安全验证链（Claw Code 融合）

借鉴 Claw Code 的 9 子模块 Bash 安全验证设计，天命的工具执行在调用前必须通过 7 层安全验证链。

### 7 层验证链

```
[工具调用请求]
    │
    ▼
[1] 权限模式检查 → 当前是 read-only / workspace-write / full-access？
    │
    ▼
[2] 路径安全检查 → 是否有路径遍历（../）？是否访问敏感目录？
    │
    ▼
[3] 命令语义分析 → 危险命令检测（rm -rf、格式化、注册表修改等）
    │
    ▼
[4] 沙箱决策 → 是否需要沙箱隔离？（根据 risk_level 决定）
    │
    ▼
[5] 输出大小限制 → 大 stdout/文件内容是否需要截断？
    │
    ▼
[6] 用户确认 → 高风险操作（外部API、删除、发送）是否需要人工确认？
    │
    ▼
[7] 执行监控 → 执行超时、异常捕获、结果验证
    │
    ▼
[工具执行完成]
```

### 危险命令检测清单

| 类别 | 命令模式 | 处理方式 |
|------|---------|---------|
| 文件删除 | `rm -rf`、`del /S`、`shutil.rmtree` | 🔴 阻断 + 用户确认 |
| 系统修改 | `regedit`、`bcdedit`、`format` | 🔴 阻断 + 用户确认 |
| 网络外发 | `curl`/`wget` 到外部URL | 🟡 警告 + 用户确认 |
| 权限提升 | `sudo`、`runas`、`takeown` | 🔴 阻断 + 用户确认 |
| 批量操作 | 通配符删除、循环写入 | 🟡 警告 + 分批执行 |

### 权限模式

| 模式 | 允许的操作 | 默认场景 |
|------|-----------|---------|
| **read-only** | 读取文件、搜索、分析 | 代码审查、文档阅读 |
| **workspace-write** | 工作区内文件读写 | 日常开发任务 |
| **full-access** | 所有操作（含外部API） | 用户明确授权后 |
```

**更新位置：** SOUL.md → Protocol 6 之后，新增 Protocol 7

---

### 4. 配置层次化（借鉴多层配置合并）

**原状：** 天命的配置（SOUL.md、MEMORY.md 等）是扁平化的，没有明确的优先级和合并机制。

**升级：** 参考 Claw Code 的 5 层配置合并设计，天命的配置按优先级从低到高合并。

**新增内容：**
```markdown
## 配置层次化设计（Claw Code 融合）

借鉴 Claw Code 的多层配置合并机制，天命的配置按优先级从低到高合并，高优先级覆盖低优先级。

### 配置层次

| 层级 | 文件 | 优先级 | 说明 |
|------|------|--------|------|
| **L1 全局默认** | `SOUL.md` | 最低 | 架构核心规则，不可覆盖 |
| **L2 项目配置** | `project-config.json` | 低 | 项目特定配置（如有） |
| **L3 用户偏好** | `MEMORY.md` | 中 | 用户偏好、历史记录 |
| **L4 会话配置** | `session-config.json` | 高 | 单次会话临时覆盖 |
| **L5 运行时** | 命令行参数 | 最高 | `--model`、`--permission-mode` 等 |

### 配置合并规则

```python
def merge_config(base: dict, override: dict) -> dict:
    """
    递归合并配置，override 中的值覆盖 base 中的同名键。
    列表类型：override 替换 base（不追加）。
    字典类型：递归合并。
    """
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged
```

### 配置文件示例

```json
// project-config.json（L2 项目配置）
{
  "model_aliases": {
    "fast": "gemma4:e4b",
    "smart": "deepseek-v4-flash",
    "multimodal": "mimo-v2.5"
  },
  "default_permission_mode": "workspace-write",
  "memory": {
    "vector_search_threshold": 0.25,
    "max_context_tokens": 8192
  }
}
```
```

**更新位置：** SOUL.md → 配置层次化条目

---

### 5. 模型路由层（借鉴 Provider 抽象）

**原状：** 天命的模型切换是手动的（`/model` 命令），没有自动降级和别名映射机制。

**升级：** 参考 Claw Code 的 Provider 抽象和模型别名系统，天命设计统一的模型路由层。

**新增内容：**
```markdown
## 模型路由层（Claw Code 融合）

借鉴 Claw Code 的 Provider 抽象和模型别名系统，天命设计统一的模型路由层，支持别名映射、自动降级、多模型切换。

### 模型别名系统

| 别名 | 实际模型 | 用途 |
|------|---------|------|
| `fast` | `gemma4:e4b`（本地） | 快速响应、简单任务 |
| `smart` | `deepseek-v4-flash` | 复杂推理、代码生成 |
| `multimodal` | `mimo-v2.5` | 图片/音频/视频理解 |
| `coding` | `mimo-v2.5-pro` | 长程复杂任务、软件工程 |
| `local` | `gemma4:e4b` | 离线模式、隐私敏感任务 |

### 自动降级策略

```
[用户请求]
    │
    ▼
[模型选择] → 有 --model 参数？ → 使用指定模型
    │
    ├── 无 → 检查任务类型
    │       ├── 简单问答 → fast（本地 gemma4）
    │       ├── 代码/推理 → smart（deepseek-v4-flash）
    │       ├── 图片任务 → multimodal（mimo-v2.5）
    │       └── 长程任务 → coding（mimo-v2.5-pro）
    │
    ▼
[模型可用性检查]
    │
    ├── API 可用 → 使用选定模型
    │
    ├── API 不可用 → 自动降级到本地模型
    │       └── gemma4:e4b（离线模式）
    │
    └── 本地模型也不可用 → 提示用户检查 Ollama 服务
```

### Provider 抽象

```python
class ModelRouter:
    """统一模型路由层，参考 Claw Code 的 Provider 抽象。"""
    
    ALIASES = {
        "fast": "gemma4:e4b",
        "smart": "deepseek-v4-flash",
        "multimodal": "mimo-v2.5",
        "coding": "mimo-v2.5-pro",
        "local": "gemma4:e4b",
    }
    
    def resolve(self, model_spec: str) -> str:
        """解析模型别名或直接返回模型ID。"""
        return self.ALIASES.get(model_spec, model_spec)
    
    def select_for_task(self, task_type: str) -> str:
        """根据任务类型自动选择最佳模型。"""
        task_model_map = {
            "simple_qa": "fast",
            "code_generation": "smart",
            "image_analysis": "multimodal",
            "long_running": "coding",
        }
        return self.resolve(task_model_map.get(task_type, "smart"))
    
    def fallback(self, primary: str) -> str:
        """主模型不可用时的降级策略。"""
        if primary == "gemma4:e4b":
            return None  # 已经是本地模型，无法降级
        return "gemma4:e4b"  # 降级到本地模型
```
```

**更新位置：** SOUL.md → 模型路由层条目

---

## 三、仪表盘更新

在架构状态仪表盘中新增 4 个组件：

| 组件 | 状态 | 说明 |
|------|------|------|
| Protocol 7 工具安全验证链 | 🟢 **Claw Code 融合** | 借鉴 Claw Code 的 9 子模块 Bash 验证，升级为 7 层工具执行安全链 |
| 模块化工作区 | 🟢 **Claw Code 融合** | 借鉴 Crate 职责分离，天命按功能域划分为 6 个独立模块 |
| 配置层次化 | 🟢 **Claw Code 融合** | 借鉴多层配置合并机制：全局→项目→本地→运行时 |
| 模型路由层 | 🟢 **Claw Code 融合** | 统一 Provider 抽象，支持别名映射、自动降级、多模型切换 |
| 确定性测试框架 | 🟡 **Claw Code 融合 · 计划中** | 借鉴 Mock Parity Harness，为三省图节点和工具链提供确定性测试 |

---

## 四、借鉴来源清单更新

在 SOUL.md 的借鉴来源清单中新增：

| 来源 | 领域 | 借鉴内容 | 融合深度 |
|------|------|---------|---------|
| **Claw Code** (ultraworkers) | Rust CLI 代理框架 | 模块化工作区、确定性测试框架、工具安全验证链、配置层次化、模型路由层 | 🔵 深度 |

---

## 五、升级效果

| 维度 | 升级前 | 升级后 |
|------|--------|--------|
| **模块化** | 逻辑分离，无明确边界 | 6 个独立模块，单一职责 |
| **测试** | 无独立测试框架 | 确定性测试框架（计划中） |
| **安全** | 简单 risk_level 判断 | 7 层工具执行安全验证链 |
| **配置** | 扁平化，无优先级 | 5 层配置合并，优先级明确 |
| **模型切换** | 手动 `/model` | 自动降级 + 别名映射 + 任务类型路由 |

---

## 六、后续计划

1. **实现确定性测试框架**：为三省图节点和工具链编写测试用例
2. **实现模型路由层**：在代码层面实现 ModelRouter 类
3. **实现配置层次化**：创建 project-config.json 和合并逻辑
4. **完善工具安全验证链**：将 7 层验证嵌入工具执行流程
5. **模块化重构**：将现有组件迁移到 6 个独立模块

---

_报告生成时间：2026-05-10_
_借鉴来源：Claw Code (github.com/ultraworkers/claw-code)_
_融合深度：🔵 深度融合（成为架构核心组件）_
