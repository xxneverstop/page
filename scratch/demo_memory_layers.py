"""
直观观察 Page 的三层记忆系统（LayeredMemory）

  第 1 层：短期工作集 (Working Memory)
    - task_summary: 当前任务摘要
    - recent_files: 最近读过的文件（最多 8 个，自动淘汰最旧的）
    - file_summaries: 文件内容摘要（最多展示 6 个）

  第 2 层：情节笔记 (Episodic Notes)
    - 关键发现、错误记录、决策理由（最多 12 条）
    - 每条带 tags，用于关键词检索
    - 按时间排序，自动淘汰最旧的

  第 3 层：持久记忆 (Durable Memory)
    - 存储在 .page/memory/ 文件系统中
    - 跨会话持久化
    - 4 个预定义 topic: project-conventions, key-decisions,
      dependency-facts, user-preferences

用法：
  cd D:\workspace\page
  python scratch\demo_memory_layers.py
"""

from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

# 修复 Windows GBK 终端编码 + 禁用输出缓冲
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', write_through=True)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from page.features.memory import (
    LayeredMemory,
    DurableMemoryStore,
    WORKING_FILE_LIMIT,
    EPISODIC_NOTE_LIMIT,
    FILE_SUMMARY_LIMIT,
    DURABLE_TOPIC_DEFAULTS,
)


def hr(title):
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def sub(title):
    print(f"\n  ── {title} ──")


def show_state(label, memory):
    """打印当前记忆状态的摘要"""
    s = memory.to_dict()
    print(f"\n  [{label}]")
    print(f"    任务摘要: {s['working']['task_summary'] or '(空)'}")
    print(f"    最近文件 ({len(s['working']['recent_files'])}/{WORKING_FILE_LIMIT}): "
          f"{', '.join(s['working']['recent_files']) or '(空)'}")
    # 文件摘要
    summaries = s.get("file_summaries", {})
    if summaries:
        print(f"    文件摘要 ({len(summaries)} 个):")
        for fpath, info in summaries.items():
            fresh = info.get("freshness")
            fresh_str = f" [新鲜度: {fresh[:8]}...]" if fresh else ""
            print(f"      {fpath}: {info['summary'][:80]}{fresh_str}")
    else:
        print(f"    文件摘要: (空)")
    # 情节笔记
    notes = s.get("episodic_notes", [])
    if notes:
        print(f"    情节笔记 ({len(notes)}/{EPISODIC_NOTE_LIMIT}):")
        for note in notes:
            tags_str = f" [tags: {', '.join(note['tags'])}]" if note['tags'] else ""
            kind = note.get('kind', 'episodic')
            print(f"      #{note['note_index']} ({kind}){tags_str}: {note['text'][:100]}")
    else:
        print(f"    情节笔记: (空)")
    print(f"    持久记忆 topics: {s.get('durable_topics', []) or '(空)'}")


def show_memory_text(label, memory):
    """打印 render_memory_text 的输出——这就是注入 prompt memory 段的内容"""
    print(f"\n  [{label}] 注入 prompt 的 memory 段内容：")
    text = memory.render_memory_text()
    for line in text.split("\n"):
        print(f"    │ {line}")


def show_retrieval(label, memory, query):
    """展示检索结果"""
    candidates = memory.retrieval_candidates(query)
    print(f"\n  [{label}] 检索: \"{query}\" → 命中 {len(candidates)} 条")
    for c in candidates:
        kind = c.get('kind', 'episodic')
        tags = c.get('tags', [])
        source = c.get('source', '')
        print(f"    - ({kind}{', source=' + source if source else ''})"
              f"{' [tags: ' + ', '.join(tags) + ']' if tags else ''}"
              f": {c['text'][:100]}")


# ═══════════════════════════════════════════════════════════════════
# 场景：模拟一次完整的代码调试过程
# ═══════════════════════════════════════════════════════════════════

