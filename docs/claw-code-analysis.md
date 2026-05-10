# Claw Code 源码通篇扫描分析报告

> 扫描日期：2026-05-10 | 仓库：github.com/ultraworkers/claw-code | ⭐ 191K Stars

---

## 一、项目概览

Claw Code 是 **Claude Code CLI 的公开 Rust 重写**，GitHub 史上最快达到 100K 星标的仓库。

| 指标 | 数值 |
|------|------|
| Stars | 191K |
| Forks | 110K |
| 总提交数 | 1,015 |
| Rust 代码量 | ~20K 行 |
| Crate 数量 | 9 个 |
| 二进制名 | `claw` |
| 默认模型 | `claude-opus-4-6` |

**技术栈：** Rust 96.5% + Python 3% + 其他 0.5%

---

## 二、核心架构（三部分）

### 2.1 OmX（oh-my-codex）— 工作流层
将简短指令转化为结构化执行：规划关键词 → 执行模式 → 持久化验证循环 → 并行多代理工作流。

### 2.2 clawhip — 事件通知路由器
监控和通知保留在编码代理上下文窗口之外：git提交、tmux会话、GitHub issues/PRs、代理生命周期事件。

### 2.3 OmO（oh-my-openagent）— 多代理协调层
处理规划、任务移交、分歧解决和跨代理验证循环。当架构师/执行者/审查者意见不一致时，提供结构让循环收敛。

---

## 三、Rust 工作区 Crate 架构（9个）

```
用户输入 (CLI/REPL)
    │
    ▼
┌─────────────────────────────────────────────┐
│  rusty-claude-cli (主二进制)                  │
│  参数解析 + REPL循环 + 流式显示 + 工具渲染     │
└──────────────┬──────────────────────────────┘
               │
    ┌──────────┼──────────┬──────────┬──────────┐
    ▼          ▼          ▼          ▼          ▼
┌───────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌──────────┐
│ api/  │ │runtime/│ │ tools/ │ │plugins/│ │commands/ │
│API通信│ │会话运行│ │工具执行│ │插件系统│ │命令注册  │
└───────┘ └────────┘ └────────┘ └────────┘ └──────────┘
    │          │          │          │
    ▼          ▼          ▼          ▼
SSE流式     配置加载    内置工具     元数据
认证管理     会话持久化   插件工具    安装/启用
请求预检     权限策略    Agent工具   Hook接口
Provider     MCP生命周期  搜索工具
             系统提示    Web工具
```

### Crate 详细职责

| Crate | 职责 |
|-------|------|
| **rusty-claude-cli** | 主CLI二进制，REPL，单次提示，子命令，流式渲染，参数解析 |
| **runtime** | `ConversationRuntime`、配置加载、会话持久化(JSONL)、权限策略、MCP客户端生命周期、系统提示组装、使用量跟踪 |
| **api** | Provider客户端、SSE流式传输、请求/响应类型、认证（API Key + Bearer Token）、请求大小/上下文窗口预检 |
| **tools** | 内置工具规范与执行：Bash、ReadFile、WriteFile、EditFile、GlobSearch、GrepSearch、WebSearch、WebFetch、Agent、TodoWrite、NotebookEdit、Skill、ToolSearch |
| **commands** | 斜杠命令定义、解析、帮助文本生成、JSON/Text命令渲染 |
| **plugins** | 插件元数据、安装/启用/禁用/更新流程、插件工具定义、Hook集成接口 |
| **compat-harness** | 从上游TS源代码提取tool/prompt清单 |
| **mock-anthropic-service** | 确定性的`/v1/messages`模拟服务，用于CLI对等测试 |
| **telemetry** | 会话跟踪事件和遥测数据类型 |

---

## 四、核心数据流

```
1. 用户输入 → CLI/REPL 接收
2. 命令路由 → 斜杠命令 vs 普通提示
3. 运行时准备 → 配置加载、会话恢复、权限检查
4. 系统提示组装 → CLAUDE.md + 项目记忆 + 工具描述
5. API 请求 → 请求预检 → SSE流式传输 → 响应处理
6. 工具调用 → 权限验证 → 执行 → 结果返回
7. 会话持久化 → JSONL写入
8. 输出渲染 → 文本/JSON + Markdown ANSI渲染
```

---

## 五、工具系统（40个工具）

### 已实现完整对等的工具（36个）

| 类别 | 工具 |
|------|------|
| **文件操作** | ReadFile、WriteFile、EditFile、GlobSearch、GrepSearch |
| **系统执行** | Bash（含9子模块安全验证）、PowerShell、REPL |
| **Web** | WebSearch、WebFetch |
| **任务管理** | TaskCreate、TaskGet、TaskList、TaskStop、TaskUpdate、TaskOutput |
| **团队/定时** | TeamCreate、TeamDelete、CronCreate、CronDelete、CronList |
| **代码智能** | LSP（诊断/悬停/定义/引用/补全/符号/格式化） |
| **MCP** | MCP调用桥、ListMcpResources、ReadMcpResource |
| **Agent** | Agent委托、SubAgent |
| **其他** | TodoWrite、NotebookEdit、Skill、ToolSearch、Sleep、Config、EnterPlanMode、ExitPlanMode、StructuredOutput |

### 仅存根（4个）
AskUserQuestion、McpAuth、RemoteTrigger、TestingPermission

---

## 六、权限系统（三层）

| 层级 | 权限 | 说明 |
|------|------|------|
| **read-only** | 只读 | 不能写文件/执行命令 |
| **workspace-write** | 工作区写入 | 可以编辑工作区内文件 |
| **danger-full-access** | 完全访问（默认） | 不限制任何操作 |

