"""
直观观察 Page 的 Checkpoint/Resume 机制

核心概念：
  1. Checkpoint 创建 — 每次工具执行后自动保存状态快照
  2. 运行时身份 — 13 个维度校验"执行环境是否变了"
  3. 新鲜度检测 — 文件 sha256 对比，发现外部修改
  4. 三种恢复状态 — full-valid / partial-stale / workspace-mismatch
  5. Checkpoint 文本注入 — resume 时模型看到的上下文

用法：
  cd D:\workspace\page
  python scratch\demo_checkpoint_resume.py
"""

from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', write_through=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from page import FakeModelClient, Page, SessionStore, WorkspaceContext
from page.checkpoint import (
    RUNTIME_IDENTITY_KEYS,
    CHECKPOINT_NONE_STATUS,
    CHECKPOINT_FULL_VALID_STATUS,
    CHECKPOINT_PARTIAL_STALE_STATUS,
    CHECKPOINT_WORKSPACE_MISMATCH_STATUS,
    CHECKPOINT_SCHEMA_MISMATCH_STATUS,
    evaluate_resume_state,
    create_checkpoint,
    current_checkpoint,
    render_checkpoint_text,
    current_runtime_identity,
)


def hr(title):
    print()
    print("=" * 68)
    print(f"  {title}")
    print("=" * 68)


def sub(title):
    print(f"\n  ── {title} ──")


def show_checkpoint(label, cp):
    """展示一个 checkpoint 的完整内容"""
    print(f"\n  [{label}] checkpoint_id={cp.get('checkpoint_id', '?')[:20]}...")
    print(f"    parent:           {cp.get('parent_checkpoint_id', '')[:20] or '(root)'}...")
    print(f"    schema_version:   {cp.get('schema_version')}")
    print(f"    current_goal:     {cp.get('current_goal', '-')[:80]}")
    print(f"    current_blocker:  {cp.get('current_blocker', '-') or '(none)'}")
    print(f"    next_step:        {cp.get('next_step', '-')[:80]}")
    print(f"    completed:        {cp.get('completed', [])}")
    key_files = [item.get('path', '?') for item in cp.get('key_files', [])]
    print(f"    key_files:        {key_files}")
    identity = cp.get('runtime_identity', {})
    print(f"    runtime_identity: model={identity.get('model')}, "
          f"cwd={Path(identity.get('cwd', '')).name}, "
          f"approval={identity.get('approval_policy')}, "
          f"max_steps={identity.get('max_steps')}")


def show_resume_state(label, state):
    """展示恢复状态评估结果"""
    status = state.get("status", "?")
    status_icon = {
        CHECKPOINT_NONE_STATUS: "(无 checkpoint)",
        CHECKPOINT_FULL_VALID_STATUS: "OK 全部一致，可无缝恢复",
        CHECKPOINT_PARTIAL_STALE_STATUS: "STALE 文件已被外部修改",
        CHECKPOINT_WORKSPACE_MISMATCH_STATUS: "MISMATCH 执行环境已改变",
        CHECKPOINT_SCHEMA_MISMATCH_STATUS: "SCHEMA 版本不兼容",
    }.get(status, status)
    print(f"\n  [{label}] 恢复状态: {status} {status_icon}")
    if state.get("stale_paths"):
        print(f"    过期文件: {state['stale_paths']}")
    if state.get("runtime_identity_mismatch_fields"):
        print(f"    不匹配字段: {state['runtime_identity_mismatch_fields']}")
    if state.get("stale_summary_invalidations"):
        print(f"    摘要失效数: {state['stale_summary_invalidations']}")


def show_checkpoint_text(label, text):
    """展示注入 prompt 的 checkpoint 文本"""
    if not text:
        print(f"\n  [{label}] (无 checkpoint 文本)")
        return
    print(f"\n  [{label}] 注入 prompt 的 checkpoint 段:")
    for line in text.split("\n"):
        print(f"    │ {line}")


# ═══════════════════════════════════════════════════════════════
# 场景：完整演示 checkpoint 创建 → 恢复 → 漂移检测
# ═══════════════════════════════════════════════════════════════

