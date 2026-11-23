# Page 项目结构规整记录

> 日期：2026-11-18。基线：`master`，`2ba3511065dbd44ec0d8f59e9d864f435db207a4`。执行前工作区干净。
> 来源：本次对话中确认的五项结构规整方案。

这次整理让评测入口、测试和文档更容易查找。核心 Agent 运行逻辑、恢复状态机、工具权限和任务 Schema 均未修改；主要变化是代码归位、脚本默认路径和实验资料归档。

## 代码与测试

```text
原来：metrics.py 同时放实验、聚合和报告
现在：provider_experiments.py → 模型配置与对照实验
      metrics.py              → 聚合与现有模块实验
      reports.py              → 报告生成
```

| 文件 | 实际改动 |
| --- | --- |
| `page/evaluation/metrics.py` | 由 1740 行整理为 1344 行，迁出四个 Provider 函数和三个报告函数；保留原有实验与聚合。 |
| `page/evaluation/provider_experiments.py` | 新增；保存 Provider 配置、客户端构造、任务实验和结果汇总。 |
| `page/evaluation/reports.py` | 新增；保存两种报告渲染及核心 Benchmark 报告写入。 |
| `scripts/run_provider_experiments.py` | 使用新的 Provider 入口；默认 benchmark、工作区和结果目录锚定项目根目录。 |
| `scripts/run_large_scale_experiments.py` | 从对应模块导入实验、指标和报告；修正默认项目路径。 |
| `scripts/collect_resume_metrics.py` | 报告渲染改从 reports 导入。该命令仍会执行原有模块实验。 |
| `scripts/run_step_budget_experiment.py` | 默认任务集与工作区路径锚定项目根目录。 |
| `scripts/interview_demo.py` | 补齐从外部目录运行时的导入路径，使用新的客户端构造入口，默认结果保存在项目 artifacts 下。 |
| `tests/test_metrics.py` | 同步 Provider 和报告函数的导入位置。 |
| `tests/test_script_paths.py` | 新增 9 项参数化检查，覆盖默认路径、显式相对路径、只读展示归档和五个脚本的外部目录帮助入口。 |

显式传入的相对路径仍相对于启动目录，绝对路径按原值使用。现有 CLI 参数名、公开包入口、benchmark JSON 和 fixture 位置保留。

原 `tests/test_pico.py` 的 62 个测试归位如下，原文件已移除：

| 接收文件 | 搬入用例数 |
| --- | ---: |
| 新增 `tests/test_providers.py` | 7 |
| 新增 `tests/test_cli.py` | 14 |
| `tests/test_checkpoint.py` | 10 |
| `tests/test_memory.py` | 9 |
| `tests/test_context_manager.py` | 3 |
| `tests/test_tools.py` | 2 |
| `tests/test_tool_executor.py` | 3 |
| `tests/test_run_store.py` | 2 |
| `tests/test_safety_invariants.py` | 1 |
| `tests/test_public_api_contract.py` | 3 |
| 新增 `tests/test_runtime.py` | 剩余 8 |

静态语法树对比确认：原有 161 个测试函数的名称和函数体全部保留，没有重名覆盖；28 个 slow 用例的分类保持一致。接收模块补齐本地导入和小型构造函数，`test_tool_executor.py` 的构造函数增加可选输出和参数支持，原调用方式继续有效。所有原 metrics 函数和类的语法树也保持一致。

## 文档与结果

- 新增 [文档索引](../README.md)，根 README 增加目录导航。
- `optimize-cli-ux.md` 原字节移动到本目录；根目录阅读笔记原字节移动到 `docs/my-docs/`。删除只有 `hello`、没有业务用途的根 `notes.txt`。
- 补充 `scratch/README.md` 的脚本用途及运行方法，新增 `examples/mini-page/README.md`；保留已有教学脚本位置。
- `.gitignore` 去重，定向放行新增索引、本记录和移动的两份文档；个人资料、`.env`、`.page/`、`artifacts/` 的忽略边界保留。
- 更新评审包四份文档的导航和实验结果引用，移除公开入口对未纳入版本管理的历史材料的依赖。
- 在历史核心实验来源说明中更新 reports 导入，并说明历史 JSON 未变、复跑应另选输出位置。
- 将两份最终 Recovery JSON 原字节复制到 [恢复实验归档](../../benchmarks/results/recovery-demo-archive/DATA_PROVENANCE.md)，保留本地原件。归档说明记录 SHA-256、历史实验时间、小样本边界以及缺失模型版本和 Trace 的事实。

## 验证

所有模型运行验证均为离线 FakeModel；读取 DeepSeek 历史摘要不会调用模型。

| 检查 | 实际结果 |
| --- | --- |
| `python -m pytest -q tests/test_script_paths.py --basetemp <外部短目录>` | 9 passed。 |
| `python -m pytest -q --basetemp <外部短目录>` | 首轮 164 passed、1 skipped、5 failed，耗时 105.78 秒。5 个失败均为系统临时目录中的 PermissionError，发生在实验工作区 README 的创建阶段。 |
| 将当前验证进程的 TMPDIR/TEMP/TMP 和 tempfile.tempdir 指向仓库外可写目录，复跑上述 5 项 | 5 passed，耗时 170.65 秒。测试和产品代码没有为绕过环境错误而修改。 |
| 从项目外运行 `run_step_budget_experiment.py --task-ids readme_intro_locked --budgets 6`，显式输出到临时目录 | FakeModel 1/1 通过、Verifier 通过、final 正常结束。默认 benchmark 成功定位到项目。 |
| `python scripts/interview_demo.py --scenario recovery --model deepseek --output benchmarks/results/recovery-demo-archive/interview-recovery-deepseek-final.json --show-latest` | 只读展示 12 次历史运行及 4/6、6/6 摘要，无 API 调用。 |
| `python -m page --help` | 正常退出。 |
| 原函数 AST、文档与归档字节一致性、Git 忽略边界、本地文档链接 | 均通过；归档原件保留，公开文档本地链接有效。 |
| `git diff --check` | 通过。 |
| Ruff | 未运行：当前 Python 环境未安装 ruff，版本检查返回 No module named ruff；未额外安装依赖。 |

按测试用例去重后，本次共验证 169 项通过、1 项跳过（包含新增 9 项路径检查）。这不是单次全量命令的全绿结果：首轮的五项环境错误通过独立复跑排除。

首轮全量使用 `<外部短目录>` 作为 pytest 临时根；五项复跑使用同一外部根下的 `u` 作为 pytest 临时根、`v` 作为标准库临时根。复跑范围为 `tests/test_metrics.py` 的四个消融/报告测试及 `tests/test_recovery_experiment.py::test_recovery_experiment_compares_blind_and_guarded_modes`。环境修改只作用于验证进程，临时输出检查完成后清理。

## 后续边界

本次没有调用真实模型、改写历史实验数字、提交或推送 Git。评测模块内 Provider runner 和报告函数的导入位置已经调整，仓库内调用方与现行复现说明已同步；外部个人脚本若仍使用旧导入，需要改到新模块。

此前识别的 Action Journal 多步操作和恢复语义问题属于下一阶段功能修复，不由这次文件归位解决。
