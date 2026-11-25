# S0A 离线基线（2026-11-24）

本次基线在移动 `page/` 模块前建立。Windows 上的新环境按锁同步成功，快速测试通过 167 个，全量测试通过 195 个，两次均有 1 个符号链接权限跳过。两个固定任务的 Verifier 均通过，FakeModel 恢复演示的两种模式各通过 3/3。

## 环境与复跑记录

- 源码起点为 `master` 上的 `b656097d2aa7d877a429e323bad96ee9d17f41c8`。复跑副本包含 S0A 新增的锁和架构断链修正。执行前已有的工作区改动见 Build Log。迁移前源码快照保存在本地 `artifacts/s0ab-649la8ju/s0a-source/`。
- Windows 使用 CPython `3.13.14` 和 uv `0.11.23`，按 `uv.lock` 安装 pytest `9.2.0`、Ruff `0.17.6`。首次锁定和同步获准访问官方 PyPI。复跑在仓库外的新环境使用已缓存的包，`uv` 命令带 `--no-config --no-python-downloads`。
- 在 Windows 实际账户下验证了仓库外短路径。标准库 `TemporaryDirectory` 的嵌套写入、读回和清理通过。快速和全量 pytest 分别使用独立 `--basetemp`。复跑通过 `TMPDIR`、`TEMP`、`TMP` 给标准库分配另一处临时目录。
- 起草时默认沙箱长路径上的会话写入失败，在短路径复跑中消失。`b656097` 已删除的架构页面导致文档测试失败。修正评审包链接和对应断言后，定向检查通过。复跑期间使用隔离的 `.page/` 会话和运行工件。

| 检查 | 执行方式 | 实际结果 |
| --- | --- | --- |
| 锁和新环境 | `uv lock --offline --check`，`uv sync --offline --locked --group dev` | 退出码 0，解析 11 份锁定条目。 |
| CLI | `uv run --locked --offline page --help`，`uv run --locked --offline python -m page --help` | 两种入口均以退出码 0 打印帮助。 |
| 测试收集 | `uv run --locked --offline python -m pytest --collect-only -q`，分别再次加 `-m slow` 和 `-m 'not slow'` | 分别收集 196、28、168 个节点。 |
| 临时目录与文档 | 使用独立 `--basetemp` 运行 `tests/test_session_store.py` 及 `tests/test_public_api_contract.py::test_reviewer_skeleton_docs_exist` | 3 通过。 |
| 快速离线回归 | `uv run --locked --offline python -m pytest -q -rs -m 'not slow' --tb=short --basetemp $pytestFast` | 167 通过、1 跳过、28 未选中，29.09 秒。 |
| 全量离线回归 | `uv run --locked --offline python -m pytest -q -rs --tb=short --basetemp $pytestFull` | 195 通过、1 跳过，180.34 秒。 |
| Ruff | `uv run --locked --offline python -m ruff check page scripts tests`，另加 `--output-format json` | 退出码 1，108 项既有诊断，涉及 22 项规则。数量最多的是 `I001` 27 项、`SIM117` 13 项和 `BLE001` 11 项。 |

`$pytestFast` 和 `$pytestFull` 指向该轮专用的两个短路径。两套测试的同一跳过项来自 `test_safety_invariants.py`，原因为 Windows 符号链接权限不可用。Ruff JSON 用于迁移后按规则、文件和消息逐项对照。

## 功能对照

Verifier 是由评测器独立运行的验收程序。固定任务以 `uv run --locked --offline python scripts/run_step_budget_experiment.py --mode fake --task-ids sample_beta_locked,path_escape_recovery --budgets 6 --max-total-runs 2 --workspace-root "$run/work" --output-json "$run/budget.json"` 执行。`$run` 指向本轮工件目录。退出码为 0。

| 场景 | 依据 | 观察结果 |
| --- | --- | --- |
| 改写指定文件 | `sample_beta_locked` | 1 个工具步骤，文件摘要已记录，Verifier 退出码 0。 |
| 路径校验后恢复 | `path_escape_recovery` | 2 个工具步骤，第一个错误为 `invalid_arguments`，修正后 Verifier 退出码 0。 |
| 人工拒绝和 Context 保护 | `test_risky_tool_deny_behavior`、`test_detailed_denied_approval_does_not_execute`、`test_protected_context_overflow_fails_explicitly` | 全量回归通过上述场景。 |
| 旧会话对照样本 | FakeModel 在独立目录保存会话，另一个进程用原绝对路径恢复 | 读取历史，checkpoint 为 `full-valid`，重复动作记录为 `skipped_duplicate`，续跑后历史已保存。 |
| 恢复演示 | `uv run --locked --offline python scripts/interview_demo.py --all --model fake --output "$run/recovery.json"` | `blind_resume` 和 `guarded_resume` 的 Verifier 各通过 3/3，`guarded_resume` 跳过 2 次重复动作。 |

收集清单、命令和退出码、Ruff JSON、固定任务和演示工件位于本地 `artifacts/s0ab-649la8ju/A/`。历史归档的 [17 项 SHA-256 清单](historical-sha256.txt) 用于逐字节对照。

## 条件项

本机 `.env` 文件存在。Provider 费用硬上限、可用额度及人工审批条件待核验，两题在线探索延期。本轮真实模型请求数为 0，待正式实验前补齐探索记录。

CI 按本机实测结果确定范围后评估。Docker 隔离验证归 S5。分发包的构建和安装验收按实际分发需求启动。
