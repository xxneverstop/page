"""
直观观察 Page 的六层工具安全闸口 (ToolExecutor)

六层校验链 (tool_executor.py:45-160):
  ① 白名单检查    — allowed_tools 控制哪些工具可用
  ② 工具存在性    — 防止模型幻想出不存在的工具
  ③ 参数校验      — 路径沙箱、参数范围、patch_file 精确一次
  ④ 防重复调用    — 连续两次相同调用被拦截
  ⑤ 审批检查      — risky 工具需要确认 (ask/auto/never)
  ⑥ 快照对比      — 执行前后各拍一次 workspace 快照，diff 追踪变化

用法:
  cd D:\workspace\page
  python scratch\demo_tool_safety.py
"""

from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', write_through=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from page import FakeModelClient, Page, SessionStore, WorkspaceContext
from page.tool_executor import ToolExecutor, ToolExecutionResult


def hr(title):
    print()
    print("=" * 68)
    print(f"  {title}")
    print("=" * 68)


def sub(title):
    print(f"\n  ── {title} ──")


def show_result(result: ToolExecutionResult):
    """展示工具执行结果"""
    m = result.metadata
    status_icon = {"ok": "[OK]", "rejected": "[REJECTED]", "error": "[ERROR]",
                   "partial_success": "[PARTIAL]"}.get(m["tool_status"], "[?]")
    print(f"    {status_icon} tool_status={m['tool_status']} "
          f"error_code={m.get('tool_error_code', '') or '-'} "
          f"risk={m['risk_level']} read_only={m['read_only']}")
    if m.get("security_event_type"):
        print(f"         security_event: {m['security_event_type']}")
    if m.get("affected_paths"):
        print(f"         affected_paths: {m['affected_paths']}")
    if m.get("diff_summary"):
        print(f"         diff: {m['diff_summary']}")
    content_preview = result.content[:120].replace("\n", "\\n")
    print(f"         content: {content_preview}")


# ═══════════════════════════════════════════════════════════════
# 场景：逐层演示六层安全闸口
# ═══════════════════════════════════════════════════════════════

