# Page 文档索引

正式资料从下面几个入口阅读：

| 内容 | 入口 |
| --- | --- |
| 后续工作的执行依据、环境与验收 | [Page Roadmap v2](roadmap/roadmap-v2.md) |
| 项目安装、模型配置和 CLI 使用 | [根 README](../README.md) |
| 目标架构、上下文与运行边界 | [Roadmap v2 首轮目标](roadmap/roadmap-v2.md#项目定位与首轮目标) |
| 五分钟演示、实验报告与面试问答 | [面试评审包](review-pack/README.md) |
| 固定回归与模块消融的历史口径 | [核心实验来源说明](../benchmarks/results/main-resume-repro-2026-06-07/DATA_PROVENANCE.md) |
| 历史恢复演示的原始结果与限制 | [Recovery 演示归档](../benchmarks/results/recovery-demo-archive/DATA_PROVENANCE.md) |
| CLI 交互调整记录 | [CLI 体验记录](develop/optimize-cli-ux.md) |
| 本次结构规整与验证结果 | [2026-11-18 规整记录](develop/2026-11-18-project-structure-cleanup.md) |

`develop/` 保存开发记录，`plans/` 保存计划，`my-docs/` 保存个人学习资料。除明确放行的文件外，这些目录中的本地资料默认不进入 Git；正式资料不依赖它们。移动到文档目录的 [外部文章阅读笔记](my-docs/fable5_prompt_leak_cl4_summary.md) 保留原文内容和来源说明，不属于项目实现证据。

`scripts/` 中命令的默认任务、fixture 与输出路径以项目根目录为基准；命令行显式提供的相对路径仍以启动目录为基准。为便于复现，文档中的相对路径命令统一从项目根目录运行。新的本地运行输出写入 `artifacts/` 或 `.page/`，需要长期引用的结果另行归档到 `benchmarks/results/`，并记录数据来源。