**Bash 安全验证链路（9子模块）：**
sedValidation → pathValidation → readOnlyValidation → destructiveCommandWarning → commandSemantics → bashPermissions → bashSecurity → modeValidation → shouldUseSandbox

---

## 七、配置系统

### 配置文件优先级（从低到高）
1. `~/.claw.json`（用户全局）
2. `~/.config/claw/settings.json`
3. `<repo>/.claw.json`（项目）
4. `<repo>/.claw/settings.json`
5. `<repo>/.claw/settings.local.json`（本地覆盖）

### 模型别名
| 别名 | 实际模型 |
|------|---------|
| `opus` | `claude-opus-4-6` |
| `sonnet` | `claude-sonnet-4-6` |
| `haiku` | `claude-haiku-4-5-20251213` |
| `grok` | `grok-3` |
| `grok-mini` | `grok-3-mini` |

### 多 Provider 支持
| Provider | 认证方式 |
|----------|---------|
| Anthropic | `ANTHROPIC_API_KEY` 或 `ANTHROPIC_AUTH_TOKEN` |
| OpenAI 兼容 | `OPENAI_API_KEY` + `OPENAI_BASE_URL` |
| xAI (Grok) | `XAI_API_KEY` + `XAI_BASE_URL` |
| DashScope (Qwen) | `DASHSCOPE_API_KEY` |
| Ollama（本地） | `OPENAI_BASE_URL=http://localhost:11434/v1` |

---

## 八、Slash 命令体系（67/141 已实现）

### 会话管理
`/help` `/status` `/sandbox` `/cost` `/resume` `/session` `/version` `/usage` `/stats`

### 工作区/Git
`/compact` `/clear` `/config` `/memory` `/init` `/diff` `/commit` `/pr` `/issue` `/export` `/hooks` `/files` `/release-notes`

### 发现/调试
`/mcp` `/agents` `/skills` `/doctor` `/tasks` `/context` `/desktop`

### 自动化/分析
`/review` `/advisor` `/insights` `/security-review` `/subagent` `/team` `/telemetry` `/providers` `/cron`

### 插件管理
`/plugin`（`list`/`install`/`enable`/`disable`/`uninstall`/`update`）

### 特色命令
`/ultraplan` 深度规划 | `/teleport` 文件/符号导航 | `/bughunter` 问题扫描

---

## 九、测试策略

### Mock Parity Harness
- 确定性 Anthropic 兼容 mock 服务（`mock-anthropic-service` crate）
- 干净环境 CLI 测试框架
- 脚本化场景验证

### 已覆盖场景（10个）
| 场景 | 验证内容 |
|------|---------|
| streaming_text | 流式文本响应 |
| read_file_roundtrip | 文件读取完整往返 |
| grep_chunk_assembly | Grep搜索分块组装 |
| write_file_allowed / denied | 写文件权限控制 |
| multi_tool_turn_roundtrip | 多工具调用往返 |
| bash_stdout_roundtrip | Bash标准输出往返 |
| bash_permission_prompt_approved / denied | Bash权限提示 |
| plugin_tool_roundtrip | 插件工具往返 |

---

## 十、哲学与设计理念

### 核心理念
> **人类设定方向，"爪子"执行劳动。**

### 瓶颈已经改变
- **过去**：打字速度是瓶颈
- **现在**：架构清晰度、任务分解、判断力、品味是稀缺资源

### 持久的差异化因素
1. 产品品味 — 知道什么值得构建
2. 方向 — 明确的愿景和目标
3. 系统设计 — 架构思维
4. 人类信任 — 建立可信赖的系统
5. 运营稳定性 — 系统的可靠性和韧性
6. 判断力 — 决定下一步构建什么

### 人类角色转变
> 当代理系统可以在几小时内重建代码库时，稀缺资源变成了：**清晰思考变得更加有价值**。

---

## 十一、与天命架构的对比

| 维度 | Claw Code | 天命·生息架构 |
|------|-----------|-------------|
| **语言** | Rust（~20K行） | Python + Markdown |
| **架构模式** | 9 Crate 模块化工作区 | 三省图 State Graph |
| **工具系统** | 40个内置工具 | 130技能 + 7个Hub |
| **多代理** | Agent + SubAgent + Team | 斥候/谋士/文官/总管 |
| **状态管理** | JSONL会话持久化 | JSON检查点 + 向量记忆 |
| **自进化** | 无（静态工具集） | 4引擎自进化 + 文本梯度 |
| **记忆系统** | CLAUDE.md + 会话恢复 | 5层记忆 + 向量检索 |
| **权限模型** | 3层（read-only/write/full） | 风险等级（low/medium/high） |
| **MCP支持** | 完整生命周期 | MCP扩展连接 |
| **测试** | Mock Parity Harness | 无独立测试框架 |
| **生态** | Discord + 插件市场 | 技能编译 + EventBus |

### 天命架构可借鉴
1. **Crate 职责分离**：每个模块有明确单一职责，天命可进一步模块化
2. **Mock 测试框架**：确定性测试是天命缺失的
3. **权限三层模型**：比当前 risk_level 更细粒度
4. **配置层次化**：多层配置合并机制值得借鉴
5. **Provider 抽象**：统一的API通信层设计优雅

### 天命架构优势
1. **自进化能力**：Claw Code 是静态的，天命有4引擎持续进化
2. **记忆深度**：5层记忆 + 向量检索 vs 简单的会话恢复
3. **度量驱动**：基线对比 + 梯度反向传播
4. **知识沉淀**：130技能自动编译 vs 手动插件管理
