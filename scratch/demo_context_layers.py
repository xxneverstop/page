"""
直观观察 ContextManager 的三大核心机制：
  1. 五段式分层结构（prefix / memory / relevant_memory / history / request）
  2. 动态裁剪（超预算时按 reduction_order 逐层压缩）
  3. 智能压缩（read_file 去重、旧 tool 输出摘要化）

用法：
  cd D:\workspace\page
  python scratch\demo_context_layers.py
"""

import sys
import tempfile
import io
from pathlib import Path

# 修复 Windows GBK 终端编码 + 禁用输出缓冲
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', write_through=True)

# 确保能 import page
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from page import FakeModelClient, Page, SessionStore, WorkspaceContext
from page.context_manager import ContextManager, DEFAULT_SECTION_BUDGETS


def hr(title):
    """打印分隔标题"""
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def show_section(title, text, max_chars=400):
    """打印一个 section 的内容（截断显示）"""
    print(f"\n  ┌─ {title} ({len(text)} 字符)")
    display = text if len(text) <= max_chars else text[:max_chars] + f"\n  ... (截断，共 {len(text)} 字符)"
    for line in display.split("\n"):
        print(f"  │ {line}")
    print(f"  └─")


def show_metadata(metadata):
    """打印 build() 返回的元数据"""
    sections = metadata.get("sections", {})
    print(f"\n  📊 各段预算与渲染情况：")
    print(f"  {'Section':<25} {'预算':>8} {'原始':>8} {'渲染':>8} {'状态':>8}")
    print(f"  {'-'*57}")
    for name, info in sections.items():
        budget = info.get("budget_chars") or 0
        raw = info.get("raw_chars") or 0
        rendered = info.get("rendered_chars") or 0
        if budget and rendered > budget:
            over = "超预算"
        elif budget:
            over = "OK"
        else:
            over = "(无限)"
        print(f"  {name:<25} {budget:>8} {raw:>8} {rendered:>8} {over:>8}")

    reductions = metadata.get("budget_reductions", [])
    if reductions:
        print(f"\n  🔪 裁剪记录（按 reduction_order 依次压缩）：")
        for r in reductions:
            print(f"     - {r['section']}: {r['from_chars']} → {r['to_chars']} (裁掉 {r['from_chars'] - r['to_chars']} 字符)")

    # 历史压缩统计
    history = metadata.get("history", {})
    if history.get("collapsed_duplicate_reads"):
        print(f"\n  📦 智能压缩（read_file 去重）：{history['collapsed_duplicate_reads']} 处")
    if history.get("summarized_tool_count"):
        print(f"  📦 智能压缩（tool 输出摘要化）：{history['summarized_tool_count']} 处")
    if history.get("reused_file_summary_count"):
        print(f"  📦 复用的文件摘要：{history['reused_file_summary_count']} 处")

    # 相关记忆
    rel = metadata.get("relevant_memory", {})
    if rel:
        print(f"\n  🧠 相关记忆：选中 {rel.get('selected_count', 0)} 条，来自 {rel.get('selected_sources', [])}")
        sources = rel.get("selected_kinds", [])
        if "durable" in sources:
            print(f"     (包含持久记忆)")


# ═══════════════════════════════════════════════════════════════════
# 场景 1：五段式 prompt 分层结构
# ═══════════════════════════════════════════════════════════════════

