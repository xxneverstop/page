# M0–M7 实施记录

## M0

基线 HEAD 为 `926ea0e2c3fe4a81fb31cf15a5bd6add7f84233d`。旧工作区 `D:/workspace/page` 保留用户未提交改动；冻结分支为 `legacy/page-pre-minimal-rebuild`；新 Worktree 为 `D:/workspace/page-minimal`，分支为 `rebuild/minimal-agent`。新核心源码目录为根目录 `core/`。

## 当前实现

- M3：`core/observability.py` 提供事件、JSONL Trace、原子状态/报告和旧 Viewer schema 适配。
- M4：事件层保留 Context 证据入口，Context 预算和 freshness 由核心 Context 模块负责。
- M5：`core/skills.py` 发现 Skill 元信息，显式选择后才读取正文并记录来源 hash。
- M6：`core/recovery.py` 提供 Checkpoint、独立 call identity 的 Action Journal 和显式 Resume 决策。
- M7：`core/evaluation.py` 通过独立 verifier 区分 Agent 完成与验证通过。

## 验证与限制

新增模块使用 Python 标准库，需和 M1/M2 核心接口联调后运行完整测试。当前未声称真实模型成功率、恢复恰好一次或自动 Skill 推荐；未知副作用要求人工复核。
