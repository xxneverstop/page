Read and follow AGENTS.md as the canonical engineering rules.

关键入口：
- `core/agent.py`：最小 Agent 主循环
- `core/models.py`：结构化消息、工具调用和事件
- `core/tools.py`：工具注册、校验和执行
- `docs/architecture.md`：架构和不变量
- `docs/roadmap/roadmap-v3.md`：当前阶段路线图

Claude Code 只负责按当前阶段计划修改和验证，不复制 AGENTS.md 规则，也不把旧 `page/` 包接入新入口。