def demo_1_layered_structure():
    hr("场景 1：五段式 Prompt 分层结构")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "README.md").write_text("# Demo Project\n", encoding="utf-8")
        (root / "src" / "main.py").mkdir(parents=True, exist_ok=True)

        workspace = WorkspaceContext.build(root)
        store = SessionStore(root / ".page" / "sessions")
        agent = Page(
            model_client=FakeModelClient([]),
            workspace=workspace,
            session_store=store,
        )

        # 添加一些 episodic notes
        agent.memory.append_note("部署密钥配置在 .env 的 DEPLOY_KEY 字段", tags=("deploy",), created_at="2026-06-27T10:00:00+00:00")
        agent.memory.append_note("上次构建失败是因为缺少 pandas 依赖", tags=("build",), created_at="2026-06-27T10:05:00+00:00")

        # 模拟对话历史
        agent.record({"role": "user", "content": "帮我检查一下项目的依赖", "created_at": "2026-06-27T09:00:00+00:00"})
        agent.record({"role": "assistant", "content": "我来看看 requirements.txt 和 setup.cfg。", "created_at": "2026-06-27T09:01:00+00:00"})
        agent.record({
            "role": "tool", "name": "read_file",
            "args": {"path": "requirements.txt"},
            "content": "# requirements.txt\nflask>=2.0\nnumpy>=1.21\n# 注意：pandas 需要 >=1.5",
            "created_at": "2026-06-27T09:02:00+00:00",
        })
        agent.record({"role": "assistant", "content": "项目依赖 flask 和 numpy，pandas 需要 >=1.5 但尚未安装。", "created_at": "2026-06-27T09:03:00+00:00"})

        cm = ContextManager(agent)
        prompt, metadata = cm.build("安装缺失的 pandas 依赖")

        print("\n  📐 五段式结构示意：")
        print("  ┌─────────────────────────────────────────────┐")
        print("  │ ① prefix     — System Prompt + 工具签名       │")
        print("  │ ② memory     — 任务摘要 + 文件列表 + 笔记     │")
        print("  │ ③ relevant   — 检索到的相关记忆（最多 3 条）   │")
        print("  │ ④ history    — 压缩后的对话历史               │")
        print("  │ ⑤ request    — 当前用户请求（永不裁剪）        │")
        print("  └─────────────────────────────────────────────┘")

        # 各段的起始标记（按 prompt 中的出现顺序）
        markers = [
            ("prefix",           "You are page"),
            ("memory",           "\nMemory:\n"),
            ("relevant_memory",  "\nRelevant memory:\n"),
            ("history",          "\nTranscript:\n"),
            ("current_request",  "\nCurrent user request:\n"),
        ]

        for i, (section_name, marker) in enumerate(markers):
            start = prompt.find(marker)
            if start < 0:
                continue
            # 找下一段的起始位置
            next_start = len(prompt)
            for _, next_marker in markers[i + 1:]:
                ns = prompt.find(next_marker)
                if ns > start:
                    next_start = ns
                    break
            section_text = prompt[start:next_start]
            show_section(section_name, section_text, 300)

        show_metadata(metadata)
        print(f"\n  📏 总 prompt 长度：{len(prompt)} 字符（预算 {cm.total_budget}）")


# ═══════════════════════════════════════════════════════════════════
# 场景 2：超预算动态裁剪
# ═══════════════════════════════════════════════════════════════════

def demo_2_dynamic_trimming():
    hr("场景 2：超预算时的动态裁剪（按 reduction_order 逐层压缩）")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "README.md").write_text("demo\n", encoding="utf-8")

        workspace = WorkspaceContext.build(root)
        store = SessionStore(root / ".page" / "sessions")
        agent = Page(
            model_client=FakeModelClient([]),
            workspace=workspace,
            session_store=store,
        )

        # 构造大量内容让 prompt 严重超预算
        agent.prefix = "PREFIX " + ("◆" * 1200)  # 很大的 prefix
        agent.memory.render_memory_text = lambda: "MEMORY: " + ("●" * 800)  # 很大的 memory

        # 5 条 episodic notes（每条都很大）
        for i in range(5):
            agent.memory.append_note(
                f"笔记 #{i}: " + ("■" * 300),
                tags=("recall",),
                created_at=f"2026-06-27T10:0{i}:00+00:00",
            )

        # 构造历史：1 条旧消息 + 6 条新消息
        agent.record({
            "role": "user",
            "content": "OLD-MESSAGE " + ("◈" * 500),
            "created_at": "2026-06-27T08:00:00+00:00",
        })
        for minute in range(1, 7):
            role = "user" if minute % 2 == 1 else "assistant"
            tag = "RECENT" if minute >= 5 else "mid"
            agent.record({
                "role": role,
                "content": f"{tag}-{minute} " + ("◎" * 300),
                "created_at": f"2026-06-27T10:0{minute}:00+00:00",
            })

        # 使用极小的 total_budget 触发裁剪
        cm = ContextManager(
            agent,
            total_budget=1200,
            section_budgets={
                "prefix": 200,
                "memory": 200,
                "relevant_memory": 200,
                "history": 400,
            },
        )
        prompt, metadata = cm.build("请在保持这条请求完整的前提下压缩上下文")

        print("\n  ⚠️ 预算紧张！total_budget=1200，各段初始远超预算")
        print("  裁剪优先级: relevant_memory → history → memory → prefix")
        print("  request 永不裁剪\n")

        show_metadata(metadata)

        # 验证关键契约
        print(f"\n  🔒 契约检查：")
        print(f"     ✓ request 完整保留" if "请在保持这条请求完整的前提下压缩上下文" in prompt else "     ✗ request 丢失！")
        print(f"     ✓ RECENT-5 保留" if "RECENT-5" in prompt else "     ✗ 新消息被误删！")
        print(f"     {'✓' if 'OLD-MESSAGE' not in prompt else '✗'} OLD-MESSAGE {'已裁掉' if 'OLD-MESSAGE' not in prompt else '仍在'}")

        print(f"\n  📏 总 prompt 长度：{len(prompt)} 字符（预算 {cm.total_budget}）")
        print(f"  {'⚠️ 超预算！' if len(prompt) > cm.total_budget else '✓ 在预算内'}")


