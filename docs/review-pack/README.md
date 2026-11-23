# Page 面试评审包

> Reviewer index: Project pitch · Architecture map · Benchmark evidence · Sample run artifact list

> 更新于 2026-08-06

这套材料用于 Windows 11 本地面试。项目的核心亮点只有一个：**Page 能在任务中断后，先核对文件和动作状态，再安全地继续执行。**

它不是 Docker、服务部署或生产环境使用手册。

## 建议阅读顺序

1. [手动执行演示手册](./手动执行演示手册.md)：先学会怎么现场演示 Page。
2. [Recovery 主亮点实现与实验报告](./Recovery主亮点实现与实验报告.md)：了解恢复机制、实验结果和能力边界。
3. [阿里 AI 应用开发面试问题与回答](./阿里AI应用开发面试问题与回答.md)：准备常见追问和口头回答。
4. [执行清单](./执行清单.md)：面试前按清单完成复跑和自检。

项目结构与正式资料入口见[文档索引](../README.md)；恢复机制的数据流见[架构概览](../architecture/agent-harness-v1-overview.md)。

## 现场怎么演示

主流程是让 Page 修复一个真实的小程序：

```powershell
page
```

如果系统找不到 `page` 命令，改用：

```powershell
python -m page
```

快速测试和 Recovery 实验只在面试官追问可靠性时展示：

```powershell
pytest -q -m "not slow"
python scripts/interview_demo.py --scenario recovery --model fake --repetitions 1 --output artifacts/interview-recovery-fake-demo.json
```

## 一句话介绍项目

> Page 是一个本地 Coding Agent。它能读取和修改代码、运行命令，并记录每一步；任务中断后，它会先核对动作是否真的执行过，再决定跳过、重试还是交给用户处理。

## 面试时要记住的证据

- FakeModel 用来验证恢复状态机是否按设计工作。它不代表真实模型能力。
- DeepSeek 用来做小样本真实模型验证：`blind_resume` 完成 4/6，`guarded_resume` 完成 6/6。
- 这 12 次运行只覆盖 3 类人为构造的故障，不能说成线上成功率。
- 主要实验文件：
  - [FakeModel 原始结果](../../benchmarks/results/recovery-demo-archive/interview-recovery-fake-final.json)
  - [DeepSeek 原始结果](../../benchmarks/results/recovery-demo-archive/interview-recovery-deepseek-final.json)
  - [归档来源与缺失信息](../../benchmarks/results/recovery-demo-archive/DATA_PROVENANCE.md)：历史摘要没有关联完整版本与逐 Run Trace，不能当作当前版本的新实验。
- 每次运行都会留下：
  - `task_state.json`：任务最终状态；
  - `trace.jsonl`：逐步执行记录；
  - `report.json`：本次运行汇总；
  - `action_journal`：动作是否开始、完成或需要人工确认的记录，保存在 Session 和 Report 中。

架构入口见 [Agent Harness v1](../architecture/agent-harness-v1-overview.md)。
