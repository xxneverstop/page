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
- 一个 `tool_call_id` 贯穿同一工具的 `tool_requested`、多个 `tool_stage` 和 `tool_executed`。工具事件还会带上所属的 `iteration_id` 和可用的 `model_request_id`。`tool_requested` 在基础 Trace 中也会记录（参数正文仅在详细采集时写入），因此"请求工具"和"工具实际执行"可以分开核对。
- `iteration_finished.outcome` 记录轮次结束原因：`tool`、`final`、`retry`、`stopped`、`model_failed`、`context_failed` 或 `finalization_tool_rejected`。工具执行失败不会被后续通用的 `tool` outcome 覆盖为成功。
- `checkpoint_created`、Action Journal 字段和恢复事件用于解释动作的持久化状态。Trace 记录提供观测证据，恢复决策继续以持久化状态和 Agent Core 安全规则为准。
- 每轮 `prompt_metadata` 中的 `history_tool_call_ids`、`history_tool_results` 和 `history_messages` 用来确认工具反馈已进入下一轮 History / Context。

## 采集级别与脱敏

默认运行保留用于状态、统计和关联的摘要字段。`python -m page --trace-detail` 才会写入实际 Prompt、Provider 请求和响应正文、模型提取正文以及工具阶段和结果正文。Provider 未提供 HTTP 追踪能力时，页面会明确显示未记录。

`prompt_rendered` 记录的是**本地渲染文本**，并带有 `prompt_source: "local_render"`。原生工具协议可能只把工具结果发给服务端，因此 Provider 实际入参以 `model_http_request.body` 为准，二者不能互相替代。

Runtime 在写入 Trace 和 Report 前调用字段级脱敏。API Key、Authorization Header 和已发现凭据值不会作为明文写入。详细采集仍可能包含任务输入、源码和工具结果，正式分享前需要检查运行目录。

## 统计口径

- 逻辑模型调用按 `model_request_id` 去重。HTTP 重试仍属于同一次逻辑调用。
- HTTP 尝试以实际发送为单位：`model_http_request` 开启一次尝试，`model_http_response` 和 `model_http_error` 是同一尝试的结果。只有响应而缺少请求的旧日志会按一次已确认尝试计入，并标记数据来源。
- 工具调用区分 `tool_requested`（模型请求）、`tool_executed`（执行结果）、`rejected`（审批或校验拒绝）和 `skipped`（恢复判定为重复动作或缓存读取）。`partial_success` 同时计入失败统计。
- Token 只统计带数字字段的实际 usage。`status` 为 `complete`（所有逻辑调用都有完整 usage）、`partial`（只有部分调用有 usage，或只有 Report 的最后一次请求记录）或 `unknown`。`scope` 为 `run` 或 `last_request`。缺少实际 usage 的缓存元数据不计为已知 Token。
- Agent 的最终回答（`iteration_finished(outcome="final")` 或 `report.final_answer`）不等于独立 Verifier 通过。普通 CLI 运行没有 Verifier 后续阶段，Viewer 显示为未知。

## Inspection model

Viewer 的 `GET /api/runs/<run_id>/inspection` 将多个工件归一为 `page-inspection-v2`

- `run` 保存状态、身份、时间、模型和停止原因，并标注 `status_source` 与 `duration_source`。
- `stats` 保存轮次、逻辑模型调用、HTTP 发送、工具状态分布、Checkpoint、上下文和用量统计。
- `iterations` 保存每轮的事件 ID、模型请求 ID、工具调用 ID、状态和最后判定。轮次状态与单个工具执行结果分开表示。
- `contexts` 每轮只保留一个合并快照（`prompt_built` 元数据 + `prompt_rendered` 正文）。相邻轮次的 `diff` 由服务端计算；任意两个快照的对比由 Viewer 在浏览器内计算。
- `models` 保存逻辑模型请求及其 HTTP 尝试生命周期。请求、响应和错误通过 `event_id` 关联，正文只保留在 `raw` 中一次。
- `tools` 保存工具生命周期、执行语义（`executed` / `rejected` / `skipped` / `requested`）、安全状态和工作区变化，正文通过事件 ID 引用。
- `recovery` 保存恢复事件、Journal 和 Checkpoint 引用。
- `evaluation` 只映射已有报告中的 Verifier、Evaluation 和 Metrics 字段。
- `raw` 保存有界的归一化事件集合，并标出 `truncated` 和 `skipped`。

`diff.source` 区分 `metadata`（运行时记录的结构化差异）、`text`（Viewer 根据两份 Prompt 计算的文本差异）以及组合。`text_truncated` 表示文本差异超过 240 行被截断。结构化差异和文本差异都不是 Harness 决策记录；Harness 决策以 `model_parsed`、`recovery_reconciled` 等原始事件为准。

Inspection 快照最多读取 12,000 条记录和 32 MiB。损坏或超大记录会被跳过并计入 `skipped`，后续有效事件仍可读取；单条记录超过丢弃上限时 `truncated` 为真。服务端按三个工件的 mtime/size 缓存已构建结果，工件未变化时不重复解析。

该接口只读。Viewer 不写回 Task、Session、Journal 或 Checkpoint。
