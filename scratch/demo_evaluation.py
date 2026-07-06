"""
直观观察 Page 评测与审计闭环的全部过程
═══════════════════════════════════════════════════════════════

覆盖「七、贡献点 6：评测与审计闭环」的全部内容：

  三层评测体系:
    第 1 层: Harness Regression（框架回归）
      - 12 个固定 benchmark 任务 + FakeModelClient
      - 验证 while 循环、解析器、工具校验的框架合约
    第 2 层: 模块收益评测（对照实验）
      - 2a: 上下文治理 — context stress matrix (12 组配置)
      - 2b: 记忆收益   — memory dependency experiment (12 个任务)
      - 2c: 恢复正确性 — recovery ablation (10 个场景)
    第 3 层: 运行工件聚合
      - task_state.json + trace.jsonl + report.json
      - 从 .page/runs/ 聚合工具调用统计、错误率、stop_reason 分布

用法:
  cd D:/workspace/page
  python scratch/demo_evaluation.py
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', write_through=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from page import FakeModelClient, Page, SessionStore, WorkspaceContext
from page.task_state import TaskState, STATUS_COMPLETED, STATUS_STOPPED, STATUS_FAILED
from page.run_store import RunStore


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════

_step = [0]

def hr(title):
    _step[0] += 1
    print()
    print("=" * 68)
    print(f"  [{_step[0]}] {title}")
    print("=" * 68)


def sub(title):
    print(f"\n  ── {title} ──")


def ok(msg):
    print(f"    ✓ {msg}")


def info(msg):
    print(f"    ℹ {msg}")


def show_dict(d, indent=4):
    prefix = " " * indent
    for k, v in d.items():
        if isinstance(v, dict):
            print(f"{prefix}{k}:")
            show_dict(v, indent + 2)
        elif isinstance(v, list):
            print(f"{prefix}{k}: [{len(v)} items]")
            for item in v[:5]:
                print(f"{prefix}  - {item}")
            if len(v) > 5:
                print(f"{prefix}  ... and {len(v) - 5} more")
        else:
            print(f"{prefix}{k}: {v}")


# ═══════════════════════════════════════════════════════════════
# 主演示
# ═══════════════════════════════════════════════════════════════

def demo():
    # ═══════════════════════════════════════════════════════════
    # PART A: 第 1 层 — Harness Regression（框架回归）
    # ═══════════════════════════════════════════════════════════

    hr("第 1 层：Harness Regression — 框架回归测试体系")

    print("""
    目的: 验证 Page 框架本身的行为一致性（不依赖任何 LLM API）
    方法: 12 个固定 benchmark 任务 + FakeModelClient(脚本化输出)
    指标: test 通过率、预算内完成率、verifier 通过率

    关键类: BenchmarkEvaluator (evaluator.py:376-569)
      - load()      → 加载 coding_tasks.json
      - run()       → 遍历所有任务，逐任务执行 + 汇总
      - run_task()  → 执行单个任务: 复制 fixture → 构建 agent → ask → 验证
    """)

    # ─── A1: 加载 benchmark ───
    sub("A1: 加载 benchmark — validate_benchmark() 做了什么")

    from page.evaluation.evaluator import load_benchmark, validate_benchmark, summarize_rows

    benchmark = load_benchmark()
    print(f"      加载了 {len(benchmark['tasks'])} 个固定 benchmark 任务\n")

    # 展示任务分类分布
    from collections import Counter
    cats = Counter(t["category"] for t in benchmark["tasks"])
    print("      任务分类分布:")
    for cat, count in cats.most_common():
        print(f"        {cat}: {count} 个")

    sub("A2: benchmark schema 验证规则 (validate_benchmark)")
    print("""
      必需字段 (REQUIRED_BENCHMARK_KEYS):
        schema_version, tasks

      每个 task 的必需字段 (REQUIRED_TASK_KEYS):
        id, prompt, fixture_repo, allowed_tools,
        step_budget, expected_artifact, verifier, category

      额外校验:
        - id 不能重复
        - fixture_repo 目录必须存在
        - allowed_tools 必须在 legal_tool_names() 中
        - step_budget >= 1
    """)

    # ─── A3: 展示单个 task 的定义 ───
    sub("A3: 示例 — 一个 benchmark task 的完整定义")

    task = benchmark["tasks"][0]
    show_dict(task)
    info(f"脚本化输出 (SCRIPTED_MODEL_OUTPUTS[{task['id']}]):")
    from page.evaluation.evaluator import SCRIPTED_MODEL_OUTPUTS
    for line in SCRIPTED_MODEL_OUTPUTS[task["id"]]:
        print(f"        {line}")

    # ─── A4: 手动执行一个 task — 观察完整流程 ───
    sub("A4: 手动模拟 BenchmarkEvaluator.run_task() 的完整流程")

    with tempfile.TemporaryDirectory(prefix="page-eval-demo-") as tmp:
        from page.evaluation.evaluator import (
            BenchmarkEvaluator, _scripted_outputs_for_task,
            _artifact_path_for_task, _digest_file,
        )
        import shutil

        task = benchmark["tasks"][0]  # readme_intro_locked
        # fixture_repo 是相对于 repo root 的路径
        fixture_source = Path(task["fixture_repo"])
        fixture_copy = Path(tmp) / task["id"] / fixture_source.name
        fixture_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(fixture_source), str(fixture_copy))

        workspace = WorkspaceContext.build(fixture_copy, repo_root_override=fixture_copy)
        store = SessionStore(fixture_copy / ".page" / "sessions")
        run_store = RunStore(fixture_copy / ".page" / "runs")
        model = FakeModelClient(_scripted_outputs_for_task(task))
        agent = Page(
            model_client=model, workspace=workspace, session_store=store,
            run_store=run_store, approval_policy="auto",
            max_steps=int(task["step_budget"]), allowed_tools=task["allowed_tools"],
        )

        # 观察执行前状态
        print(f"      task id: {task['id']}")
        print(f"      prompt:  {task['prompt']}")
        print(f"      fixture: {task['fixture_repo']} → 复制到 {fixture_copy}")
        print(f"      allowed_tools: {task['allowed_tools']}")
        print(f"      step_budget: {task['step_budget']}")
        print(f"      initial history: {len(agent.session['history'])} 条 (空)")

        # 执行
        answer = agent.ask(task["prompt"])
        task_state = agent.current_task_state

        # 观察执行后状态
        run_dir = Path(agent.current_run_dir)
        print(f"\n      执行结果:")
        print(f"        final_answer: {answer[:80]}")
        print(f"        tool_steps:   {task_state.tool_steps}")
        print(f"        attempts:     {task_state.attempts}")
        print(f"        stop_reason:  {task_state.stop_reason}")
        print(f"        status:       {task_state.status}")
        print(f"        run_dir:      {run_dir}")

        # 检查 3 个运行工件
        print(f"\n      3 个运行工件:")
        for name in ["task_state.json", "trace.jsonl", "report.json"]:
            p = run_dir / name
            if p.exists():
                size = p.stat().st_size
                print(f"        ✓ {name}  ({size} bytes)")
            else:
                print(f"        ✗ {name}  MISSING!")

        # Verifier 验证
        import subprocess as sp
        verifier = sp.run(task["verifier"], cwd=str(fixture_copy), shell=True,
                          capture_output=True, text=True)
        print(f"\n      verifier: {task['verifier'][:60]}...")
        print(f"        exit_code: {verifier.returncode}")
        within_budget = task_state.tool_steps <= int(task["step_budget"])
        verifier_passed = verifier.returncode == 0
        expected_exists = (fixture_copy / _artifact_path_for_task(task)).exists()
        print(f"        within_budget: {within_budget}")
        print(f"        verifier_passed: {verifier_passed}")
        print(f"        expected_artifact_exists: {expected_exists}")
        ok(f"全 pass = {within_budget and verifier_passed and expected_exists}")

        # trace.jsonl 内容
        sub("trace.jsonl — 事件流结构")
        trace = [
            json.loads(line)
            for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        for event in trace:
            ev_type = event.get("event", "?")
            ev_name = event.get("name", "")
            ev_status = event.get("tool_status", "")
            print(f"        [{ev_type}] {ev_name} {ev_status}")

        # report.json 内容
        sub("report.json — 运行摘要")
        report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        print(f"        run_id:       {report['run_id']}")
        print(f"        status:       {report['status']}")
        print(f"        stop_reason:  {report['stop_reason']}")
        print(f"        tool_steps:   {report['tool_steps']}")
        print(f"        attempts:     {report['attempts']}")
        print(f"        checkpoint_id: {report['checkpoint_id']}")
        print(f"        resume_status: {report['resume_status']}")

    # ─── A5: summarize_rows — 汇总逻辑 ───
    sub("A5: summarize_rows() — 评分卡怎么算的")

    print("""
      汇总指标:
        total_tasks        任务总数
        passed / failed    通过 / 失败数
        pass_rate          = passed / total_tasks
        within_budget      预算内完成数 (tool_steps <= step_budget)
        verifier_passes    verifier 通过数
        within_budget_rate = within_budget / total_tasks
        verifier_pass_rate = verifier_passes / total_tasks
        failure_category_counts  按失败原因分组

      单个 task 判定 pass 的 4 个条件 (AND):
        ① within_budget: tool_steps <= step_budget
        ② verifier_passed: verifier.exit_code == 0
        ③ expected_artifact_exists: 预期产出文件存在
        ④ non_failure_stop_reason: stop_reason == "final_answer_returned"

      失败分类优先级 (failure_category):
        ① missing_artifact  >  ② budget_exceeded
        >  ③ verifier_failed  >  ④ failure_stop_reason
    """)

    # ═══════════════════════════════════════════════════════════
    # PART B: TaskState — 状态机
    # ═══════════════════════════════════════════════════════════

    hr("TaskState 状态机 — 一次 run 的生命周期追踪")

    ts = TaskState.create(task_id="demo-task", user_request="fix the bug in utils.py")
    print(f"      创建 TaskState:")
    print(f"        run_id:       {ts.run_id}")
    print(f"        task_id:      {ts.task_id}")
    print(f"        user_request: {ts.user_request}")
    print(f"        status:       {ts.status}")
    print(f"        tool_steps:   {ts.tool_steps}")

    sub("模拟 3 轮工具调用的状态变化")
    for i in range(3):
        ts.record_attempt()
        ts.record_tool(f"tool_{i+1}")
        print(f"      轮次 {i+1}: attempts={ts.attempts} tool_steps={ts.tool_steps} last_tool={ts.last_tool}")

    sub("正常结束: finish_success()")
    ts.finish_success("bug fixed: changed a-b to a+b")
    print(f"      status={ts.status} stop_reason={ts.stop_reason}")
    print(f"      final_answer={ts.final_answer[:50]}...")

    sub("to_dict() — 完整的运行快照")
    show_dict(ts.to_dict())

    sub("状态枚举速查")
    print(f"""
      STATUS_RUNNING     = "running"   (初始状态，刚创建时)
      STATUS_COMPLETED   = "{STATUS_COMPLETED}"  (finish_success() 后)
      STATUS_COMPLETED   = "{STATUS_COMPLETED}"   finish_success()
      STATUS_STOPPED     = "{STATUS_STOPPED}"     stop()
      STATUS_FAILED      = "{STATUS_FAILED}"      stop_model_error()

      STOP_REASON 共 9 种:
        final_answer_returned / step_limit_reached / retry_limit_reached
        / model_error / tool_timeout / approval_denied
        / delegate_failed / persistence_error / resume_load_error
    """)

    # ═══════════════════════════════════════════════════════════
    # PART C: RunStore — 运行工件落盘
    # ═══════════════════════════════════════════════════════════

    hr("RunStore — 3 类运行工件的落盘机制 (run_store.py)")

    with tempfile.TemporaryDirectory(prefix="page-runstore-") as tmp:
        rs = RunStore(Path(tmp) / ".page" / "runs")

        ts2 = TaskState.create(task_id="demo", user_request="test run store")
        ts2.finish_success("done")

        # start_run: 创建 run 目录 + 写入初始 task_state
        run_dir = rs.start_run(ts2)
        print(f"      start_run() → 创建目录: {run_dir}")

        # append_trace: jsonl 追加写入
        rs.append_trace(ts2, {"event": "run_started", "created_at": "2026-07-01T10:00:00+00:00"})
        rs.append_trace(ts2, {"event": "tool_executed", "name": "read_file",
                               "tool_status": "ok", "duration_ms": 12.5,
                               "created_at": "2026-07-01T10:00:01+00:00"})
        rs.append_trace(ts2, {"event": "run_finished", "final_answer": "done",
                               "run_duration_ms": 1500.0,
                               "created_at": "2026-07-01T10:00:02+00:00"})
        print(f"      append_trace() × 3 → 追加 3 个事件")

        # write_report: 原子写 report.json
        report = {"run_id": ts2.run_id, "status": ts2.status,
                   "tool_steps": ts2.tool_steps, "stop_reason": ts2.stop_reason}
        rs.write_report(ts2, report)
        print(f"      write_report() → 原子写 (先写临时文件再 replace)")

        # 验证 3 个工件
        print(f"\n      最终工件:")
        for name in ["task_state.json", "trace.jsonl", "report.json"]:
            p = run_dir / name
            print(f"        {p}")
            if name == "trace.jsonl":
                lines = p.read_text(encoding="utf-8").strip().split("\n")
                for line in lines:
                    ev = json.loads(line)
                    print(f"          → {ev['event']}")
            elif name == "report.json":
                r = json.loads(p.read_text(encoding="utf-8"))
                print(f"          → {json.dumps(r, indent=12)}")

    # ═══════════════════════════════════════════════════════════
    # PART D: 第 2 层 — 模块收益评测（对照实验）
    # ═══════════════════════════════════════════════════════════

    hr("第 2 层：模块收益评测 — 对照实验体系")

    print("""
    三个子层:
      2a: 上下文治理收益 — 12 组配置, 有/无 context_reduction 对比
      2b: 记忆收益       — 12 个记忆依赖任务, memory_on/off/irrelevant
      2c: 恢复正确性     — 10 个恢复场景, resume_enabled/disabled 对比
    """)

    # ─── 2a: 上下文治理 ───
    sub("2a: 上下文治理 — feature ablation 对照")

    from page.evaluation.metrics import measure_feature_ablation_metrics

    with tempfile.TemporaryDirectory(prefix="page-context-") as tmp:
        root = Path(tmp)
        (root / "README.md").write_text("demo\n", encoding="utf-8")
        ws = WorkspaceContext.build(root)
        store = SessionStore(root / ".page" / "sessions")
        agent = Page(model_client=FakeModelClient([]), workspace=ws,
                     session_store=store, approval_policy="auto")

        # 注入大量 history 和 notes
        for i in range(8):
            agent.record({"role": "user" if i % 2 == 0 else "assistant",
                          "content": f"history-{i}-" + "X" * 200,
                          "created_at": f"2026-07-01T10:{i:02d}:00+00:00"})
        for i in range(4):
            agent.memory.append_note(f"note-{i}-" + "Y" * 150, tags=("recall",),
                                     created_at=f"2026-07-01T11:{i:02d}:00+00:00")

        results = measure_feature_ablation_metrics(agent, "debug the utils module")

        print("      对照实验: full vs no_context_reduction vs no_memory\n")
        for variant, metrics in results.items():
            print(f"      [{variant}]")
            print(f"        prompt_chars:         {metrics['prompt_chars']}")
            print(f"        memory_chars:         {metrics['memory_chars']}")
            print(f"        history_chars:        {metrics['history_chars']}")
            print(f"        relevant_selected:    {metrics['relevant_selected_count']}")
            print(f"        budget_reductions:    {metrics['budget_reduction_count']}")
            print(f"        request_preserved:    {metrics['current_request_preserved']}")

        # 计算压缩率
        full_chars = results["full"]["prompt_chars"]
        raw_chars = results["no_context_reduction"]["prompt_chars"]
        if raw_chars > full_chars:
            ratio = (raw_chars - full_chars) / raw_chars * 100
            print(f"\n      → 压缩效果: {raw_chars} → {full_chars} ({ratio:.1f}%)")
            ok("context_reduction 有效压缩了 prompt 长度")

    # ─── 2b: 记忆收益 ───
    sub("2b: 记忆收益 — memory dependency experiment 对照")

    from page.evaluation.metrics import run_memory_dependency_experiment

    print("      运行 memory dependency experiment (3 种 variant × 3 次)...")
    mem_result = run_memory_dependency_experiment(repetitions=3)

    print(f"\n      对照实验: memory_on vs memory_off vs memory_irrelevant\n")
    for variant, metrics in mem_result.items():
        print(f"      [{variant}]")
        print(f"        repeated_reads: {metrics['repeated_reads']}")
        print(f"        avg_tool_steps: {metrics['avg_tool_steps']:.2f}")
        print(f"        avg_attempts:   {metrics['avg_attempts']:.2f}")
        print(f"        correct_rate:   {metrics['correct_rate']:.1%}")

    if mem_result["memory_on"]["repeated_reads"] < mem_result["memory_off"]["repeated_reads"]:
        on = mem_result["memory_on"]["repeated_reads"]
        off = mem_result["memory_off"]["repeated_reads"]
        ok(f"memory_on 重复读文件 {on} 次 vs memory_off {off} 次 (减少了 {off - on} 次)")
    elif mem_result["memory_on"]["repeated_reads"] == 0:
        ok("memory_on 完全消除了重复读文件 (repeated_reads = 0)")

    # ─── 2c: 恢复正确性 ───
    sub("2c: 恢复正确性 — recovery ablation 对照")

    from page.evaluation.metrics import run_recovery_ablation_v2

    print("      运行 recovery ablation (10 个场景 × ...)...")
    try:
        recov_result = run_recovery_ablation_v2(repetitions=2)

        for variant in ["resume_enabled", "resume_disabled"]:
            summary = recov_result["variants"][variant]["summary"]
            print(f"\n      [{variant}]")
            print(f"        resume_success_rate:            {summary['resume_success_rate']:.1%}")
            print(f"        stale_reanchor_rate:             {summary['stale_reanchor_rate']:.1%}")
            print(f"        workspace_drift_detection_rate:  {summary['workspace_drift_detection_rate']:.1%}")
            print(f"        resume_false_accept_rate:        {summary['resume_false_accept_rate']:.1%}")

        enabled = recov_result["variants"]["resume_enabled"]["summary"]
        ok(f"漂移识别率: {enabled['workspace_drift_detection_rate']:.1%}")
        ok(f"误信旧状态率: {enabled['resume_false_accept_rate']:.1%}")
    except Exception as exc:
        info(f"recovery ablation 跳过 (可能需要完整 fixture 环境): {exc}")

    # ═══════════════════════════════════════════════════════════
    # PART E: 第 3 层 — 运行工件聚合
    # ═══════════════════════════════════════════════════════════

    hr("第 3 层：运行工件聚合 — 从 trace.jsonl + report.json 挖掘数据")

    with tempfile.TemporaryDirectory(prefix="page-aggregate-") as tmp:
        runs_root = Path(tmp) / ".page" / "runs"
        runs_root.mkdir(parents=True)

        # 手动造 3 个 run 的工件
        for run_id in ["run_001", "run_002", "run_003"]:
            run_dir = runs_root / run_id
            run_dir.mkdir(parents=True)

            # task_state.json
            (run_dir / "task_state.json").write_text(json.dumps({
                "run_id": run_id, "task_id": f"task_{run_id}",
                "user_request": "test", "status": "completed",
                "tool_steps": {"run_001": 3, "run_002": 5, "run_003": 2}[run_id],
                "attempts": {"run_001": 4, "run_002": 6, "run_003": 3}[run_id],
                "stop_reason": "final_answer_returned",
            }), encoding="utf-8")

            # trace.jsonl
            trace_lines = [
                {"event": "run_started", "created_at": "2026-07-01T10:00:00+00:00"},
                {"event": "prompt_built", "duration_ms": 5.2},
                {"event": "tool_executed", "name": "read_file",
                 "tool_status": "ok", "duration_ms": 12.0},
                {"event": "tool_executed", "name": "write_file",
                 "tool_status": "ok", "duration_ms": 8.5},
                {"event": "run_finished", "run_duration_ms": 250.0,
                 "created_at": "2026-07-01T10:00:03+00:00"},
            ]
            if run_id == "run_002":
                trace_lines.insert(3, {"event": "tool_executed", "name": "run_shell",
                                        "tool_status": "partial_success",
                                        "security_event_type": "",
                                        "duration_ms": 150.0})
            if run_id == "run_003":
                trace_lines.insert(2, {"event": "tool_executed", "name": "read_file",
                                        "tool_status": "rejected",
                                        "security_event_type": "path_escape",
                                        "duration_ms": 0.5})

            (run_dir / "trace.jsonl").write_text(
                "\n".join(json.dumps(e) for e in trace_lines) + "\n", encoding="utf-8")

            # report.json
            (run_dir / "report.json").write_text(json.dumps({
                "run_id": run_id, "status": "completed",
                "tool_steps": {"run_001": 3, "run_002": 5, "run_003": 2}[run_id],
                "attempts": {"run_001": 4, "run_002": 6, "run_003": 3}[run_id],
                "stop_reason": "final_answer_returned",
                "prompt_metadata": {"prompt_chars": 2500, "cached_tokens": 800,
                                     "input_tokens": 1200, "cache_hit": run_id != "run_001"},
            }), encoding="utf-8")

        # 使用 aggregate_run_artifacts 聚合
        from page.evaluation.metrics import aggregate_run_artifacts

        aggregated = aggregate_run_artifacts(runs_root)

        print(f"      聚合了 {aggregated['run_count']} 个 run 的数据:\n")
        print(f"      整体指标:")
        print(f"        avg_tool_steps:         {aggregated['avg_tool_steps']:.2f}")
        print(f"        avg_attempts:           {aggregated['avg_attempts']:.2f}")
        print(f"        avg_prompt_chars:       {aggregated['avg_prompt_chars']:.2f}")
        print(f"        avg_run_duration_ms:    {aggregated['avg_run_duration_ms']:.2f}")
        print(f"        avg_tool_duration_ms:   {aggregated['avg_tool_duration_ms']:.2f}")
        print(f"        cache_hit_rate:         {aggregated['cache_hit_rate']:.1%}")
        print(f"        prefix_reuse_rate:      {aggregated['prefix_reuse_rate']:.1%}")

        print(f"\n      工具名称分布 (tool_name_counts):")
        for name, count in sorted(aggregated["tool_name_counts"].items()):
            print(f"        {name}: {count} 次")

        print(f"\n      工具状态分布 (tool_status_counts):")
        for status, count in sorted(aggregated["tool_status_counts"].items()):
            print(f"        {status}: {count} 次")

        print(f"\n      安全事件分布 (security_event_counts):")
        for event, count in sorted(aggregated["security_event_counts"].items()):
            print(f"        {event}: {count} 次")

        print(f"\n      停止原因分布 (stop_reason_counts):")
        for reason, count in sorted(aggregated["stop_reason_counts"].items()):
            print(f"        {reason}: {count} 次")

        ok("运行工件聚合完成 — 所有指标可用于长期趋势分析")

    # ═══════════════════════════════════════════════════════════
    # PART F: 总结
    # ═══════════════════════════════════════════════════════════

    hr("总结：三层评测体系 完整架构")

    print("""
    ┌─────────────────────────────────────────────────────────────┐
    │              Page 评测与审计闭环 全景图                        │
    ├─────────────────────────────────────────────────────────────┤
    │                                                             │
    │  第 1 层：Harness Regression（框架回归）                      │
    │  ├ 12 个固定 benchmark 任务 (coding_tasks.json)               │
    │  ├ FakeModelClient 脚本化输出 (不依赖任何 LLM API)            │
    │  ├ validate_benchmark() — schema 校验 (7+8 必需字段)         │
    │  ├ BenchmarkEvaluator.run_task() — 5 步流程                 │
    │  │   ① 复制 fixture  →  ② 构建 Page agent                   │
    │  │   ③ agent.ask()   →  ④ 检查 expected_artifact           │
    │  │   ⑤ subprocess verifier 验证                             │
    │  ├ 判定 pass = within_budget + verifier_passed               │
    │  │              + artifact_exists + non_failure_stop          │
    │  └ summarize_rows() — pass_rate / budget_rate / verifier_rate│
    │                                                             │
    │  第 2 层：模块收益评测（对照实验）                              │
    │  ├ 2a: 上下文治理 — context stress matrix (12 组配置)        │
    │  │    measure_feature_ablation_metrics()                     │
    │  │    对照: full vs no_context_reduction vs no_memory        │
    │  │    指标: prompt_chars / compression_ratio                 │
    │  ├ 2b: 记忆收益 — memory dependency experiment (12 个任务)   │
    │  │    run_large_scale_memory_experiment()                    │
    │  │    对照: memory_on vs memory_off vs memory_irrelevant     │
    │  │    指标: repeated_reads / avg_tool_steps / correct_rate   │
    │  └ 2c: 恢复正确性 — recovery ablation (10 个场景)            │
    │       run_recovery_ablation_v2()                             │
    │       对照: resume_enabled vs resume_disabled                │
    │       指标: 漂移识别率 / 误信旧状态率 / false_accept_rate     │
    │                                                             │
    │  第 3 层：运行工件聚合                                        │
    │  ├ TaskState — 一次 run 的生命周期状态机                     │
    │  │   9 种 stop_reason / 4 种 status / 10 个字段 to_dict()    │
    │  ├ RunStore — 3 类运行工件落盘                               │
    │  │   task_state.json → 原子写 (临时文件 + replace)           │
    │  │   trace.jsonl     → 逐条追加 (流式事件序列)               │
    │  │   report.json     → 原子写 (运行最终摘要)                  │
    │  └ aggregate_run_artifacts() — 从 runs/ 目录聚合            │
    │      tool_name_counts / tool_status_counts                   │
    │      / security_event_counts / stop_reason_counts            │
    │      / cache_hit_rate / avg_duration / ...                   │
    │                                                             │
    └─────────────────────────────────────────────────────────────┘

    核心原则:
      ✦ 模型能力、系统能力和运行观测要分开评测
      ✦ 不能因为模型强就认为系统好，也不能因为模型弱否定系统设计价值
      ✦ FakeModelClient 确定性测试验证框架合约
      ✦ 对照实验分离模块变量，证明具体机制的收益
      ✦ 运行工件聚合做长期趋势，发现性能退化
    """)


if __name__ == "__main__":
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  评测与审计闭环 — 三层评测体系 可视化演示                        ║")
    print("║  Harness Regression + 模块收益评测 + 运行工件聚合              ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    demo()

    print()
    print("=" * 68)
    print("  演示完毕。关注:")
    print("  [A] 第 1 层：BenchmarkEvaluator 的 run_task 流程 + pass 判定")
    print("  [B] 第 1 层：3 个运行工件 (task_state / trace / report) 的结构")
    print("  [C] 第 2 层：feature ablation / memory experiment / recovery ablation")
    print("  [D] 第 3 层：aggregate_run_artifacts 的聚合指标")
    print("=" * 68)
    print()
