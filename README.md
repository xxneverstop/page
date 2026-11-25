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

`page/cli.py` 提供命令行入口，运行框架位于 `page/core/`。

- `core/runtime.py`、`core/agent_loop.py` 装配组件并运行控制循环。
- `core/providers/` 接入 OpenAI-compatible、Anthropic-compatible 和其他模型。
- `core/tools/` 注册 7 类工具并负责校验、审批和执行。
- `core/context/` 管理上下文预算、提示前缀和分层记忆。
- `core/durability/` 保存会话并对账工具动作，`core/recovery/` 根据检查点恢复任务。
- `core/observability/` 保存运行工件，`page/evaluation/` 提供分层评测。

Python 代码可从 `page` 导入公开接口，例如 `from page import Page`。

## 本地运行

要求 Python 3.10+。项目运行时零第三方依赖。开发验证使用 `.python-version` 指定的 Python 3.13.14，基线使用 uv 0.11.23。

```powershell
uv sync --locked --group dev
uv run --locked page --help
uv run --locked python -m page --help
```

只安装 CLI 时也可以使用 `python -m pip install -e .`。

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

在已同步的环境中运行离线恢复演示、快速回归或完整回归：

```powershell
uv run --locked --offline python scripts/interview_demo.py --all --model fake
uv run --locked --offline python -m pytest -q -m 'not slow'
uv run --locked --offline python -m pytest -q
```

Windows 上如果遇到临时文件权限或长路径错误，请在仓库之外选择可写的短路径。以下以新建的 `D:/tmp/page-check` 为例，在单独的 PowerShell 运行验证。`s` 供 Python 标准库使用，`p` 只供 pytest 使用，pytest 可清空该目录。

```powershell
New-Item -ItemType Directory -Path 'D:/tmp/page-check/s'
$env:TMPDIR = $env:TEMP = $env:TMP = 'D:/tmp/page-check/s'
uv run --locked --offline python -m pytest -q --basetemp 'D:/tmp/page-check/p'
```

## 工具与运行工件

Page 提供 `list_files`、`read_file`、`search`、`run_shell`、`write_file`、`patch_file`、`delegate` 7 类工具。读和受限委派属于 safe；Shell 与文件写入属于 risky，需要经过审批和安全校验。

每次 `ask()` 会在 `.page/runs/<run_id>/` 下生成：

- `task_state.json`：最终状态和停止原因；
- `trace.jsonl`：按时间追加的执行事件；
- `report.json`：面向复盘的运行摘要。

在浏览器查看运行时间线、模型判定、工具和恢复过程：

```powershell
python viewer/server.py
```

打开 `http://127.0.0.1:8765`。实时跟随、历史复盘和评测目录的用法见 [Page Trace Web](viewer/README.md)。

在第二个 PowerShell 窗口查看格式化的中文日志：

```powershell
python scripts/watch_trace.py
```

查看器会跟踪新一轮请求。加 `--detail` 展开日志已记录的字段，加 `--once` 只回看最近一次运行。按 `Ctrl+C` 退出查看器。

要观察完整的请求与响应，在运行 Page 的窗口退出并用 `python -m page --trace-detail` 启动，再发一条新请求。查看器会依次显示用户原文、提示词分段和正文、HTTP 请求体及原始响应体、模型提取结果、操作判定和工具执行阶段。原生工具协议可能用服务端的对话状态续接，以 HTTP 请求体为准。

详细日志会写入 `.page/runs/`，可能包含问题、代码和工具结果。它沿用已有的敏感值过滤，不采集 HTTP 请求头。

## 可复现实验

当前归档位于 `benchmarks/results/main-resume-repro-2026-06-07/`：

- 12 组 Context 配置：平均 Prompt 由 6994.33 字符降至 5575.67，平均压缩率 16.36%，最高 33.59%，当前请求保留率 100%；
- 12 个记忆任务 × 5 次重复：Memory 关闭时累计重复读文件 60 次，开启后为 0 次；
- 10 类恢复场景：覆盖 checkpoint、stale state、workspace mismatch 和 schema mismatch；
- 12 个 Harness Regression：使用确定性 FakeModel 和 Verifier，只验证运行框架合同，不代表真实模型任务成功率。
- 3/6/9 步预算离线实验：12 个任务通过数分别为 11、12、12；说明 6 步对当前固定任务集足够，不证明它对真实模型全局最优。

详细口径见 `benchmarks/results/main-resume-repro-2026-06-07/DATA_PROVENANCE.md`。
步数实验见 `benchmarks/results/real-model-2026-09/step-budget-sensitivity.json`。

历史 Recovery 演示的 FakeModel 与 DeepSeek 原始结果已归档到 [recovery-demo-archive](benchmarks/results/recovery-demo-archive/DATA_PROVENANCE.md)。这是既有结果的原样保存，不是当前版本的新实验。

## 能力边界

- 当前主体是本地单用户 CLI，不是生产级多租户平台；
- MCP、向量数据库、Web UI 和并行写入型多 Agent 不在当前范围；
- FakeModel Regression、模块消融和真实模型 Eval 必须分开解释；
- Shell 的任意外部副作用无法自动证明安全，恢复时可能要求人工复核。

## 项目导航

- [`page/`](page/)：主运行框架；[`tests/`](tests/)：主项目测试。
- [`scripts/`](scripts/)：演示与评测命令；[`benchmarks/`](benchmarks/)：固定任务与归档结果。
- [文档索引](docs/README.md)：架构、演示材料与开发记录。