def demo():
    hr("Page 三层记忆系统 (LayeredMemory) 可视化演示")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # 创建一些工作文件
        (root / "README.md").write_text("# My Project\n\nA demo project.\n", encoding="utf-8")
        (root / "config.py").write_text(
            "DEBUG = True\nSECRET_KEY = 'abc123xyz'\nDATABASE_URL = 'postgresql://localhost/db'\n",
            encoding="utf-8",
        )
        (root / "src").mkdir(exist_ok=True)
        (root / "src" / "main.py").write_text(
            "import config\n\ndef main():\n    print('Hello')\n    return config.DEBUG\n",
            encoding="utf-8",
        )
        (root / "src" / "utils.py").write_text(
            "def add(a, b):\n    return a - b  # BUG: should be a + b\n",
            encoding="utf-8",
        )
        (root / "tests").mkdir(exist_ok=True)
        (root / "tests" / "test_utils.py").write_text(
            "from src.utils import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
            encoding="utf-8",
        )

        memory = LayeredMemory(workspace_root=str(root))

        # ═══════════════════════════════════════════════════════
        # 第 0 步：初始状态（全是空的）
        # ═══════════════════════════════════════════════════════
        hr("初始状态：三层全空")
        show_state("三层全空的初始状态", memory)
        show_memory_text("初始 — 注入 prompt 的内容", memory)

        print("""
  ┌─────────────────────────────────────────────────────────┐
  │  第 1 层：Working Memory — 空的                              │
  │  第 2 层：Episodic Notes — 空的                              │
  │  第 3 层：Durable Memory  — 磁盘上不存在 .page/memory/       │
  └─────────────────────────────────────────────────────────┘""")

        # ═══════════════════════════════════════════════════════
        # 第 1 步：Agent 接到任务，开始探索
        # ═══════════════════════════════════════════════════════
        hr("第 1 步：Agent 读取 config.py 和 main.py")

        # 第 1 层：设置任务摘要
        memory.set_task_summary("调试 utils.add 函数的减法 bug，修复为加法")

        # 第 1 层：记录读了什么文件 + 文件摘要
        memory.remember_file("config.py")
        memory.remember_file("src/main.py")
        memory.set_file_summary("config.py", "DEBUG=True | SECRET_KEY=*** | DATABASE_URL=postgresql://...")
        memory.set_file_summary("src/main.py", "import config | def main() -> config.DEBUG")

        # 第 2 层：记录关键发现
        memory.append_note(
            "config.py 中的 SECRET_KEY 是敏感信息，注意脱敏",
            tags=("security", "config"),
            created_at="2026-06-27T10:01:00+00:00",
        )
        memory.append_note(
            "main.py 依赖 config.DEBUG，修改 config 会影响 main",
            tags=("dependency",),
            created_at="2026-06-27T10:02:00+00:00",
        )

        show_state("读取 2 个文件后", memory)
        show_memory_text("第 1 步后 — 注入 prompt 的内容", memory)

        print("""
  ┌─────────────────────────────────────────────────────────┐
  │  第 1 层：Working Memory — 填充了                         │
  │    - task_summary: "调试 utils.add 函数的减法 bug..."     │
  │    - recent_files: [config.py, src/main.py]              │
  │    - file_summaries: config.py 和 main.py 的摘要          │
  │                                                          │
  │  第 2 层：Episodic Notes — 新增 2 条                      │
  │    - SECRET_KEY 敏感注意脱敏  [tags: security, config]    │
  │    - main.py 依赖 config.DEBUG  [tags: dependency]        │
  │                                                          │
  │  第 3 层：Durable Memory — 仍未写入                        │
  └─────────────────────────────────────────────────────────┘""")

        # ═══════════════════════════════════════════════════════
        # 第 2 步：Agent 发现 bug
        # ═══════════════════════════════════════════════════════
        hr("第 2 步：Agent 读取 utils.py 和 test_utils.py，发现 bug")

        memory.remember_file("src/utils.py")
        memory.remember_file("tests/test_utils.py")
        memory.set_file_summary("src/utils.py", "def add(a,b): return a-b  # BUG: 减法应为加法")
        memory.set_file_summary("tests/test_utils.py", "def test_add(): assert add(2,3)==5")

        # 第 2 层：记录错误发现
        memory.append_note(
            "utils.py 第 2 行: return a - b 应该是 return a + b，这是导致测试失败的原因",
            tags=("bug", "fix"),
            created_at="2026-06-27T10:05:00+00:00",
        )
        memory.append_note(
            "test_utils.py 第 3 行: assert add(2,3)==5 — 测试期望正确，代码实现错误",
            tags=("test",),
            created_at="2026-06-27T10:06:00+00:00",
        )

        show_state("读取 4 个文件 + 记录 4 条笔记后", memory)
        show_memory_text("第 2 步后 — 注入 prompt 的内容", memory)

        print("""
  ┌─────────────────────────────────────────────────────────┐
  │  第 1 层：Working Memory — 文件数增多                     │
  │    - recent_files: [config.py, main.py, utils.py,        │
  │                     test_utils.py]  (4/8 个)             │
  │                                                          │
  │  第 2 层：Episodic Notes — 新增 2 条 (共 4 条)            │
  │    - utils.py bug: a-b 应为 a+b  [tags: bug, fix]        │
  │    - test_utils.py 测试期望正确 [tags: test]              │
  └─────────────────────────────────────────────────────────┘""")

        # ═══════════════════════════════════════════════════════
        # 第 3 步：演示检索能力
        # ═══════════════════════════════════════════════════════
        hr("第 3 步：检索演示 — 不同关键词命中不同的笔记")

        show_retrieval("检索 'bug'", memory, "bug")
        show_retrieval("检索 'security'", memory, "security")
        show_retrieval("检索 'config'", memory, "config")
        show_retrieval("检索 'database'", memory, "database")

        print("""
  ┌─────────────────────────────────────────────────────────┐
  │  检索逻辑 (纯关键词，不依赖 embedding):                   │
  │                                                          │
  │  1. tag 精确命中 → 最高优先级                             │
  │  2. 关键词重叠数 → 次优先级                                │
  │  3. 创建时间 → 同分时更新优先                              │
  │                                                          │
  │  "database" 命中 0 条 — 虽然有 DATABASE_URL，但笔记里      │
  │  并没有出现 "database" 这个词。检索只匹配笔记文本和         │
  │  tags，不直接参与文件内容。                                │
  └─────────────────────────────────────────────────────────┘""")

        # ═══════════════════════════════════════════════════════
        # 第 4 步：持久记忆写入
        # ═══════════════════════════════════════════════════════
        hr("第 4 步：将重要知识 promote 到持久记忆 (第 3 层)")

        # 写入 .page/memory/ 目录（跨会话存活）
        promoted, superseded = memory.promote_durable([
            ("project-conventions", "敏感配置项（如 SECRET_KEY）在输出中需要脱敏"),
            ("dependency-facts", "config.DEBUG 被 main.py 依赖，修改需同时检查 main.py"),
        ])

        show_state("promote 2 条到持久记忆后", memory)
        print(f"\n    新 promote: {promoted}")
        print(f"    已合并/替代: {superseded or '(无)'}")

        # 检查文件系统
        mem_dir = root / ".page" / "memory"
        print(f"\n    持久记忆文件系统 ({mem_dir})：")
        print(f"    {'✓' if (mem_dir / 'MEMORY.md').exists() else '✗'} MEMORY.md")
        print(f"    {'✓' if (mem_dir / 'topics' / 'project-conventions.md').exists() else '✗'} topics/project-conventions.md")
        print(f"    {'✓' if (mem_dir / 'topics' / 'dependency-facts.md').exists() else '✗'} topics/dependency-facts.md")

        # 打印文件内容
        if (mem_dir / "MEMORY.md").exists():
            print(f"\n    文件内容 — MEMORY.md:")
            for line in (mem_dir / "MEMORY.md").read_text(encoding="utf-8").splitlines():
                print(f"      {line}")
        if (mem_dir / "topics" / "project-conventions.md").exists():
            print(f"\n    文件内容 — topics/project-conventions.md (节选):")
            lines = (mem_dir / "topics" / "project-conventions.md").read_text(encoding="utf-8").splitlines()
            for line in lines[:12]:
                print(f"      {line}")

        print("""
  ┌─────────────────────────────────────────────────────────┐
  │  第 3 层：Durable Memory — 已写入到磁盘                   │
  │    - .page/memory/MEMORY.md  (索引文件)                  │
  │    - .page/memory/topics/project-conventions.md          │
  │    - .page/memory/topics/dependency-facts.md             │
  │                                                          │
  │  关键特性：                                               │
  │    - 跨会话持久化 (session 结束也不会消失)                  │
  │    - 同 topic 中相同 subject 的笔记会自动合并 (不是重复加)   │
  │    - 检索时同时覆盖 episodic + durable 两种来源            │
  └─────────────────────────────────────────────────────────┘""")

        # ═══════════════════════════════════════════════════════
        # 第 5 步：模拟跨会话 — 新建一个 LayeredMemory 实例，
        #   观察持久记忆被重新加载
        # ═══════════════════════════════════════════════════════
        hr("第 5 步：模拟跨会话恢复 — 新建 LayeredMemory，持久记忆仍在")

        # 新建一个 LayeredMemory (模拟新 session)，不传任何状态
        fresh_memory = LayeredMemory(workspace_root=str(root))
        show_state("新 session 的状态 (episodic 全空，durable 仍在)", fresh_memory)
        show_memory_text("新 session — 注入 prompt 的内容", fresh_memory)

        # 即使是新 session，检索仍然能找到 durable 记忆
        show_retrieval("新 session 检索 'SECRET_KEY'", fresh_memory, "SECRET_KEY")
        show_retrieval("新 session 检索 'config.DEBUG'", fresh_memory, "config.DEBUG")
        show_retrieval("新 session 检索 'bug' (episodic, 在新 session 中已丢失)", fresh_memory, "bug")

        print("""
  ┌─────────────────────────────────────────────────────────┐
  │  跨会话对比:                                              │
  │                                                          │
  │  旧 session (第 4 步后):                                  │
  │    - 第 1 层 Working: task + 4 files + 4 summaries       │
  │    - 第 2 层 Episodic: 4 条笔记                          │
  │    - 第 3 层 Durable: 2 个 topic                          │
  │                                                          │
  │  新 session (第 5 步):                                    │
  │    - 第 1 层 Working: ✗ 全部归零                          │
  │    - 第 2 层 Episodic: ✗ 全部消失 (仅在 session 内有效)    │
  │    - 第 3 层 Durable: ✓ 仍然存在 (从磁盘加载)               │
  │                                                          │
  │  所以新 session 中:                                       │
  │    "bug" 检索 → 0 条 (episodic 丢失了)                    │
  │    "SECRET_KEY" → 1 条 (durable 还在)                     │
  └─────────────────────────────────────────────────────────┘""")

        # ═══════════════════════════════════════════════════════
        # 第 6 步：演示数量上限 (Working 8 文件 / Episodic 12 条)
        # ═══════════════════════════════════════════════════════
        hr("第 6 步：演示数量上限 — 超过上限后自动淘汰最旧的")

        # 添加 10 个文件（上限 8 个，前 2 个会被淘汰）
        for i in range(10):
            memory.remember_file(f"file_{i:02d}.py")
        # 添加 15 条笔记（上限 12 条，前 3 条会被淘汰）
        for i in range(15):
            memory.append_note(
                f"这是第 {i:02d} 条笔记，用于测试上限淘汰机制",
                tags=(f"test{i}",),
                created_at=f"2026-06-27T11:{i:02d}:00+00:00",
            )

        show_state("超过上限后", memory)
        print(f"\n    文件: 添加了 10 个 → 保留了 {len(memory.to_dict()['working']['recent_files'])} 个 (上限 {WORKING_FILE_LIMIT})")
        print(f"    笔记: 添加了 15 条 → 保留了 {len(memory.to_dict()['episodic_notes'])} 条 (上限 {EPISODIC_NOTE_LIMIT})")
        print(f"    最早添加的 config.py 是否还在: {'✓' if 'config.py' in memory.to_dict()['working']['recent_files'] else '✗ 已被淘汰'}")
        print(f"    最早添加的 'config.py SECRET_KEY' 笔记是否还在: "
              f"{'✓' if any('SECRET_KEY' in n['text'] for n in memory.to_dict()['episodic_notes']) else '✗ 已被淘汰'}")

        print("""
  ┌─────────────────────────────────────────────────────────┐
  │  淘汰规则：                                               │
  │                                                          │
  │  Working Memory                                          │
  │    - recent_files: 只保留最新 8 个 (WORKING_FILE_LIMIT)    │
  │    - 旧文件自动被推出队列                                  │
  │    - 但 file_summaries 不会自动清理 (需手动 invalidate)    │
  │                                                          │
  │  Episodic Notes                                          │
  │    - 只保留最新 12 条 (EPISODIC_NOTE_LIMIT)               │
  │    - 旧笔记自动被丢弃                                      │
  │                                                          │
  │  Durable Memory                                          │
  │    - 没有数量上限                                         │
  │    - 同一 topic 同一 subject 的内容会自动合并               │
  │    - 旧的被新的替代 (supersede)                           │
  └─────────────────────────────────────────────────────────┘""")

        # ═══════════════════════════════════════════════════════
        # 第 7 步：演示文件新鲜度 (freshness) 检查
        # ═══════════════════════════════════════════════════════
        hr("第 7 步：文件新鲜度检查 — 文件被外部修改后，摘要自动失效")

        # 先给一个文件设摘要
        test_memory = LayeredMemory(workspace_root=str(root))
        (root / "data.txt").write_text("original content v1\n", encoding="utf-8")
        test_memory.remember_file("data.txt")
        test_memory.set_file_summary("data.txt", "original content v1")

        print(f"\n    设置摘要时的文件 hash: "
              f"{test_memory.to_dict()['file_summaries']['data.txt']['freshness'][:16]}...")

        # 模拟外部修改
        (root / "data.txt").write_text("MODIFIED content v2 — someone changed this!\n", encoding="utf-8")
        print(f"    外部修改了 data.txt (v1 → v2)")

        # 刷新并检查过期
        invalidated = test_memory.invalidate_stale_file_summaries()
        print(f"    失效的摘要: {invalidated}")

        show_state("外部修改后", test_memory)
        print(f"    data.txt 摘要是否还在: "
              f"{'✓' if 'data.txt' in test_memory.to_dict()['file_summaries'] else '✗ 已被自动清除 — 因为文件 hash 变了'}")

        print("""
  ┌─────────────────────────────────────────────────────────┐
  │  文件新鲜度机制：                                         │
  │                                                          │
  │  set_file_summary 时记录文件的 sha256 hash                 │
  │  invalidate_stale_file_summaries() 重新计算 hash 对比     │
  │  如果 hash 变了 → 摘要失效 → 自动清除                       │
  │                                                          │
  │  设计意图：防止模型依赖过时的文件摘要                        │
  │  与 checkpoint 的关键文件新鲜度检测是同一种设计思想         │
  └─────────────────────────────────────────────────────────┘""")


if __name__ == "__main__":
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  三层记忆系统 (LayeredMemory) 可视化演示                      ║")
    print("║  Layer 1: Working Memory   Layer 2: Episodic Notes          ║")
    print("║  Layer 3: Durable Memory   + 检索 / 上限 / 新鲜度            ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    demo()

    print()
    print("=" * 70)
    print("  演示完毕。关注以上输出中的：")
    print("  ① 三层各自的职责边界和数据生命周期")
    print("  ② render_memory_text 的输出 — 这就是注入 prompt 的 memory 段")
    print("  ③ 检索如何命中不同层的笔记 (tag > 关键词 > 时间)")
    print("  ④ 跨会话：episodic 丢失 vs durable 持久")
    print("  ⑤ 数量上限和文件新鲜度的自动维护")
    print("=" * 70)
