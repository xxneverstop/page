# Page Roadmap v3

| 阶段 | 输出 | 状态 |
| --- | --- | --- |
| M0 | 旧版冻结、Worktree、规范与文档 | 已验收 |
| M1 | Minimal Agent Core、Session、Provider、事件 | 已验收（FakeProvider） |
| M2 | Coding 工具、安全与失败修复闭环 | 已验收（离线） |
| M3 | Trace、Viewer 适配、CLI 进度 | 已验收（旧 Viewer 兼容） |
| M4 | Context 预算、压缩、freshness、A/B | 已验收基础实现；真实 A/B 待 Provider |
| M5 | Skill 元信息与按需注入 | 已验收基础实现；真实对照待 Provider |
| M6 | Checkpoint、Action Journal、显式 Resume | 已验收限定场景 |
| M7 | 独立 Verifier、任务集、报告和交付 | 已验收离线六任务；真实任务待冻结 |

关键路径为 M0 → M1 → M2 → M3 → M4/M5 → M7；M6 是受限可靠性专题。每个阶段必须有测试和运行证据，历史结果不混入新指标。
