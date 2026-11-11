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

首次使用，在仓库根目录复制配置模板：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，填写所选后端的 API Key，并按服务配置模型和接口地址。默认后端是 DeepSeek，对应 `PAGE_DEEPSEEK_API_KEY`、`PAGE_DEEPSEEK_MODEL` 和 `PAGE_DEEPSEEK_API_BASE`；其他后端的配置项见 [.env.example](.env.example)。`.env` 已被 Git 忽略。

配置完成后，启动交互模式或执行单次任务：

```powershell
python -m page
python -m page "概述当前项目的目录结构"
```

通过 `PAGE_PROVIDER` 或命令行 `--provider` 可选择 `deepseek`、`openai`、`anthropic`、`ollama`；命令行参数优先。Ollama 使用本地服务，需要先启动服务并准备对应模型。

`openai` 后端使用 Responses API，请将 `PAGE_OPENAI_API_BASE` 设置为支持 `/responses` 的基础地址；仅支持 `/chat/completions` 的服务无法直接接入。`anthropic` 和 `deepseek` 后端使用 Anthropic-compatible Messages API。

默认使用文本工具协议；OpenAI/Anthropic-compatible 后端（含 DeepSeek 接入）可显式启用原生 Tool Calling：

```powershell
python -m page --provider openai --tool-protocol native "Inspect this repository"
```

原生协议需要服务端支持对应的工具调用字段；不支持时使用 `--tool-protocol text`。当前 Ollama 接入只支持文本工具协议。

## 会话恢复与验证

在原工作区恢复最近一次保存的会话：

```powershell
python -m page --resume latest
```

也可使用 `--resume <session_id>` 指定会话。恢复时保持原来的后端、模型和工具协议配置；原生协议会话需继续传入 `--tool-protocol native`。框架会核对 checkpoint、工作区及动作日志，再决定继续执行或要求人工复核。

离线恢复演示不会调用真实模型，也不会修改项目源码：

```powershell
python scripts/interview_demo.py --all
```

安装测试依赖后运行快速回归：

```powershell
python -m pip install pytest
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

架构说明见 [Agent Harness v1](docs/architecture/agent-harness-v1-overview.md)，演示和面试材料见 [面试评审包](docs/review-pack/README.md)。
