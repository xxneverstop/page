# Page

Page 是一个用 Python 实现的本地代码智能体 Agent Harness。它不追求做完整 IDE，而是把模型调用、工具执行、上下文治理、记忆、恢复和运行审计拆成可理解、可测试的最小运行框架。

## 它解决什么问题

- 长任务中 Prompt 持续膨胀；
- Agent 重复读取已经确认过的文件；
- 进程中断后任务状态和工具副作用难以恢复；
- 模型可能调用越权、缺参或有副作用的工具；
- 只看最终回答，无法判断一次运行在哪一步失败。

## 核心流程

```text
用户请求
  → ContextManager 组装上下文
  → ModelClient 生成 Tool Call 或 Final
  → ToolExecutor 校验、审批并执行
  → Memory / Checkpoint / Action Journal 更新
  → task_state.json / trace.jsonl / report.json 落盘
```

核心代码位于 `page/`：

- `runtime.py`、`agent_loop.py`：对象装配和控制循环；
- `providers/`：OpenAI-compatible、Anthropic-compatible 等模型接入；
- `tools.py`、`tool_executor.py`：7 类工具及安全执行链；
- `context_manager.py`、`features/memory.py`：上下文预算和分层记忆；
- `checkpoint.py`、`action_journal.py`：状态恢复和副作用对账；
- `run_store.py`、`evaluation/`：运行工件和分层评测。

## 本地运行

要求 Python 3.10+。项目运行时零第三方依赖，测试使用 pytest。

```powershell
python -m pip install -e .
python -m page --help
```

默认继续使用兼容性更好的文本工具协议；OpenAI/Anthropic-compatible 后端可显式启用原生 Tool Calling：

```powershell
python -m page --provider openai --tool-protocol native "Inspect this repository"
```

离线恢复演示不会调用真实模型，也不会修改项目源码：

```powershell
python scripts/interview_demo.py --all
```

快速回归：

```powershell
python -m pytest -q -m "not slow"
```

## 工具与运行工件

Page 提供 `list_files`、`read_file`、`search`、`run_shell`、`write_file`、`patch_file`、`delegate` 7 类工具。读和受限委派属于 safe；Shell 与文件写入属于 risky，需要经过审批和安全校验。

每次 `ask()` 会在 `.page/runs/<run_id>/` 下生成：

- `task_state.json`：最终状态和停止原因；
- `trace.jsonl`：按时间追加的执行事件；
- `report.json`：面向复盘的运行摘要。

## 可复现实验

当前归档位于 `benchmarks/results/main-resume-repro-2026-06-07/`：

- 12 组 Context 配置：平均 Prompt 由 6994.33 字符降至 5575.67，平均压缩率 16.36%，最高 33.59%，当前请求保留率 100%；
- 12 个记忆任务 × 5 次重复：Memory 关闭时累计重复读文件 60 次，开启后为 0 次；
- 10 类恢复场景：覆盖 checkpoint、stale state、workspace mismatch 和 schema mismatch；
- 12 个 Harness Regression：使用确定性 FakeModel 和 Verifier，只验证运行框架合同，不代表真实模型任务成功率。
- 3/6/9 步预算离线实验：12 个任务通过数分别为 11、12、12；说明 6 步对当前固定任务集足够，不证明它对真实模型全局最优。

详细口径见 `benchmarks/results/main-resume-repro-2026-06-07/DATA_PROVENANCE.md`。
步数实验见 `benchmarks/results/real-model-2026-09/step-budget-sensitivity.json`。

## 能力边界

- 当前主体是本地单用户 CLI，不是生产级多租户平台；
- MCP、向量数据库、Web UI 和并行写入型多 Agent 不在当前范围；
- FakeModel Regression、模块消融和真实模型 Eval 必须分开解释；
- Shell 的任意外部副作用无法自动证明安全，恢复时可能要求人工复核。

面试学习材料见 `docs/mydocs/page-interview-study-guide.md`。
