# 历史 Recovery 演示归档

本目录于 2026-11-18 整理项目结构时，从本地 `artifacts/` 原样复制已有 JSON。未重新运行模型、未修改历史数据，原文件仍保留在本地 `artifacts/` 中。归档日期不是实验日期。

| 文件 | 原始 captured_at（UTC） | 规模 | blind / guarded verifier 通过数 |
| --- | --- | --- | --- |
| [FakeModel 原始结果](interview-recovery-fake-final.json) | `2026-08-05T13:26:50.611230+00:00` | 3 类任务 × 2 模式 × 1 次 = 6 次 | 3/3、3/3 |
| [DeepSeek 原始结果](interview-recovery-deepseek-final.json) | `2026-08-05T13:24:37.958577+00:00` | 3 类任务 × 2 模式 × 2 次 = 12 次 | 4/6、6/6 |

两份原始文件的 SHA-256：

```text
interview-recovery-fake-final.json
bf3382075da86c74b654d3127af51a6728019521e8e5e63271225d3e484118f3
interview-recovery-deepseek-final.json
b096f4478657bdf4c6fc868d61e7737b62f72df8367ba1d744414b8e52c6e54b
```

## 可以从归档中核对什么

原始 rows 保留每次运行的任务、恢复方式、verifier 结果、模型请求、工具步数及 usage 等摘要；variants 保存分组汇总。任务仅有 `write_after_commit_crash`、`patch_after_commit_crash`、`stale_file_drift` 三类合成故障。

FakeModel 用于验证状态机；guarded 组跳过 2 次重复文件动作。DeepSeek 的两次 blind 失败均来自 `stale_file_drift`，真实模型组没有触发重复动作跳过。因此 4/6 → 6/6 只能作为这次恢复组合的小样本观察，不能单独归因于动作去重，更不能外推为通用 Coding Agent 或生产成功率。

## 缺失的信息与复现边界

原始 JSON 没有固定实际模型版本、运行时 commit、完整解码配置，也未关联逐 Run 的 trace、diff、Verifier stdout/stderr。这里不推测或补造这些字段，不把当前代码版本当成历史实验版本。当前目录是历史摘要证据，不是完整可复现的实验现场。

从项目根目录只读展示历史结果，不会调用模型：

```powershell
python scripts/interview_demo.py --scenario recovery --model deepseek --output benchmarks/results/recovery-demo-archive/interview-recovery-deepseek-final.json --show-latest
```

新离线运行仍写本地 `artifacts/`，避免覆盖归档：

```powershell
python scripts/interview_demo.py --scenario recovery --model fake --repetitions 1 --output artifacts/interview-recovery-fake-demo.json
```

新的真实模型实验需要单独确认模型配置与成本预算，并记录完整来源。实验解释见 [Recovery 报告](../../../docs/review-pack/Recovery主亮点实现与实验报告.md)。
