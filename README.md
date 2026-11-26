# Page Minimal Agent

Page 是一个从零实现的 Python Minimal Coding Agent Harness。新版核心位于根目录 `core/`，主流程是构建上下文、调用模型、串行执行工具、回填结果并继续或结束。

旧 `page/` 包、Viewer、历史 Benchmark 和运行工件保留用于查阅与兼容；新版入口不会导入旧 Runtime。

## 快速开始

```powershell
uv sync --group dev
uv run page --help
uv run python -m core --help
uv run pytest -q
```

运行时只依赖 Python 标准库。真实 Provider 需要显式配置环境变量和模型协议；离线开发请使用 FakeProvider。每次运行的事件和状态写入 `.page/runs/<run_id>/`，可用 `python viewer/server.py` 只读复盘。

## 能力与边界

当前支持单 Agent、多轮原生工具调用、受约束文件和 Shell 工具、Session、事件、Context 预算、Skill 按需注入以及最小 Checkpoint/Resume。多 Agent、MCP 平台、数据库、复杂调度和完整 IDE 不在范围内。

`completed` 表示 Agent 正常结束，独立 Verifier 才能判断代码任务是否通过。Shell 外部副作用无法自动证明安全，未知副作用的恢复会要求人工确认。

详见 [docs/README.md](docs/README.md)、[docs/architecture.md](docs/architecture.md) 和 [docs/roadmap/roadmap-v3.md](docs/roadmap/roadmap-v3.md)。
