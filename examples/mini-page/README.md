# mini-page 教学实现

这是 Page 的独立教学包，用少量代码展示 ContextManager、AgentLoop、ToolExecutor 和运行工件之间的关系。它有自己的 `pyproject.toml`、`mini_page` 包和测试，不属于主 `page` 包，也不承担主项目的完整安全、记忆与恢复能力。

从项目根目录进入本目录后运行：

```powershell
cd examples/mini-page
python -m mini_page --help
python -m mini_page "Inspect this workspace"
```

CLI 使用本目录的 FakeModelClient，不需要真实模型 API。运行输出写入所选工作区的 `.mini-page/runs/`。

如需验证教学实现，在安装 pytest 的环境中，从本目录运行 `python -m pytest -q`。主项目的运行和测试入口见[根 README](../../README.md)；主模块的手动演示见 [scratch](../../scratch/README.md)。
