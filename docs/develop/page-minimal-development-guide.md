# Page Minimal Agent 开发运行手册

本文以 `rebuild/minimal-agent` 分支当前版本为准。新版运行核心在根目录 `core/`；根目录下的 `page/` 是旧版 Runtime，当前只用于历史查阅、旧实验和回退。

## 1. 目录和入口

| 内容 | 用途 | 当前策略 |
| --- | --- | --- |
| `core/` | 新版 Agent、Provider、工具、安全、Context、Skill、恢复和评测 | 正式运行入口 |
| `page/` | 旧版 Page Runtime | legacy，暂保留；不参与新版打包和 CLI |
| `viewer/` | 只读 Trace Viewer | 保留，新旧运行工件都依赖它 |
| `benchmarks/minimal_tasks.json` | 新版六个离线任务 | 保留，供 M7 评测使用 |
| `benchmarks/results/` | 历史实验和 Provenance | 原样保留，不与新版指标混算 |
| `scripts/run_minimal_eval.py` | 新版离线评测入口 | 保留 |
| `scripts/*`、旧 `tests/` | 多数依赖旧 `page` 包的历史实验和测试 | 删除 `page/` 前需要一起归档或删除 |

新版命令入口有两个，实际指向同一套 `core` 代码：

```powershell
uv run page --help
uv run python -m core --help
```

安装后的 console script 由 `pyproject.toml` 中的 `page = "core.cli:main"` 提供。新版打包只发现 `core*`，不会把旧 `page*` 包放进 wheel。

## 2. 安装开发环境

要求 Python 3.10 或更高版本。推荐使用项目锁定的 uv 工作流：

```powershell
Set-Location D:\workspace\page-minimal
uv sync --group dev
uv run python -c "import core; print(core.__file__)"
```

没有 uv 时，可以使用当前 Python 的虚拟环境：

```powershell
python -m pip install -e .
python -m core --help
```

运行时核心只使用 Python 标准库；开发依赖主要用于 pytest 和可选的代码检查。

## 3. 最小离线运行

默认 Provider 是确定性的 `FakeProvider`，不需要 API Key：

```powershell
uv run page --provider fake --workspace D:\workspace\page-minimal "描述当前项目的核心入口"
```

省略 `--provider fake` 也会使用 FakeProvider：

```powershell
uv run page --workspace D:\workspace\page-minimal "读取项目说明"
```

FakeProvider 默认只返回固定的最终回答，适合检查 CLI、运行工件和状态落盘；它不会代表真实模型已经完成 Coding 任务。需要验证工具循环时，使用默认测试、`run_minimal_eval.py` 或脚本化 Provider 测试。

工作区默认是当前目录，也可以明确指定一个临时目录：

```powershell
$workspace = 'D:\tmp\page-manual-workspace'
New-Item -ItemType Directory -Force $workspace | Out-Null
Set-Content -LiteralPath (Join-Path $workspace 'sample.py') -Value "def answer():`n    return 42`n" -Encoding utf8
uv run page --provider fake --workspace $workspace "检查 sample.py"
```

## 4. 工具权限和安全边界

新版 CLI 默认允许只读工具：

- `read_file`：读取工作区内的 UTF-8 文件。
- `search`：搜索工作区文件。

涉及副作用的工具必须显式打开：

```powershell
# 允许 write_file / edit_file
uv run page --provider openai --allow-write ... "修改受控工作区中的文件"

# 允许 run_shell；通常与 --allow-write 一起按任务需要开启
uv run page --provider openai --allow-write --allow-shell ... "运行测试并修复失败"
```

工具执行器会在副作用前检查工作区边界、符号链接、审批策略和参数。Shell 使用受限工作目录和环境变量，默认超时 30 秒，并保留退出码和截断标记。测试退出码非零会作为模型可见的 `ToolResult` 回填，不自动等同于 Agent 失败。

不要把真实密钥写入命令行历史或 Trace。PowerShell 环境变量写法如下：

```powershell
$env:PAGE_API_BASE = 'https://api.example.com/v1'
$env:PAGE_MODEL = 'model-name'
$env:PAGE_API_KEY = '***'
```

## 5. Skill 按需加载

Skill 正文从工作区的 `skills/<name>/SKILL.md` 按需读取。当前仓库提供 `coding-bugfix` 示例：

```powershell
uv run page --provider fake --workspace D:\workspace\page-minimal --skill coding-bugfix "检查一个小型修复任务"
```

Skill 只提供上下文指令，不能绕过工具权限、路径约束或审批。使用不存在的 Skill 前，先确认对应目录和 `SKILL.md` 存在。

## 6. OpenAI-compatible Provider

适配器请求 `<base-url>/chat/completions`，要求服务返回 Chat Completions 原生 `tool_calls` 字段：

```powershell
uv run page `
  --provider openai `
  --base-url $env:PAGE_API_BASE `
  --model $env:PAGE_MODEL `
  --api-key $env:PAGE_API_KEY `
  --workspace D:\tmp\page-manual-workspace `
  --allow-write `
  --allow-shell `
  "运行测试，依据失败信息修复代码并再次运行测试"
```