def demo():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "README.md").write_text("# Demo\n", encoding="utf-8")
        (root / "src").mkdir(exist_ok=True)
        (root / "src" / "main.py").write_text("def main():\n    return 42\n", encoding="utf-8")
        (root / "src" / "utils.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

        workspace = WorkspaceContext.build(root)
        store = SessionStore(root / ".page" / "sessions")

        # ═══════════════════════════════════════════════════
        # 第 1 步：理解 RUNTIME_IDENTITY_KEYS
        # ═══════════════════════════════════════════════════
        hr("第 1 步：13 维运行时身份")

        fake_outputs = [
            '<tool>{"name":"read_file","args":{"path":"src/main.py","start":1,"end":2}}</tool>',
            "<final>main.py 定义了返回 42 的 main 函数</final>",
        ]
        agent = Page(
            model_client=FakeModelClient(fake_outputs),
            workspace=workspace,
            session_store=store,
            max_steps=4,
            approval_policy="auto",
        )

        identity = current_runtime_identity(agent)
        print(f"\n  每次 checkpoint 都记录这 {len(RUNTIME_IDENTITY_KEYS)} 个维度，")
        print(f"  用于恢复时判断「执行环境是否变了」:\n")
        for key in RUNTIME_IDENTITY_KEYS:
            val = identity.get(key, "?")
            display = str(val)[:70] if len(str(val)) <= 70 else str(val)[:67] + "..."
            print(f"    {key:<30} = {display}")

        # ═══════════════════════════════════════════════════
        # 第 2 步：Agent 执行一轮，观察 checkpoint 创建
        # ═══════════════════════════════════════════════════
        hr("第 2 步：Agent 执行 — 每次工具执行后自动创建 checkpoint")

        agent.memory.remember_file("src/main.py")
        agent.memory.set_file_summary("src/main.py", "def main() -> 42")

        answer = agent.ask("检查 src/main.py 的功能")
        print(f"\n  ask() 返回: {answer}")

        # 保存 session_id 用于后续 "恢复"
        session_id = agent.session["id"]
        print(f"  session_id: {session_id[:16]}...")

        # 检查 session 中的 checkpoints
        checkpoints = agent.session.get("checkpoints", {})
        all_items = checkpoints.get("items", {})
        print(f"\n  执行了 1 次 ask()，产生了 {len(all_items)} 个 checkpoint:")
        for cid, cp in all_items.items():
            trigger = cp.get("summary", "")[:60]
            print(f"    - {cid[:20]}... trigger={trigger}")

        current_cp = current_checkpoint(agent)
        show_checkpoint("最新 checkpoint", current_cp)

        # 展示 checkpoint 链接关系
        if current_cp:
            parent_id = current_cp.get("parent_checkpoint_id", "")
            if parent_id:
                print(f"\n    checkpoint 链: parent → child")
                print(f"      {parent_id[:20]}...")
                print(f"        └→ {current_cp['checkpoint_id'][:20]}...")

        # ═══════════════════════════════════════════════════
        # 第 3 步：演示 FULL-VALID 恢复
        # ═══════════════════════════════════════════════════
        hr("第 3 步：FULL-VALID — 执行环境完全一致，可无缝恢复")

        # 使用 Page.from_session() 加载同一个 session
        agent2 = Page.from_session(
            model_client=FakeModelClient(["<final>继续上次的任务</final>"]),
            workspace=WorkspaceContext.build(root),
            session_store=store,
            session_id=session_id,
            max_steps=4,
            approval_policy="auto",
        )
        # agent2 从 session.json 加载了 agent1 的 checkpoints

        resume = evaluate_resume_state(agent2)
        show_resume_state("恢复评估结果 (应与 agent1 一致)", resume)

        # 展示 checkpoint 文本注入
        cp_text = render_checkpoint_text(agent2)
        show_checkpoint_text("注入 prompt", cp_text)

        # ═══════════════════════════════════════════════════
        # 第 4 步：演示 PARTIAL-STALE — 文件被外部修改
        # ═══════════════════════════════════════════════════
        hr("第 4 步：PARTIAL-STALE — 文件被外部修改，key_files 新鲜度不匹配")

        # 外部修改 key_files 中的一个文件
        (root / "src" / "main.py").write_text(
            "def main():\n    return 999  # SOMEONE CHANGED THIS!\n",
            encoding="utf-8",
        )
        print(f"\n  外部修改了 src/main.py: return 42 → return 999")

        agent3 = Page.from_session(
            model_client=FakeModelClient(["<final>检测到变化，重新读取</final>"]),
            workspace=WorkspaceContext.build(root),
            session_store=store,
            session_id=session_id,
            max_steps=4,
            approval_policy="auto",
        )

        resume3 = evaluate_resume_state(agent3)
        show_resume_state("恢复评估结果 (文件被修改)", resume3)

        cp_text3 = render_checkpoint_text(agent3)
        show_checkpoint_text("注入 prompt (告知模型哪些文件过期)", cp_text3)

        # ═══════════════════════════════════════════════════
        # 第 5 步：演示 WORKSPACE-MISMATCH — 执行环境变了
        # ═══════════════════════════════════════════════════
        hr("第 5 步：WORKSPACE-MISMATCH — 执行环境改变（如模型变了）")

        # 制造模型名不同的 client (给 FakeModelClient 设 model 属性)
        mismatch_client = FakeModelClient(["<final>环境已变，重新开始</final>"])
        mismatch_client.model = "claude-opus-4-8"  # 覆盖 model 属性

        agent4 = Page.from_session(
            model_client=mismatch_client,
            workspace=WorkspaceContext.build(root),
            session_store=store,
            session_id=session_id,
            max_steps=8,                    # 不同的步数限制！
            approval_policy="never",        # 不同的审批策略！
        )

        resume4 = evaluate_resume_state(agent4)
        show_resume_state("恢复评估结果 (环境不一致)", resume4)

        identity4 = current_runtime_identity(agent4)
        old_identity = current_cp.get("runtime_identity", {}) if current_cp else {}
        print(f"\n  不匹配对比:")
        for key in resume4.get("runtime_identity_mismatch_fields", []):
            old = str(old_identity.get(key, "?"))[:50]
            new = str(identity4.get(key, "?"))[:50]
            print(f"    {key}: checkpoint 中={old}")
            print(f"    {' ' * len(key)}  当前值={new}")

        # ═══════════════════════════════════════════════════
        # 第 6 步：演示 checkpoint 链
        # ═══════════════════════════════════════════════════
        hr("第 6 步：Checkpoint 链 (parent → child → grandchild)")

        # 两步 fake 输出制造 2 个 tool 步骤，观察更多 checkpoint 链
        agent5 = Page.from_session(
            model_client=FakeModelClient([
                '<tool>{"name":"read_file","args":{"path":"src/utils.py","start":1,"end":2}}</tool>',
                '<tool>{"name":"list_files","args":{"path":"src"}}</tool>',
                "<final>检查完毕</final>",
            ]),
            workspace=WorkspaceContext.build(root),
            session_store=store,
            session_id=session_id,
            max_steps=4,
        )
        agent5.memory.remember_file("src/utils.py")
        agent5.memory.set_file_summary("src/utils.py", "def add(a, b): return a+b")
        agent5.ask("检查 utils.py")

        cp_chain = agent5.session.get("checkpoints", {}).get("items", {})
        print(f"\n  共 {len(cp_chain)} 个 checkpoint (前 2 个来自 agent1, 中间 1 个来自 agent3, 后 3 个来自 agent5):")

        # 按时间排序展示链条
        sorted_cps = sorted(cp_chain.items(), key=lambda x: x[1].get("created_at", ""))
        for i, (cid, cp) in enumerate(sorted_cps):
            parent = cp.get("parent_checkpoint_id", "")[:16]
            n_files = len(cp.get("key_files", []))
            goal = cp.get("current_goal", "")[:50]
            trigger = cp.get("summary", "")[:50]
            print(f"    [{i}] {cid[:16]}... ← parent={parent or 'root':>16}")
            print(f"        goal={goal}")
            print(f"        trigger={trigger}")
            print(f"        key_files={n_files}")

        # ═══════════════════════════════════════════════════
        # 第 7 步：演示 NO CHECKPOINT 情况
        # ═══════════════════════════════════════════════════
        hr("第 7 步：NO CHECKPOINT — 新仓库，没有任何历史")

        with tempfile.TemporaryDirectory() as fresh_tmp:
            fresh_root = Path(fresh_tmp)
            (fresh_root / "README.md").write_text("# New Project\n", encoding="utf-8")

            fresh_agent = Page(
                model_client=FakeModelClient(["<final>全新开始</final>"]),
                workspace=WorkspaceContext.build(fresh_root),
                session_store=SessionStore(fresh_root / ".page" / "sessions"),
            )

            resume_none = evaluate_resume_state(fresh_agent)
            show_resume_state("全新仓库的恢复评估", resume_none)

            cp = current_checkpoint(fresh_agent)
            print(f"    当前 checkpoint: {cp}")

        print(f"\n  ┌─────────────────────────────────────────────────────────┐")
        print(f"  │  三种恢复状态对比:                                       │")
        print(f"  │                                                        │")
        print(f"  │  no-checkpoint     → 新仓库, 没有任何历史                 │")
        print(f"  │  full-valid        → 13 维身份一致 + key_files hash 一致  │")
        print(f"  │  partial-stale     → 身份一致 但 某些 key_files 被修改    │")
        print(f"  │  workspace-mismatch→ 身份不一致 (模型/配置/工作区变了)     │")
        print(f"  │                                                        │")
        print(f"  │  关键: partial-stale 时模型被告知哪些文件过期,              │")
        print(f"  │  可以重新 read_file 确认;                                  │")
        print(f"  │  workspace-mismatch 时模型被告知环境已变,                   │")
        print(f"  │  不应信任旧的 checkpoint 目标                             │")
        print(f"  └─────────────────────────────────────────────────────────┘")


if __name__ == "__main__":
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  Checkpoint / Resume 机制可视化演示                          ║")
    print("║  创建 → 13维身份 → full-valid → partial-stale → mismatch     ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    demo()

    print()
    print("=" * 68)
    print("  演示完毕。关注以上输出中的：")
    print("  ① RUNTIME_IDENTITY_KEYS 的 13 个维度")
    print("  ② 每次 tool_executed 后自动创建 checkpoint")
    print("  ③ checkpoint 之间的 parent→child 链")
    print("  ④ full-valid / partial-stale / workspace-mismatch 的区别")
    print("  ⑤ checkpoint 文本如何注入 prompt (模型被告知什么)")
    print("=" * 68)
