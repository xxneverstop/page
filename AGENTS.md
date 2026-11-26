# AGENTS.md

Page 是一个 Python Minimal Coding Agent Harness，目标是简单、稳定、可靠、易读。

## 执行顺序

先阅读 `docs/README.md`、`docs/architecture.md`、`docs/roadmap/roadmap-v3.md` 和当前阶段计划；只实现当前阶段范围。

## 代码规则

- 新运行链路使用根目录 `core/`，旧 `page/` 包只作为历史参考，不得被新入口间接导入。
- 保持单向依赖：模型与会话是数据事实源，Agent 只协调上下文、Provider、工具和事件；核心循环不处理 UI、实验报告或恢复对账。
- 优先标准库和已有依赖；不为未来场景预留抽象。
- 公共入口、关键控制流和边界条件写简短中文注释或 docstring，说明为什么。

## 变更与验证

先读相关接口和测试；不要修改历史 Benchmark、旧 Trace 或用户文件。每次修改运行相关单测，阶段完成运行完整离线回归、CLI 冒烟和一项运行证据，并记录实际命令与结果。

Shell、文件写入和外部副作用必须经过路径约束、输出限制和审批策略；不泄露密钥。模型回答不是代码验证结果，`completed` 不等于独立 Verifier 通过。

新增能力同步更新 docs、roadmap 状态和必要的 Viewer 字段/测试。

## 代码库结构查询

本项目使用 codebase-memory-mcp。代码发现优先使用 `search_graph`、`trace_path`、`get_code_snippet`、`query_graph`、`get_architecture`；只有搜索字符串、配置或 MCP 不足时才使用 `rg`/文件搜索。
