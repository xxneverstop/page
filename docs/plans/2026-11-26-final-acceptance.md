# Minimal Agent 重建阶段验收（2026-11-26）

## What changed

- M0：从 `926ea0e2c3fe4a81fb31cf15a5bd6add7f84233d` 冻结 `legacy/page-pre-minimal-rebuild`，创建 `rebuild/minimal-agent` 和 `D:/workspace/page-minimal` Worktree；根目录 `core/` 成为新版唯一运行包，补齐 AGENTS、CLAUDE、架构/契约/开发文档和 roadmap-v3。
- 总体计划 `docs/plans/page-minimal-agent-rebuild-plan.md` 已原样纳入新 Worktree，作为后续人工复查的执行依据。
- M1：实现结构化 `Message`、`ToolCall`、`ToolResult`、`ModelTurn`、`AgentEvent`、`AgentResult`，FakeProvider、OpenAI-compatible 原生 Tool Calling、Session 原子 JSON、Context 投影、预算和串行多工具 Agent Loop。
- M2：实现 `read_file`、`search`、`write_file`、`edit_file`、`run_shell`，路径/符号链接/工作区边界、审批、环境白名单、输出上限、超时和进程树清理；非零退出保留 exit code 并回填模型。
- M3：实现 EventSink、TraceWriter、原子 `task_state.json`/`report.json`、Viewer 适配；旧 Viewer 识别新核心生命周期、模型和工具事件。
- M4：Context 支持消息/字符预算、Skill 注入、文件版本 freshness 检查，并保证工具调用与结果配对。
- M5：SkillStore 发现元信息，显式选择后读取正文，记录来源 hash；示例 Skill 位于 `skills/coding-bugfix/SKILL.md`。
- M6：CheckpointStore、独立 call_id 的 ActionJournal、显式 Resume 决策；未知副作用只阻止恢复，不进入普通 Context/下一轮。
- M7：六个独立 Coding 契约和独立 Verifier，提供 `scripts/run_minimal_eval.py` 和 `benchmarks/minimal_tasks.json`，区分 Agent 完成与 Verifier 通过。

## Evidence

```text
python -m pytest -q
16 passed in 2.19s

python -m core --help
通过

uv run --offline page --help
通过

uv run --offline python -c "import core; print(core.Agent.__name__)"
Agent

python scripts/run_minimal_eval.py
6 tasks, agent_completed=6, verifier_passed=6, failed=0

python -m compileall -q core viewer
通过
```

最终复核：`git diff --check` 通过；原工作区 `D:/workspace/page` 的既有未提交文件清单保持不变。

FakeProvider CLI 运行生成 `.page/runs/<run_id>/{trace.jsonl,task_state.json,report.json}`；Viewer `build_inspection` 能将该运行还原为 `page-inspection-v2`，状态为 `completed`，事件数为 7。原工作区 `D:/workspace/page` 的用户改动未被清理或覆盖。

## Why

新版核心保持单向依赖和最小数据结构，旧 `page/` Runtime 不作为兼容层导入。工具失败是模型可见事实，`completed` 不被解释为代码通过；Viewer 只读，Session 才是控制事实源。

## Limits

- 本轮没有真实 Provider 凭据，因此 OpenAI-compatible 适配只完成协议级实现和离线覆盖，未声称真实模型 Coding 成功率。
- M7 六个任务是可复现的标准库离线契约，尚未替代真实模型任务集、Context On/Off 和 Skill On/Off 统计实验。
- 旧 `tests/` 仍保留历史 Runtime 用例；默认 `pytest -q` 已切换到新核心入口。显式运行旧全量测试会触发旧实现的已知失败，不作为新基线验收。
- Ruff 未安装，未执行 lint；实现只使用标准库，未引入新的运行依赖。

## Next

后续工作从 `rebuild/minimal-agent` 继续：接入固定真实 Provider 后冻结 6–10 个真实任务，完成 Context/Skill A/B、故障注入恢复和代表性 Viewer 复盘；确认人工审查删除清单和无未提交改动后，再合并到主分支。