def demo():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "README.md").write_text("# Safe Project\n", encoding="utf-8")
        (root / "src").mkdir(exist_ok=True)
        (root / "src" / "app.py").write_text("def run():\n    return 'ok'\n", encoding="utf-8")
        (root / "tests").mkdir(exist_ok=True)
        (root / "tests" / "test_app.py").write_text("from src.app import run\n\ndef test_run():\n    assert run() == 'ok'\n", encoding="utf-8")

        workspace = WorkspaceContext.build(root)
        store = SessionStore(root / ".page" / "sessions")

        def make_agent(**kw):
            return Page(
                model_client=FakeModelClient([]),
                workspace=workspace,
                session_store=store,
                approval_policy=kw.pop("approval_policy", "auto"),
                **kw,
            )

        # ═══════════════════════════════════════════════════
        # 第 0 步：总览 — 六层在代码中的位置
        # ═══════════════════════════════════════════════════
        hr("总览：六层安全闸口在 ToolExecutor.execute() 中的位置")

        agent0 = make_agent()
        executor = ToolExecutor(agent0)

        print("""
    ToolExecutor.execute(name, args)
      │
      ├─ ① 白名单检查 (行 47)
      │     if allowed_tools is not None and name not in allowed_tools:
      │         return rejected: tool_not_allowed
      │
      ├─ ② 工具存在性检查 (行 58)
      │     tool = agent.tools.get(name)
      │     if tool is None:
      │         return rejected: unknown_tool
      │
      ├─ ③ 参数校验 (行 70-87)
      │     agent.validate_tool(name, args)
      │     内部: context.path() 做路径沙箱 (防 "../" 逃逸 + 符号链接)
      │     如果失败: return rejected: invalid_arguments
      │
      ├─ ④ 防重复检查 (行 89-98)
      │     if agent.repeated_tool_call(name, args):
      │         最近 2 次 tool event 的 name + args 完全相同 → 拒绝
      │         return rejected: repeated_identical_call
      │
      ├─ ⑤ 审批检查 (行 100-110)
      │     if tool["risky"] and not agent.approve(name, args):
      │         approval_policy: "ask" → input(), "auto" → True, "never" → False
      │         return rejected: approval_denied
      │
      ├─ ⑥ 执行前快照 (行 112)
      │     before_snapshot = agent.capture_workspace_snapshot()
      │
      ├─ 真正执行 (行 115)
      │     content = tool["run"](args)
      │
      └─ ⑥ 执行后快照 + diff (行 116-118)
            after_snapshot = agent.capture_workspace_snapshot()
            affected_paths, diff_summary = agent.diff_workspace_snapshots(before, after)""")

        # ═══════════════════════════════════════════════════
        # 第 1 层：白名单
        # ═══════════════════════════════════════════════════
        hr("第 ① 层：白名单检查 — 控制哪些工具可用")

        # 默认：所有工具可用
        agent1a = make_agent()
        result1a = agent1a.tool_executor.execute("read_file", {"path": "README.md", "start": 1, "end": 1})
        show_result(result1a)

        # 白名单限制：只允许 list_files 和 read_file
        agent1b = make_agent(allowed_tools={"list_files", "read_file"})
        result1b = agent1b.tool_executor.execute("write_file", {"path": "test.txt", "content": "hi"})
        show_result(result1b)
        print(f"\n    allowed_tools={agent1b.allowed_tools}")
        print(f"    write_file 不在白名单中 → 被第①层拦截")

        # ═══════════════════════════════════════════════════
        # 第 2 层：工具存在性
        # ═══════════════════════════════════════════════════
        hr("第 ② 层：工具存在性 — 防止模型幻想出工具")

        result2 = agent1a.tool_executor.execute("delete_all_files", {"path": "."})
        show_result(result2)
        print(f"\n    'delete_all_files' 不在任何工具注册表中 → 被第②层拦截")

        # ═══════════════════════════════════════════════════
        # 第 3 层：参数校验 + 路径沙箱
        # ═══════════════════════════════════════════════════
        hr("第 ③ 层：参数校验 — 路径沙箱防逃逸 + 参数约束")

        # 3a: 路径逃逸尝试
        print(f"\n  [3a] 路径逃逸尝试:")
        result3a = agent1a.tool_executor.execute("read_file", {"path": "../../etc/passwd"})
        show_result(result3a)
        print(f"    workspace root: {agent1a.root}")
        print(f"    ../../etc/passwd 不在 root 子树内 → os.path.commonpath 检测到逃逸")

        # 3b: 合法路径
        print(f"\n  [3b] 合法路径:")
        result3b = agent1a.tool_executor.execute("read_file", {"path": "README.md", "start": 1, "end": 2})
        show_result(result3b)

        # 3c: 参数范围校验
        print(f"\n  [3c] run_shell timeout 超范围:")
        result3c = agent1a.tool_executor.execute("run_shell", {"command": "echo hi", "timeout": 999})
        show_result(result3c)
        print(f"    timeout 必须在 [1, 120] 内，999 超了")

        # 3d: 缺少必需参数
        print(f"\n  [3d] read_file 缺少 path 参数:")
        result3d = agent1a.tool_executor.execute("read_file", {"start": 1})
        show_result(result3d)

        # 3e: patch_file old_text 精确一次约束
        print(f"\n  [3e] patch_file old_text 出现次数检查:")
        (root / "data.txt").write_text("hello world\nhello world\n", encoding="utf-8")
        # old_text 出现 2 次 → 必须恰好出现 1 次
        result3e = agent1a.tool_executor.execute(
            "patch_file",
            {"path": "data.txt", "old_text": "hello world", "new_text": "hi"}
        )
        show_result(result3e)
        print(f"    'hello world' 在 data.txt 里出现了 2 次")
        print(f"    patch_file 要求 old_text 恰好在文件中出现 1 次 (防模糊匹配)")
        # 修正：old_text 恰好出现 1 次
        (root / "data.txt").write_text("hello world\n", encoding="utf-8")
        result3e2 = agent1a.tool_executor.execute(
            "patch_file",
            {"path": "data.txt", "old_text": "hello world", "new_text": "hi there"}
        )
        show_result(result3e2)

        # ═══════════════════════════════════════════════════
        # 第 4 层：防重复调用
        # ═══════════════════════════════════════════════════
        hr("第 ④ 层：防重复调用 — 拦截死循环")

        # 先执行一次，并在 history 中留痕 (模拟 AgentLoop 的行为)
        agent4 = make_agent()
        r = agent4.tool_executor.execute("read_file", {"path": "README.md", "start": 1, "end": 1})
        agent4.record({"role": "tool", "name": "read_file",
                        "args": {"path": "README.md", "start": 1, "end": 1},
                        "content": r.content, "created_at": "2026-07-01T10:00:00+00:00"})

        # 再执行一次完全相同的调用 — 这次 history 里有上一次的 tool event
        print(f"\n  执行第 1 次 read_file README.md → OK (留痕在 history)")
        print(f"  执行第 2 次完全相同的 read_file README.md:")
        result4 = agent4.tool_executor.execute("read_file", {"path": "README.md", "start": 1, "end": 1})
        show_result(result4)

        print(f"\n  防重复逻辑 (runtime.py:533-540):")
        print(f"    取最近 2 个 tool event, 如果 name + args 完全相同 → 拦截")
        print(f"    第 1 次调用留下 tool event: read_file README.md")
        print(f"    第 2 次调用时: 最近 2 个 tool event = [read_file README.md, read_file README.md]")
        print(f"    完全相同 → 被第④层拦截")

        # 换了参数就可以通过
        result4b = agent4.tool_executor.execute("read_file", {"path": "README.md", "start": 1, "end": 3})
        show_result(result4b)
        print(f"    换了参数 start=1 end=3 → 不是完全相同 → 通过")

        # ═══════════════════════════════════════════════════
        # 第 5 层：审批检查
        # ═══════════════════════════════════════════════════
        hr("第 ⑤ 层：审批检查 — risky 工具需要确认")

        # write_file 是 risky 工具

        print(f"\n  [5a] approval_policy='auto' (自动批准):")
        agent5a = make_agent(approval_policy="auto")
        result5a = agent5a.tool_executor.execute("write_file", {"path": "out.txt", "content": "auto approved"})
        show_result(result5a)

        print(f"\n  [5b] approval_policy='never' (自动拒绝):")
        agent5b = make_agent(approval_policy="never")
        result5b = agent5b.tool_executor.execute("write_file", {"path": "out.txt", "content": "blocked"})
        show_result(result5b)

        print(f"\n  [5c] read_only=True 模式:")
        agent5c = make_agent(read_only=True)
        result5c = agent5c.tool_executor.execute("write_file", {"path": "out.txt", "content": "blocked"})
        show_result(result5c)
        print(f"    read_only 模式下，agent.approve() 直接返回 False (行 632-633)")

        print(f"\n  [5d] 非 risky 工具 (read_file) 不需要审批:")
        result5d = agent5b.tool_executor.execute("read_file", {"path": "README.md", "start": 1, "end": 1})
        show_result(result5d)
        print(f"    read_file 是 safe 工具, 跳过审批检查")

        # ═══════════════════════════════════════════════════
        # 第 6 层：快照对比
        # ═══════════════════════════════════════════════════
        hr("第 ⑥ 层：执行前后快照对比 — 精确追踪文件变化")

        agent6 = make_agent(approval_policy="auto")

        # 先看执行前 workspace 状态
        before = agent6.capture_workspace_snapshot()
        print(f"\n  执行前快照: {len(before)} 个文件")
        for fpath in sorted(before)[:5]:
            print(f"    {fpath}: sha256={before[fpath][:16]}...")

        # 执行一个写操作
        result6a = agent6.tool_executor.execute("write_file", {"path": "new_file.txt", "content": "created by agent"})
        show_result(result6a)

        # 再写一个文件
        result6b = agent6.tool_executor.execute("write_file", {"path": "src/another.py", "content": "x = 1\ny = 2\n"})
        show_result(result6b)

        print(f"\n  diff_summary 记录了每次工具执行的文件变化:")
        print(f"    第 1 次 write_file: diff={result6a.metadata['diff_summary']}")
        print(f"    第 2 次 write_file: diff={result6b.metadata['diff_summary']}")

        # 演示 partial_success：run_shell 失败但文件已被修改
        print(f"\n  [6c] partial_success: run_shell 非零退出但改了文件")
        agent6c = make_agent(approval_policy="auto")
        # 先执行 run_shell，这个命令会失败但文件被修改（之前的操作残留）
        result6c = agent6c.tool_executor.execute("run_shell", {"command": "python -c \"print(1); exit(1)\"", "timeout": 10})
        show_result(result6c)
        if result6c.metadata["tool_status"] in ("error", "partial_success"):
            print(f"    exit_code != 0 → tool_status={result6c.metadata['tool_status']}")
            if result6c.metadata.get("workspace_changed"):
                print(f"    但 workspace 发生了变化 → 被标记为 partial_success")

        # ═══════════════════════════════════════════════════
        # 第 7 步：安全事件分类
        # ═══════════════════════════════════════════════════
        hr("总结：六层拦截 + 安全事件分类")

        print("""
    六层安全闸口 总览
    ═══════════════════════════════════════════════════════
    ① 白名单       → tool_not_allowed       管理员控制可用工具范围
    ② 存在性       → unknown_tool            防模型幻觉
    ③ 参数校验     → invalid_arguments       路径沙箱 + 参数约束
                        path_escape            "../" 逃逸被标记为安全事件
    ④ 防重复       → repeated_identical_call  防死循环
    ⑤ 审批         → approval_denied          risky 工具需确认
                        read_only_block       只读模式拒绝所有写操作
    ⑥ 快照对比     → ok / partial_success / error
                        created:/modified:/deleted:  文件变化的精确追踪

    元数据字段 (每层都会记录):
      tool_status:       ok | rejected | error | partial_success
      tool_error_code:   被哪一层拦截 -> 精确的错误码
      security_event_type: path_escape | approval_denied | read_only_block
      risk_level:        low (只读) | high (risky)
      read_only:         True (安全工具) | False (risky 工具)
      affected_paths:    [被修改的文件列表]
      diff_summary:      [created:..., modified:..., deleted:...]
    """)


if __name__ == "__main__":
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  ToolExecutor 六层安全闸口 可视化演示                          ║")
    print("║  白名单 → 存在性 → 参数校验 → 防重复 → 审批 → 快照对比        ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    demo()

    print()
    print("=" * 68)
    print("  演示完毕。关注以上输出中的：")
    print("  ① 每一层在什么条件下拦截 → 返回什么 error_code")
    print("  ② 路径沙箱怎么检测 '../' 逃逸")
    print("  ③ 防重复的 '最近 2 次' 判断逻辑")
    print("  ④ 三种审批策略的差异 (auto/never/read_only)")
    print("  ⑤ 快照对比如何精确追踪文件变化 (created/modified/deleted)")
    print("  ⑥ metadata 中每条都记录了 tool_status + error_code + risk_level")
    print("=" * 68)
