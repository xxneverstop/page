# 开发与验证

要求 Python 3.10+。安装开发依赖后运行：

```powershell
uv sync --locked --group dev
uv run pytest -q
uv run page --help
uv run python -m core --help
```

离线测试不得依赖模型凭据；使用 FakeProvider 覆盖直接回答、多轮工具和失败回填。真实模型验证需要显式配置环境变量，并使用受控工作区。

Viewer：`python viewer/server.py --runs-dir .page/runs`，只读读取运行工件。新运行使用 `core.observability.TraceWriter` 写入 JSONL 和原子状态文件。

提交前检查：`git status --short`、`pytest -q`、CLI `--help` 冒烟、至少一份 FakeProvider Trace，以及独立 Verifier 结果。默认 `pytest -q` 只收集 `tests/minimal_*` 和 `tests/unit/test_minimal_support.py`；旧 `tests/` 用例保留为历史参考，因其绑定旧 `page` Runtime，需显式指定后单独迁移。