# ═══════════════════════════════════════════════════════════════════
# 场景 3：智能压缩（read_file 去重 + tool 摘要化）
# ═══════════════════════════════════════════════════════════════════

def demo_3_smart_compression():
    hr("场景 3：智能压缩 — read_file 去重 & tool 输出摘要化")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "README.md").write_text("demo\n", encoding="utf-8")
        (root / "config.py").write_text("DEBUG = True\nSECRET_KEY = 'abc'\n", encoding="utf-8")

        workspace = WorkspaceContext.build(root)
        store = SessionStore(root / ".page" / "sessions")
        agent = Page(
            model_client=FakeModelClient([]),
            workspace=workspace,
            session_store=store,
        )

        # 在 memory 中预设文件摘要（模拟之前读过的文件）
        agent.memory.set_file_summary("config.py", "DEBUG=True | SECRET_KEY=***")
        agent.memory.set_file_summary("README.md", "demo project readme")
        agent.memory.remember_file("config.py")
        agent.memory.remember_file("README.md")

        # ═══ 构造历史：包含重复 read_file 和旧 tool 输出 ═══

        # T=09:00 — 第一次读 config.py（完整的 tool 输出）
        agent.record({
            "role": "tool", "name": "read_file",
            "args": {"path": "config.py", "start": 1, "end": 2},
            "content": "# config.py\nDEBUG = True\nSECRET_KEY = 'abc'\n",
            "created_at": "2026-06-27T09:00:00+00:00",
        })
        agent.record({"role": "assistant", "content": "config.py 包含 DEBUG 和 SECRET_KEY。", "created_at": "2026-06-27T09:01:00+00:00"})

        # T=09:02 — 第二次读 config.py（又是一次完整的 read_file 输出）
        agent.record({
            "role": "tool", "name": "read_file",
            "args": {"path": "config.py", "start": 1, "end": 2},
            "content": "# config.py\nDEBUG = True\nSECRET_KEY = 'abc'\n",
            "created_at": "2026-06-27T09:02:00+00:00",
        })
        agent.record({"role": "assistant", "content": "再次确认 config.py 的内容。", "created_at": "2026-06-27T09:03:00+00:00"})

        # T=09:04 — 跑了一次 shell（长输出）
        agent.record({
            "role": "tool", "name": "run_shell",
            "args": {"command": "pytest -q"},
            "content": "test_a.py::test_one PASSED\ntest_b.py::test_two FAILED\ntest_c.py::test_three FAILED\ntest_d.py::test_four PASSED\n",
            "created_at": "2026-06-27T09:04:00+00:00",
        })
        agent.record({"role": "assistant", "content": "测试有两个失败，需要修复。", "created_at": "2026-06-27T09:05:00+00:00"})

        # T=10:01~10:06 — 最近的对话（让前面的变成"旧"的）
        for minute in range(1, 7):
            role = "user" if minute % 2 == 1 else "assistant"
            agent.record({
                "role": role,
                "content": f"recent conversation #{minute}",
                "created_at": f"2026-06-27T10:0{minute}:00+00:00",
            })

        cm = ContextManager(agent)
        prompt, metadata = cm.build("检查项目的测试状态和配置")

        print("\n  🎯 压缩前（history 中的原内容）：")
        print("     [tool:read_file config.py]  → DEBUG = True\\nSECRET_KEY = 'abc'  (第1次)")
        print("     [tool:read_file config.py]  → DEBUG = True\\nSECRET_KEY = 'abc'  (第2次！重复！)")
        print("     [tool:run_shell pytest -q]  → PASSED\\nFAILED\\nFAILED\\nPASSED  (4行)")

        # 找 transcript 段
        transcript_pos = prompt.find("Transcript:")
        request_pos = prompt.find("Current user request:")
        if transcript_pos >= 0 and request_pos >= 0:
            transcript = prompt[transcript_pos:request_pos]
            show_section("history (压缩后)", transcript, 600)

            # 检查关键变化
            print(f"\n  🔍 压缩效果对比：")
            print(f"     read_file 原始输出出现次数: {transcript.count('[tool:read_file]')} (期望: 0 — 已被去重)")
            print(f"     config.py 摘要出现: {'✓' if 'config.py' in transcript and 'DEBUG' in transcript else '✗'}")
            shell_raw_present = 'PASSED' in transcript and 'FAILED' in transcript and 'PASSED\nFAILED' not in transcript
            print(f"     run_shell 原始多行输出出现: {'✗' if shell_raw_present else '✓ 已被摘要化'}")
            print(f"     pytest 压缩行出现: {'✓' if 'pytest -q ->' in transcript else '✗'}")

        show_metadata(metadata)


