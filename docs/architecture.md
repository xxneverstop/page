# Minimal Agent 架构

```text
CLI → Agent.run
        ├─ Context.build(Session)
        ├─ Provider.complete(messages, tools)
        ├─ Session.append(assistant/tool result)
        └─ ToolExecutor.execute(call) → 下一轮
                 └─ EventSink → trace.jsonl → Viewer
```

`Session` 是结构化对话和工具结果的事实源；Context 只是每次请求的投影。Trace 用于观察和复盘，Viewer 只读且不参与决策。工具调用在同一轮顺序执行，每个 `call_id` 必须有一个结果。`completed` 表示 Agent 正常结束，不代表独立 Verifier 通过。

恢复只在显式 Resume 边界执行，Context 构建不得隐式触发恢复对账。新核心使用根目录 `core/`，旧 `page/` 包仅作为历史参考。
