# 天命·生息架构 中文介绍

> 一个会成长、会自我修复、会说人话的 AI Agent 架构。
>
> 不是提示词堆砌，不是花哨流程图——是一套可执行、可度量、可自愈的 Agent 操作系统。

[English](../README.md)

## 核心信念

- 没有记忆的 Agent，每次都是新手
- 没有度量的 Agent，全凭瞎猜
- 没有心跳的 Agent，是死的
- 不能解释自己的 Agent，是黑箱

## 快速导航

- [快速上手](getting-started.md) — 如何让你的 Agent 接入此架构
- [三省图 (State Graph)](state-graph.md) — 8节点条件分支有向图
- [自进化引擎](evolution-engine.md) — 度量驱动 + 文本梯度反向传播
- [五层记忆系统](memory-system.md) — 向量语义检索 + 四层纵深
- [运行协议 (Protocols)](protocols.md) — P0 到 P6 操作守则
- [已知问题](known-issues.md) — 坦诚面对当前局限

## 技术栈

- **状态图**: 思维模拟（灵感来自 langgraph）
- **持久化**: JSON 检查点文件
- **向量记忆**: Ollama + nomic-embed-text（768维）
- **技能系统**: Markdown 文件 + 可选脚本
- **自动化**: SQLite 定时任务
- **浏览器**: Playwright
- **桌面**: nut-js + screenshot-desktop
