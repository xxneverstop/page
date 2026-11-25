# Page Agent Execution Inspector

Page Agent Execution Inspector 是 Page 的本地运行观测和调试工具。它读取 `.page/runs/<run_id>/` 中已经落盘的工件，以只读方式复盘 Agent Loop、上下文、模型请求、工具执行、恢复证据和评测结果。

## Windows 启动

在仓库根目录执行

```powershell
python viewer/server.py
```

打开 `http://127.0.0.1:8765/`。服务只绑定本机回环地址，默认读取仓库的 `.page/runs/`。

查看评测或归档目录时，传入直接包含 `run_*` 子目录的路径

```powershell
python viewer/server.py --runs-dir 'D:/path/to/evaluation/runs' --port 8766
```

另开一个 PowerShell 窗口运行 Page。需要保存完整 Prompt、Provider 请求与响应以及工具阶段正文时，显式开启详细 Trace

```powershell
python -m page --trace-detail
```

默认采集保留运行所需的摘要字段。详细采集会增加本地工件体积，并可能包含任务文本、源码片段和工具输出。运行完成后再用查看器复盘，分享工件前先按项目资料规则检查内容。

## 视图

| 视图 | 复盘内容 |
| --- | --- |
| 概览 | Task、Run、Session、状态、停止原因、模型、工具协议、耗时、调用统计、上下文预算和最终回答 |
| 执行 | Agent Loop 轮次、Context → Model → Decision → Tool / Result 的反馈链路、轮次事件和证据入口 |
| 上下文 | 分段预算、实际 Prompt、Token 估算、压缩记录、Freshness 信息和相邻快照 Diff |
| 模型 | 逻辑模型请求、Provider 输入、Adapter 提取、Harness 判定和 HTTP 尝试 |
| 工具 | 工具参数、权限和审批阶段、风险、结果、受影响路径、Diff 摘要与 Action ID |
| 恢复 | Recovery decision、Action Journal、Checkpoint 和已对账、可重试、跳过、人工复核证据 |
| 评测 | 已有 report 中的独立 Verifier、Evaluation、Metrics 和运行指标。缺少字段时显示未知 |
| 原始 Trace | 有界的完整 JSONL 事件、分类筛选、搜索和原始字段详情 |

左侧运行列表支持 Run 搜索和状态筛选。顶部开关控制是否跟随最新 Run。选择事件、模型请求、工具调用或上下文快照后，右侧 Evidence 抽屉会展示关联 ID、实际输入、判断、结果和原始字段。复制按钮只把当前已展示的证据写入本机剪贴板。

## HTTP 接口

查看器保留三个基础接口

- `GET /api/runs` 返回可浏览的 Run 摘要。
- `GET /api/runs/<run_id>/events?offset=<n>` 增量读取 JSONL，适合实时跟随。
- `GET /api/runs/<run_id>/report` 读取脱敏后的运行报告。

页面使用 `GET /api/runs/<run_id>/inspection` 获取统一的 `page-inspection-v1` 模型。该接口组合 `trace.jsonl`、`task_state.json` 和 `report.json`，对历史事件补齐 Viewer 推导的关联 ID，并返回 `raw.truncated` 与 `raw.skipped`。Inspection 快照最多读取 12,000 条记录和 32 MiB，原始事件接口仍使用增量读取。

## Trace 关联

当前运行时写入 `page-trace-v2`。事件公共字段包括 `event_id`、`event_seq`、`run_id`、`task_id`、`session_id`、`created_at`、`iteration`、`iteration_id`、`model_request_id` 和 `tool_call_id`。关联规则和兼容策略见 [Page Trace Format](../TRACE_FORMAT.md)。

`iteration_id` 表示一次 Agent Loop 轮次。`model_request_id` 表示一次逻辑模型请求，HTTP 重试以 `attempt` 记录在同一请求下。`tool_call_id` 贯穿 `tool_requested`、`tool_stage` 和 `tool_executed`。历史 Trace 缺少这些字段时，查看器会生成稳定的 Viewer ID，并在界面标记「旧日志推导」或「Viewer 推导」。这些 ID 用于复盘和导航，恢复动作继续由持久化状态、Journal、Checkpoint 和 Agent Core 的安全规则决定。

## 安全边界

查看器是本机只读服务。服务端校验 Host、Origin、请求路径和运行目录，拒绝路径穿越、链接文件和运行目录外的工件。运行时在写入 Trace 和 Report 前进行字段级脱敏，API Key、Authorization Header 和已配置凭据值不会作为明文证据展示。详细 Trace 仍可能包含业务文本、源码片段和工具结果，分享前需要人工检查。

## Roadmap 验收

| 阶段 | 查看器重点 |
| --- | --- |
| S1 | Agent Loop 轮次、工具调用配对、工具反馈和下一轮请求 |
| S2 | Context 预算、压缩、Freshness、实际 Provider 输入和快照 Diff |
| S3 | Skill 加载、选择、注入和预算字段。当前以已有 Trace 证据为准 |
| S4 | Action Journal、Checkpoint、恢复决策、跳过和重试证据 |
| S5 | 独立验收、实验指标、策略对比和失败归因 |
| S6 | 真实运行复盘、演示路径和可分享证据 |
| S7 | 按需增加数据源、筛选器和展示优化 |

查看器不会根据 Agent 的最终回答推断独立验收通过，也不会把缺失的 Provider、Token 或 Verifier 字段填成估算成功值。未知数据会在页面上明确显示。

按 `Ctrl+C` 结束本地查看服务。终端查看器仍可用于快速跟随

```powershell
python scripts/watch_trace.py
```
