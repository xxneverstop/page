# 运行合同

## 消息与调用

- `Message` 至少包含 `role`、结构化 `content`，工具调用消息保留唯一 `call_id`。
- `ModelTurn` 明确区分文本、工具调用、用量、停止原因和模型错误。
- 每个 `ToolCall` 必须产生一个 `ToolResult`，成功、失败和拒绝都算结果。

## 工具边界

文件路径必须解析到工作区内；写入和 Shell 在副作用前完成校验与审批。Shell 结果保留退出码、截断标记和错误类型。测试退出码非零是模型可见的观察结果。

## 事件与工件

事件包含 `event`、`run_id`、时间戳，并按需携带 `turn_id`、`model_request_id`、`tool_call_id`。运行目录为 `.page/runs/<run_id>/`，包括 `trace.jsonl`、`task_state.json` 和 `report.json`。Viewer 适配层可以输出旧 `page-trace-v2`，不伪造 Recovery、Skill 或 Verifier 证据。
