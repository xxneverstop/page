# M2 工具、安全与修复闭环

## What changed

- `core/tools.py` 增加 `read_file`、`search`、`write_file`、`edit_file`、`run_shell`，统一由 `ToolExecutor` 顺序执行。
- `core/security.py` 增加工作区路径正规化、符号链接逃逸检查、写入和 Shell 审批、输出截断、Shell 环境白名单与超时策略。
- 工具失败始终返回带原始 `call_id` 的 `ToolResult`；Shell 非零退出保留退出码和输出，交给后续模型回合处理。
- `tests/minimal_tools_test.py` 覆盖读查改写、越界、审批、非零退出、输出截断和超时。

## Why

M2 需要把副作用限制在明确工作区，并让测试失败成为可修复的模型观察结果。实现复用标准库和现有结构化模型，没有引入新的依赖或通用插件层。

## Evidence

```text
python -m pytest -q tests/minimal_tools_test.py
4 passed
```

M1 核心测试与 M2 测试在无并发测试进程时通过。CLI 通过 `python -m core --help` 和 FakeProvider 冒烟运行。

## Limits

- Shell 仍需要显式 `allow_shell` 或审批；未知 Shell 副作用不承诺可安全重放，后续 M6 负责恢复边界。
- 当前搜索为工作区内文本搜索，不提供索引或并行执行。
- 运行环境未安装 Ruff，未执行 lint。

## Next

M3 将把工具事件接入统一 Trace/Viewer 适配，并在 CLI 展示审批、失败和退出码。