也可以只设置 `PAGE_API_BASE`、`PAGE_MODEL` 和 `PAGE_API_KEY`，再省略对应命令行参数。当前适配器是协议级实现，真实模型质量、计费和服务端兼容性需要在受控工作区单独验证。

## 7. Trace 和 Viewer

每次 CLI 运行默认写入：

```text
.page/runs/<run_id>/
├── trace.jsonl
├── task_state.json
└── report.json
```

可以指定其他输出目录：

```powershell
uv run page --provider fake --trace-dir D:\tmp\page-runs "生成一份运行记录"
```

启动只读 Viewer：

```powershell
uv run python viewer/server.py --runs-dir .page/runs --port 8765
```

浏览器打开 `http://127.0.0.1:8765/`。如果 CLI 使用了自定义 `--trace-dir`，Viewer 的 `--runs-dir` 必须指向同一个目录。Viewer 不参与 Agent 决策，只读取已经落盘的工件。

## 8. 自动验证命令

提交或发起评审前，按顺序执行：

```powershell
uv run pytest -q
uv run python -m compileall -q core viewer scripts
uv run python scripts/run_minimal_eval.py
uv build --offline --wheel
git diff --check
git status --short --branch
```

当前默认回归是新版核心测试，结果应为 16 passed。旧 `tests/` 中的非 minimal 用例仍绑定旧 `page` Runtime，不属于新版默认基线。

## 9. 手动测试顺序

### P0：每次改动都做

1. 运行 `uv run page --help` 和 `uv run python -m core --help`，确认两个入口都能启动。
2. 用 FakeProvider 执行一次任务，检查输出目录中同时存在 `trace.jsonl`、`task_state.json` 和 `report.json`。
3. 启动 Viewer，确认运行列表能看到该 Run，状态、停止原因和事件数量可读。
4. 运行 `uv run pytest -q` 和 `uv run python scripts/run_minimal_eval.py`。

### P1：修改工具、安全或上下文后做

1. 在工作区内读取文件、搜索字符串；确认结果正确。
2. 不带 `--allow-write` 尝试写文件，确认调用被拒绝且有清晰错误。
3. 带 `--allow-write` 修改临时文件，确认文件内容和 Trace 一致。
4. 传入 `..`、工作区外绝对路径和指向外部的符号链接，确认被拒绝。
5. 执行返回码为 1 的测试命令，确认退出码回填而不是静默丢失；再执行成功命令，确认可继续。
6. 执行超时 Shell，确认进程被终止并返回 `shell_timeout`。
7. 使用 `--skill coding-bugfix`，在 Trace 或 Context 证据中确认正文被注入；不选 Skill 时确认没有该正文。

### P1：修改恢复或持久化后做

1. 写入 Checkpoint 和 Action Journal，重启后调用显式 Resume 决策。
2. 对 `applied`、`failed` 和 `unknown` 三类动作分别检查 `can_resume` 结果。
3. 确认普通下一轮 Context 构建不会偷偷触发恢复对账，也不会把一次测试失败误判为未知副作用。

### P2：有真实 Provider 凭据时做

1. 先做只读任务，确认真实模型能读取文件并返回最终回答。
2. 再做小型“失败测试 → 读取错误 → 修改 → 重跑测试”任务，使用独立 Verifier 检查文件和测试结果。
3. 复盘 Viewer 中的 Context、模型请求、每个 `call_id` 对应的 ToolResult、最终状态和报告。
4. 记录模型、版本、预算、耗时、工具次数和失败原因；不要把 FakeProvider 结果当成真实成功率。

## 10. 清理建议

### 可以立即清理的本地产物

以下目录未被 Git 跟踪，删除后可由命令重新生成：

```powershell
Remove-Item -Recurse -Force build, dist, page.egg-info
Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
```

`.page/` 是本地运行证据，完成 Viewer 复盘后再清理；`.venv/` 是开发环境，确认不再使用后再删除。

### 删除旧 `page/` 前的清单

旧 `page/` 可以从新版正式运行链路删除，但应先处理所有仍引用它的旧测试和脚本：

1. 归档或删除 `tests/integration/`、`tests/fault_injection/`、`tests/regression/` 以及非 minimal 的旧单元测试。
2. 归档或删除 `scripts/interview_demo.py`、`collect_resume_metrics.py`、`run_large_scale_experiments.py`、`run_provider_experiments.py`、`run_step_budget_experiment.py`。
3. 给 `docs/review-pack/`、`docs/roadmap/roadmap-v2.md` 和旧 `docs/develop/` 文档加上 legacy 说明，或移动到明确的 `docs/archive/`。
4. 再删除 `page/`，运行本手册第 8 节的全部验证，并检查 `import core`、wheel 内容和 Viewer 读取均正常。

因此当前建议是：先保留 `page/` 作为可回看的 legacy 目录，先清理生成物；等确认不再需要旧实验和旧测试后，再把“旧包 + 旧入口”作为一个整体删除。
