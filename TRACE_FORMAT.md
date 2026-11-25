# Page Trace Format

Page 的运行目录位于 `.page/runs/<run_id>/`，包含 `task_state.json`、`trace.jsonl` 和 `report.json`。其中 `task_state.json`、Action Journal 和 Checkpoint 保存恢复所需的持久化状态，`trace.jsonl` 保存按时间追加的观测事件，`report.json` 保存运行摘要。

## Trace schema

新事件使用 `trace_schema: "page-trace-v2"` 和 `trace_version: 2`。事件公共字段由运行时写入

| 字段 | 含义 |
| --- | --- |
| `event` | 事件类型，例如 `iteration_started`、`model_requested` 或 `tool_executed` |
| `event_id` | Run 内稳定的事件标识 |
| `event_seq` | JSONL 追加顺序，从 1 开始 |
| `run_id` | 当前运行标识 |
| `task_id` | 当前任务标识 |
| `session_id` | 当前会话标识 |
| `created_at` | 事件创建时间 |
| `iteration` | Agent Loop 轮次序号 |
| `iteration_id` | 轮次稳定标识 |
| `model_request_id` | 逻辑模型请求标识 |
| `tool_call_id` | 工具调用生命周期标识 |

旧 Trace 至少保留 `event` 和 `created_at`。查看器会按事件顺序补齐缺失字段，并为补齐的事件写入 `iteration_source: "viewer_inferred"`。页面会把这类身份标记为 Viewer 推导，便于区分运行时真实记录和兼容推导。

## 事件链路

一次完整轮次通常按以下链路落盘

```text
iteration_started
  → prompt_built
  → prompt_rendered       详细采集时出现
  → model_requested
  → model_http_*          Provider 支持且开启详细采集时出现
  → model_extracted       详细采集时出现
  → model_parsed
  → tool_requested        模型选择工具时出现
  → tool_stage            参数校验、审批和执行阶段
  → tool_executed         工具结果
  → checkpoint_created
  → iteration_finished
```

最终回答会在 `model_parsed(kind="final")`、`iteration_finished(outcome="final")` 和 `run_finished` 中形成可互相核对的证据。停止或失败运行会保留对应的 `outcome`、`stop_reason` 和结束事件。

## 关联规则

- 一个 `iteration_id` 对应一次 Agent Loop 轮次。`iteration_started` 和 `iteration_finished` 标记轮次边界。
- 一个 `model_request_id` 对应一次逻辑模型请求。HTTP 重试保留相同的 `model_request_id`，由 `attempt` 区分具体网络尝试。逻辑调用统计不会把 HTTP 重试重复计为新轮次。
- 一个 `tool_call_id` 贯穿同一工具的 `tool_requested`、多个 `tool_stage` 和 `tool_executed`。工具事件还会带上所属的 `iteration_id` 和可用的 `model_request_id`。
- `checkpoint_created`、Action Journal 字段和恢复事件用于解释动作的持久化状态。Trace 记录提供观测证据，恢复决策继续以持久化状态和 Agent Core 安全规则为准。

## 采集级别与脱敏

默认运行保留用于状态、统计和关联的摘要字段。`python -m page --trace-detail` 才会写入实际 Prompt、Provider 请求和响应正文、模型提取正文以及工具阶段和结果正文。Provider 未提供 HTTP 追踪能力时，页面会明确显示未记录。

Runtime 在写入 Trace 和 Report 前调用字段级脱敏。API Key、Authorization Header 和已发现凭据值不会作为明文写入。详细采集仍可能包含任务输入、源码和工具结果，正式分享前需要检查运行目录。

## Inspection model

Viewer 的 `GET /api/runs/<run_id>/inspection` 将多个工件归一为 `page-inspection-v1`

- `run` 保存状态、身份、时间、模型和停止原因。
- `stats` 保存轮次、逻辑模型调用、HTTP 尝试、工具、Checkpoint、上下文和用量统计。
- `iterations` 保存每轮的事件、模型请求、工具调用和结果摘要。
- `contexts` 保存上下文快照、分段统计和相邻快照 Diff。
- `models` 保存逻辑模型请求及其 Prompt、HTTP、Adapter 和 Harness 阶段。
- `tools` 保存工具生命周期、安全状态、结果和工作区变化。
- `recovery` 保存恢复事件、Journal 和 Checkpoint 引用。
- `evaluation` 只映射已有报告中的 Verifier、Evaluation 和 Metrics 字段。
- `raw` 保存有界的归一化事件集合，并标出截断和坏记录数量。

该接口只读。Viewer 不写回 Task、Session、Journal 或 Checkpoint。
