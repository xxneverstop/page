# Page Agent Harness v1 架构概览

Page 是 Windows 11 本地 Coding Agent Runtime。模型负责提出工具动作或最终回答，确定性 Runtime 负责权限、执行、恢复和证据。

```text
User / CLI
    ↓
Context Manager
  - Prefix
  - protected Recovery Context
  - Memory / Relevant Memory / History
  - protected Current Request
    ↓
Model Client (FakeModel / DeepSeek / compatible providers)
    ↓
Agent Loop → Tool Executor → File / Shell Tools
                 ↓
          Action Journal
          planned → started → succeeded/failed/reconciled
                 ↓
Checkpoint + Session + Task State (`task_state.json`) / `trace.jsonl` / `report.json`
```

## 恢复原则

- 文件工具执行前先持久化动作状态。
- `started` 动作恢复时用 before/after Hash 和后置条件对账。
- 后置条件已成立则标记 `reconciled`，不重复执行。
- Workspace、工具签名或 Schema 不一致时拒绝盲目写入。
- 任意 Shell 副作用无法可靠判定时转人工确认。
- stale 文件摘要不会重新进入 Prompt。

这是一套单机恢复内核，不等同于分布式事务、容器沙箱或生产级高可用平台。