# ═══════════════════════════════════════════════════════════════════
# 场景 4：对比 — 正常预算 vs 极限预算
# ═══════════════════════════════════════════════════════════════════

def demo_4_budget_comparison():
    hr("场景 4：同一内容在不同预算下的表现对比")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "README.md").write_text("demo\n", encoding="utf-8")

        workspace = WorkspaceContext.build(root)
        store = SessionStore(root / ".page" / "sessions")

        def make_agent():
            agent = Page(
                model_client=FakeModelClient([]),
                workspace=workspace,
                session_store=store,
                max_steps=4,
            )
            agent.prefix = "PREFIX " + ("P" * 800)
            agent.memory.render_memory_text = lambda: "MEMORY: " + ("M" * 400)
            for i in range(4):
                agent.memory.append_note(f"笔记{i}: " + ("N" * 250), tags=("test",), created_at=f"2026-06-27T10:0{i}:00+00:00")
            for t in ("09:00", "09:02"):
                agent.record({
                    "role": "tool", "name": "read_file",
                    "args": {"path": "src/main.py"},
                    "content": ("def main():\n    pass\n" * 10),
                    "created_at": f"2026-06-27T{t}:00+00:00",
                })
            for minute in range(1, 8):
                role = "user" if minute % 2 == 1 else "assistant"
                tag = "NEW" if minute >= 6 else "OLD"
                agent.record({
                    "role": role,
                    "content": f"{tag}-{minute} " + ("R" * 200),
                    "created_at": f"2026-06-27T10:0{minute}:00+00:00",
                })
            return agent

        # ── 配置 A：正常预算 ──
        print("\n  ╔══════════════════════════════════════════════╗")
        print("  ║  配置 A：正常预算 (total=8000)               ║")
        print("  ╚══════════════════════════════════════════════╝")
        agent_a = make_agent()
        cm_a = ContextManager(
            agent_a,
            total_budget=8000,
            section_budgets={
                "prefix": 2400, "memory": 1200,
                "relevant_memory": 900, "history": 3500,
            },
        )
        prompt_a, meta_a = cm_a.build("keep this request")
        show_metadata(meta_a)
        print(f"\n  📏 总长度：{len(prompt_a)} / {cm_a.total_budget} 字符")

        # ── 配置 B：极限预算 ──
        print("\n  ╔══════════════════════════════════════════════╗")
        print("  ║  配置 B：极限预算 (total=1000)               ║")
        print("  ╚══════════════════════════════════════════════╝")
        agent_b = make_agent()
        cm_b = ContextManager(
            agent_b,
            total_budget=1000,
            section_budgets={
                "prefix": 150, "memory": 150,
                "relevant_memory": 150, "history": 300,
            },
        )
        prompt_b, meta_b = cm_b.build("keep this request")
        show_metadata(meta_b)
        print(f"\n  📏 总长度：{len(prompt_b)} / {cm_b.total_budget} 字符")

        # 对比
        print(f"\n  ⚖️ 对比：")
        print(f"     正常预算 prompt: {len(prompt_a)} 字符")
        print(f"     极限预算 prompt: {len(prompt_b)} 字符")
        print(f"     压缩率: {(1 - len(prompt_b)/len(prompt_a)) * 100:.1f}%")
        print(f"     'keep this request' 保留: {'✓' if 'keep this request' in prompt_b else '✗'}")
        print(f"     NEW-6 (新消息) 保留: {'✓' if 'NEW-6' in prompt_b else '✗'}")
        print(f"     OLD-1 (旧消息) 保留: {'✗ 已丢弃' if 'OLD-1' not in prompt_b else '✓'}")

        # 裁剪顺序验证
        reductions = meta_b.get("budget_reductions", [])
        if reductions:
            order = " → ".join(r["section"] for r in reductions)
            print(f"     裁剪顺序: {order}")


# ═══════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  ContextManager 三大核心机制 可视化演示                       ║")
    print("║  1. 五段式分层结构   2. 动态裁剪   3. 智能压缩   4. 预算对比  ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    demo_1_layered_structure()
    demo_2_dynamic_trimming()
    demo_3_smart_compression()
    demo_4_budget_comparison()

    print()
    print("=" * 70)
    print("  演示完毕。关注以上输出中的：")
    print("  ① 五段式结构的确切顺序和内容")
    print("  ② 超预算时各段的裁剪量和裁剪顺序")
    print("  ③ read_file 去重和 tool 输出摘要化前后的对比")
    print("  ④ 同内容在不同预算下的表现差异")
    print("=" * 70)
