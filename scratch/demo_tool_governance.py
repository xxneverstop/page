"""
直观观察 Page 工具安全与运行治理的全部过程
═══════════════════════════════════════════════════════════════

覆盖「六、贡献点 5：工具安全与运行治理」的全部内容：

  A. 六层安全闸口 (tool_executor.py)
     ① 白名单      — allowed_tools 控制工具可用范围
     ② 存在性      — 防止模型幻觉出不存在的工具
     ③ 参数校验    — 路径沙箱 + 参数范围 + patch_file 精确一次
     ④ 防重复      — 连续 2 次相同调用被拦截
     ⑤ 审批        — risky 工具三种策略 + read_only 模式
     ⑥ 快照对比    — sha256 diff 追踪 + partial_success 识别

  B. Security 模块 (security.py)
     - Secret 检测: API key 正则扫描与自动脱敏
     - Shell 环境变量白名单: 子进程只继承安全变量
     - 配置文件脱敏: redact_text / redact_artifact

  C. Metadata 系统
     - 统一的 ToolExecutionResult 格式
     - tool_status / tool_error_code / security_event_type
     - risk_level / affected_paths / diff_summary

用法:
  cd D:/workspace/page
  python scratch/demo_tool_governance.py
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', write_through=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from page import FakeModelClient, Page, SessionStore, WorkspaceContext
from page import security as securitylib
from page.tool_executor import ToolExecutor, ToolExecutionResult


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


def fail(msg):
    print(f"    ✗ {msg}")


def info(msg):
    print(f"    ℹ {msg}")


def show_result(result: ToolExecutionResult):
    m = result.metadata
    status_icon = {
        "ok": "✓",
        "rejected": "✗",
        "error": "✗",
        "partial_success": "⚠",
    }.get(m["tool_status"], "?")

    print(f"    [{status_icon}] status={m['tool_status']}  "
          f"error_code={m.get('tool_error_code', '') or '-'}  "
          f"risk={m['risk_level']}  read_only={m['read_only']}")

    if m.get("security_event_type"):
        print(f"         🔒 security_event: {m['security_event_type']}")

    if m.get("affected_paths"):
        print(f"         📁 affected_paths: {m['affected_paths']}")

    if m.get("diff_summary"):
        for d in m["diff_summary"]:
            print(f"         📝 diff: {d}")

    if m.get("workspace_fingerprint"):
        print(f"         🔑 fingerprint: {m['workspace_fingerprint'][:16]}...")

    content_preview = result.content[:150].replace("\n", "\\n")
    print(f"         💬 content: {content_preview}")


# ═══════════════════════════════════════════════════════════════
# 主演示
# ═══════════════════════════════════════════════════════════════

def demo():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "README.md").write_text("# Demo Project\n\nThis is a test project.\n", encoding="utf-8")
        (root / ".env").write_text("DEBUG=True\nAPI_KEY=sk-abc123xyz456\ndb_password=secret123\n", encoding="utf-8")
        (root / "src").mkdir(exist_ok=True)
        (root / "src" / "app.py").write_text("def run():\n    return 'ok'\n", encoding="utf-8")
        (root / "src" / "config.py").write_text("DEBUG = True\nSECRET_KEY = 'my-secret'\n", encoding="utf-8")
        (root / "tests").mkdir(exist_ok=True)
        (root / "tests" / "test_app.py").write_text(
            "from src.app import run\n\ndef test_run():\n    assert run() == 'ok'\n", encoding="utf-8")

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

        # ═══════════════════════════════════════════════════════
        # PART A: 六层安全闸口
        # ═══════════════════════════════════════════════════════

        hr("总览：六层安全闸口的代码执行顺序")

        print("""
    ToolExecutor.execute(name, args)        ← tool_executor.py:45
      │
      ├─ ① 白名单 (行 47)                  if allowed_tools and name not in it
      │     → rejected: tool_not_allowed
      │
      ├─ ② 存在性 (行 58)                  if agent.tools.get(name) is None
      │     → rejected: unknown_tool
      │
      ├─ ③ 参数校验 (行 70-87)             agent.validate_tool(name, args)
      │     └ 内部: context.path() 做路径沙箱 → resolve + commonpath
      │     → rejected: invalid_arguments (+ path_escape 安全事件)
      │
      ├─ ④ 防重复 (行 89-98)               agent.repeated_tool_call(name, args)
      │     └ 取 history 中最近 2 个 tool event 对比 name + args
      │     → rejected: repeated_identical_call
      │
      ├─ ⑤ 审批 (行 100-110)               if risky and not agent.approve()
      │     └ 三种策略: auto(全批) / never(全拒) / ask(input交互)
      │     └ read_only 模式: 无条件拒绝所有 risky 工具
      │     → rejected: approval_denied (+ read_only_block)
      │
      ├─ ⑥ 执行前快照 (行 112)              before = capture_workspace_snapshot()
      │
      ├─ 真正执行 (行 115)                  content = tool["run"](args)
      │
      └─ ⑥ 执行后快照+diff (行 116-118)    after = capture_workspace_snapshot()
                                             diff_workspace_snapshots(before, after)
                                             → ok / partial_success / error
    """)

        # ─── 第 ① 层：白名单 ───

        hr("第 ① 层：白名单检查 — 管理员控制可用工具范围")

        agent = make_agent()
        sub("默认：所有工具可用")
        r = agent.tool_executor.execute("read_file", {"path": "README.md", "start": 1, "end": 2})
        show_result(r)
        ok("read_file 在白名单中（默认无限制），通过")

        sub("限制：allowed_tools={'list_files', 'read_file'}")
        agent_restricted = make_agent(allowed_tools={"list_files", "read_file"})
        r = agent_restricted.tool_executor.execute("write_file", {"path": "x.txt", "content": "hi"})
        show_result(r)
        fail(f"write_file 不在 {agent_restricted.allowed_tools} 中，被第①层拦截")

        # ─── 第 ② 层：工具存在性 ───

        hr("第 ② 层：工具存在性 — 防止模型幻想出不存在的工具")

        r = agent.tool_executor.execute("delete_all_files", {"path": "."})
        show_result(r)
        info("模型可能从训练数据中见过其他 agent 的工具名（如 'delete_all_files'）")
        info("只要不在 Page 的注册表里，就被第②层拦截")

        sub("Page 实际注册的 7 个工具")
        for name in agent.tools:
            risky_tag = "🔴 RISKY" if agent.tools[name]["risky"] else "🟢 safe"
            print(f"      {risky_tag}  {name}")

        # ─── 第 ③ 层：参数校验 + 路径沙箱 ───

        hr("第 ③ 层：参数校验 — 核心安全机制（路径沙箱 + 参数约束）")

        sub("3a: 路径逃逸 '../' — 最经典的攻击向量")
        print(f"      workspace root: {agent.root}")
        r = agent.tool_executor.execute("read_file", {"path": "../../etc/passwd"})
        show_result(r)
        info("Page.path() 三步防御:")
        info("  1) 相对路径拼到 root: ../../etc/passwd → /tmp/.../../../etc/passwd")
        info("  2) Path.resolve() 解析所有 .. 和符号链接 → /etc/passwd")
        info("  3) os.path.commonpath(root, resolved) ≠ root → 逃逸! → ValueError")

        sub("3b: 合法路径 — 正常通过")
        r = agent.tool_executor.execute("read_file", {"path": "README.md", "start": 1, "end": 2})
        show_result(r)
        ok("README.md 在 workspace 内，路径沙箱放行")

        sub("3c: 参数范围校验 — run_shell timeout 必须在 [1, 120]")
        r = agent.tool_executor.execute("run_shell", {"command": "echo hi", "timeout": 999})
        show_result(r)
        info("timeout=999 超出 [1,120] 范围 → 被第③层拦截")

        sub("3d: 缺少必需参数 — read_file 必须有 path")
        r = agent.tool_executor.execute("read_file", {"start": 1, "end": 10})
        show_result(r)
        info("read_file 缺少 path 参数 → KeyError → 被拦截")

        sub("3e: patch_file 的 old_text 精确一次约束 (tools.py:129-139)")
        (root / "duplicate.txt").write_text("hello\nhello\n", encoding="utf-8")
        r = agent.tool_executor.execute(
            "patch_file",
            {"path": "duplicate.txt", "old_text": "hello", "new_text": "hi"}
        )
        show_result(r)
        info("'hello' 出现了 2 次 → str.count() 返回 2 → 拒绝（防模糊匹配）")
        (root / "unique.txt").write_text("hello world\n", encoding="utf-8")
        r = agent.tool_executor.execute(
            "patch_file",
            {"path": "unique.txt", "old_text": "hello world", "new_text": "hi"}
        )
        show_result(r)
        ok("'hello world' 恰好出现 1 次 → 通过并成功 patch")

        sub("3f: write_file path 是目录")
        r = agent.tool_executor.execute("write_file", {"path": "src", "content": "x"})
        show_result(r)
        info("src/ 是一个目录 → 不能当文件写 → 被拒绝")

        # ─── 第 ④ 层：防重复 ───

        hr("第 ④ 层：防重复调用 — 最近 2 次历史相同，第 3 次被拦截")

        agent4 = make_agent()
        sub("第 1 次调用 read_file README.md:1-2 — 成功，留痕到 history")
        r1 = agent4.tool_executor.execute("read_file", {"path": "README.md", "start": 1, "end": 2})
        agent4.record({
            "role": "tool", "name": "read_file",
            "args": {"path": "README.md", "start": 1, "end": 2},
            "content": r1.content,
            "created_at": "2026-07-01T10:00:00+00:00",
        })
        show_result(r1)
        ok("history 中现有 1 个 tool event")

        sub("第 2 次调用 read_file README.md:1-2 — 成功，再次留痕")
        r2 = agent4.tool_executor.execute("read_file", {"path": "README.md", "start": 1, "end": 2})
        agent4.record({
            "role": "tool", "name": "read_file",
            "args": {"path": "README.md", "start": 1, "end": 2},
            "content": r2.content,
            "created_at": "2026-07-01T10:00:01+00:00",
        })
        show_result(r2)
        ok("history 中现有 2 个 tool event，都是 read_file README.md:1-2")

        sub("第 3 次调用 read_file README.md:1-2 → 被拦截！")
        r3 = agent4.tool_executor.execute("read_file", {"path": "README.md", "start": 1, "end": 2})
        show_result(r3)
        fail("最近 2 次历史都是 read_file(README.md,1,2) → 第④层拦截第 3 次调用")

        info("防重复逻辑 (runtime.py:533-540):")
        info("  取 history 中最近 2 个 tool event，如果 name + args 完全相同 → 拦截")
        info("  为什么是检查「最近 2 次」?")
        info("    第 1 次没上下文判断是否重复（需要 1 次做基准）")
        info("    第 2 次相同 = 可能是偶然（宽容一次）")
        info("    第 3 次相同 = 死循环强信号 → 拦截！")

        sub("换了参数 → 通过了")
        r = agent4.tool_executor.execute("read_file", {"path": "README.md", "start": 1, "end": 5})
        show_result(r)
        ok("start=1 end=5 ≠ start=1 end=2 → 不是完全相同 → 通过")

        # ─── 第 ⑤ 层：审批 ───

        hr("第 ⑤ 层：审批检查 — risky 工具需要确认（三种策略 + read_only）")

        sub("5a: approval_policy='auto' — 全部自动批准（默认推荐）")
        agent5a = make_agent(approval_policy="auto")
        r = agent5a.tool_executor.execute("write_file", {"path": "auto_out.txt", "content": "auto approved"})
        show_result(r)
        ok("auto 策略：risky 工具自动批准，安全工具不触发审批")

        sub("5b: approval_policy='never' — 全部自动拒绝")
        agent5b = make_agent(approval_policy="never")
        r = agent5b.tool_executor.execute("write_file", {"path": "blocked.txt", "content": "nope"})
        show_result(r)
        fail("never 策略：所有 risky 工具无条件拒绝")

        sub("5c: read_only=True 模式 — 无条件拒绝所有写操作")
        agent5c = make_agent(read_only=True)
        r = agent5c.tool_executor.execute("write_file", {"path": "blocked.txt", "content": "nope"})
        show_result(r)
        fail("read_only 模式: approve() 直接返回 False，不管 approval_policy 是什么")

        sub("5d: 非 risky 工具 (read_file) 不触发审批 — 直接跳过")
        r = agent5b.tool_executor.execute("read_file", {"path": "README.md", "start": 1, "end": 2})
        show_result(r)
        ok("read_file 不是 risky 工具，不经过审批检查")

        print()
        print("    工具风险分类:")
        print("      🟢 safe (不触发审批): list_files, read_file, search, delegate")
        print("      🔴 risky (需要审批):  run_shell, write_file, patch_file")

        # ─── 第 ⑥ 层：快照对比 ───

        hr("第 ⑥ 层：执行前后快照对比 — sha256 diff 精确追踪文件变化")

        agent6 = make_agent(approval_policy="auto")

        sub("6a: 执行前快照 — 整个 workspace 的文件→sha256 映射")
        before = agent6.capture_workspace_snapshot()
        print(f"      快照包含 {len(before)} 个文件:")
        for fpath in sorted(before):
            print(f"        {fpath:30s}  sha256={before[fpath][:16]}...")

        sub("6b: 执行 write_file 创建新文件 — diff 记录 created")
        r = agent6.tool_executor.execute("write_file", {"path": "new_doc.md", "content": "# New Doc\n"})
        show_result(r)
        ok(f"diff_summary 记录了: {r.metadata['diff_summary']}")

        sub("6c: 执行 patch_file 修改已有文件 — diff 记录 modified")
        r = agent6.tool_executor.execute(
            "patch_file",
            {"path": "README.md", "old_text": "# Demo Project", "new_text": "# Updated Project"}
        )
        show_result(r)
        ok(f"diff_summary 记录了: {r.metadata['diff_summary']}")

        sub("6d: run_shell 正常退出 (exit_code=0) — tool_status=ok")
        r = agent6.tool_executor.execute("run_shell", {"command": "echo hello world", "timeout": 10})
        show_result(r)
        ok("exit_code=0 且执行成功")

        sub("6e: run_shell 失败但改了文件 — tool_status=partial_success (核心设计!)")
        # 用 Python 创建一个文件然后以非零状态退出
        agent6e = make_agent(approval_policy="auto")
        r = agent6e.tool_executor.execute(
            "run_shell",
            {"command": "python -c \"open('side_effect.txt','w').write('oops'); exit(1)\"", "timeout": 10}
        )
        show_result(r)
        info("这个是 partial_success 的核心场景:")
        info("  shell 命令 exit_code ≠ 0 (失败了)")
        info("  但 workspace 发生了变化 (side_effect.txt 被创建了)")
        info("  → tool_status='partial_success' — 部分副作用已生效")
        info("  → 模型看到这个标记就知道要检查 affected_paths")

        # ═══════════════════════════════════════════════════════
        # PART B: Security 模块
        # ═══════════════════════════════════════════════════════

        hr("Security 模块：工具执行之外的三道额外防线 (security.py)")

        # ─── Secret 检测 ───

        sub("B1: Secret 检测 — looks_sensitive_env_name()")
        print("    检查环境变量名是否包含敏感标记:")
        test_names = ["API_KEY", "GITHUB_TOKEN", "DB_PASSWORD", "MY_SECRET", "PATH", "USER", "HOME"]
        for name in test_names:
            is_sensitive = securitylib.looks_sensitive_env_name(name)
            tag = "🔴 SENSITIVE" if is_sensitive else "🟢 safe"
            print(f"      {tag:20s}  {name}")
        info("检测逻辑: KEY/TOKEN/SECRET/PASSWORD 及以下划线结尾的变体")

        sub("B2: 从环境变量中检测敏感值 — detected_secret_env_items()")
        test_env = {
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "OPENAI_API_KEY": "sk-proj-1234567890abcdef",
            "ANTHROPIC_API_KEY": "anth-9876543210fedcba",
            "DB_PASSWORD": "super_secret_123",
            "USER": "demo",
        }
        secrets = securitylib.detected_secret_env_items(env=test_env)
        for name, value in secrets:
            print(f"      🔴 {name} = {value[:20]}...")
        print(f"      共检测到 {len(secrets)} 个敏感环境变量")

        sub("B3: 文本脱敏 — redact_text()")
        original = "用 API key sk-proj-1234567890abcdef 来认证，密码是 super_secret_123"
        redacted = securitylib.redact_text(original, env=test_env)
        print(f"      脱敏前: {original}")
        print(f"      脱敏后: {redacted}")
        ok("敏感值被替换为 <redacted>")

        sub("B4: 结构化数据脱敏 — redact_artifact()")
        artifact = {
            "model": "claude-sonnet-5",
            "api_key": "sk-ant-api-12345",
            "config": {"db_password": "secret123", "host": "localhost"},
            "tags": ["production", "token=abc123"],
        }
        redacted_artifact = securitylib.redact_artifact(artifact, env=test_env)
        print(f"      脱敏前: {artifact}")
        print(f"      脱敏后: {redacted_artifact}")
        ok("dict/list/str 递归脱敏，key 名匹配敏感标记的直接替换值")

        sub("B5: Shell 环境变量白名单 — shell_env()")
        test_env2 = {
            "HOME": "/home/user",
            "PATH": "/usr/bin:/bin",
            "USER": "demo",
            "LANG": "en_US.UTF-8",
            "OPENAI_API_KEY": "sk-deadbeef",
            "ANTHROPIC_API_KEY": "anth-cafebabe",
            "DB_PASSWORD": "secret",
        }
        allowlist = ("HOME", "LANG", "LC_ALL", "LC_CTYPE", "LOGNAME", "PATH", "PWD", "SHELL", "TERM", "TMPDIR", "TMP", "TEMP", "USER")
        safe_env = securitylib.shell_env(env=test_env2, allowlist=allowlist, root="/workspace")
        print(f"      原始环境变量: {len(test_env2)} 个")
        print(f"      白名单过滤后: {len(safe_env)} 个")
        for k, v in sorted(safe_env.items()):
            print(f"        ✓ {k} = {v}")
        info("OPENAI_API_KEY, ANTHROPIC_API_KEY, DB_PASSWORD 被子进程继承前被过滤掉")
        info("PWD 被强制设为 workspace root")

        # ═══════════════════════════════════════════════════════
        # PART C: Metadata 系统深入观察
        # ═══════════════════════════════════════════════════════

        hr("Metadata 系统：统一的 ToolExecutionResult 格式")

        print("""
    每次工具执行都返回统一的 ToolExecutionResult:
    ┌──────────────────────────────────────────────────────────┐
    │ content:  str              工具的文本输出（给模型看的）     │
    │ metadata: dict             平台对这次执行的判断（给系统用的）│
    │   ├─ tool_status:          ok | rejected | error | partial_success
    │   ├─ tool_error_code:      精确到被哪一层拦截
    │   │    tool_not_allowed | unknown_tool | invalid_arguments
    │   │    | repeated_identical_call | approval_denied
    │   │    | tool_failed | tool_partial_success
    │   ├─ security_event_type:  path_escape | approval_denied | read_only_block
    │   ├─ risk_level:           low (只读) | high (risky)
    │   ├─ read_only:            True | False
    │   ├─ affected_paths:       [被修改的文件路径]
    │   ├─ workspace_changed:    bool
    │   ├─ workspace_fingerprint: 执行后的 workspace sha256 指纹
    │   └─ diff_summary:         [created:... | modified:... | deleted:...]
    └──────────────────────────────────────────────────────────┘
    """)

        sub("对比：成功 vs 各种拦截的 metadata")
        agent_m = make_agent(approval_policy="auto")

        # 成功
        r_ok = agent_m.tool_executor.execute("read_file", {"path": "README.md", "start": 1, "end": 2})
        print(f"      ✅ 成功执行:")
        print(f"         tool_status={r_ok.metadata['tool_status']}")
        print(f"         error_code='{r_ok.metadata['tool_error_code']}'")
        print(f"         risk_level={r_ok.metadata['risk_level']}")

        # 白名单拦截
        r_wl = agent_restricted.tool_executor.execute("write_file", {"path": "x.txt", "content": "x"})
        print(f"\n      ❌ 白名单拦截:")
        print(f"         tool_status={r_wl.metadata['tool_status']}")
        print(f"         error_code={r_wl.metadata['tool_error_code']}")
        print(f"         risk_level={r_wl.metadata['risk_level']}")

        # 路径逃逸
        r_esc = agent_m.tool_executor.execute("read_file", {"path": "../../etc/passwd"})
        print(f"\n      🔒 路径逃逸 (安全事件):")
        print(f"         tool_status={r_esc.metadata['tool_status']}")
        print(f"         error_code={r_esc.metadata['tool_error_code']}")
        print(f"         security_event={r_esc.metadata['security_event_type']}")

        info("所有 metadata 最终都会进入 trace.jsonl 和 report.json，确保可审计")

        # ═══════════════════════════════════════════════════════
        # PART D: 综合场景 — 模拟一次完整的工具调用链
        # ═══════════════════════════════════════════════════════

        hr("综合场景：模拟 AgentLoop 中一次完整的工具调用链")

        agent_e2e = make_agent(approval_policy="auto")

        print("""
    模拟场景: 模型要 "检查 config.py 的 SECRET_KEY 是否安全"

    AgentLoop.run() 中的流程:
      while loop:
        ① context_manager.build(user_message)  → 组装 prompt
        ② model_client.complete(prompt)         → 模型返回 <tool> 标签
        ③ Page.parse(raw)                       → 解析出 (kind=tool, payload)
        ④ tool_executor.execute(name, args)     → 六层安检 + 执行
        ⑤ agent.record()                        → 写入 history
        ⑥ memory.update_memory_after_tool()     → 写入 working memory
        ⑦ checkpoint.create_checkpoint()         → 存盘断点
    """)

        # Step 1: 模型返回 read_file 工具调用
        sub("Step 1: 模型返回 read_file config.py")
        r1 = agent_e2e.tool_executor.execute("read_file", {"path": "src/config.py", "start": 1, "end": 3})
        agent_e2e.record({
            "role": "tool", "name": "read_file",
            "args": {"path": "src/config.py", "start": 1, "end": 3},
            "content": r1.content,
            "created_at": "2026-07-01T10:00:00+00:00",
        })
        show_result(r1)
        ok("读到 config.py: DEBUG=True, SECRET_KEY='my-secret'")

        # Step 2: 模型决定搜索敏感信息
        sub("Step 2: 模型返回 search SECRET_KEY")
        r2 = agent_e2e.tool_executor.execute("search", {"pattern": "SECRET", "path": "."})
        agent_e2e.record({
            "role": "tool", "name": "search",
            "args": {"pattern": "SECRET", "path": "."},
            "content": r2.content,
            "created_at": "2026-07-01T10:00:01+00:00",
        })
        show_result(r2)
        ok("搜索到 src/config.py 中的 SECRET_KEY")

        # Step 3: 模型尝试写文件修改（这会经过全部六层）
        sub("Step 3: 模型返回 write_file（经过六层安检）")
        r3 = agent_e2e.tool_executor.execute(
            "write_file",
            {"path": "src/config.py", "content": "DEBUG = True\nSECRET_KEY = '***REDACTED***'\n"}
        )
        show_result(r3)
        ok("write_file 通过全部六层 → 文件被修改")

        # Step 4: 验证
        sub("Step 4: 验证修改结果")
        r4 = agent_e2e.tool_executor.execute("read_file", {"path": "src/config.py", "start": 1, "end": 3})
        show_result(r4)
        ok("SECRET_KEY 已变为 '***REDACTED***'")

        print(f"\n    本次会话 history 共有 {len(agent_e2e.session['history'])} 条记录")

        # ═══════════════════════════════════════════════════════
        # 总结
        # ═══════════════════════════════════════════════════════

        hr("总结：工具安全与运行治理 完整架构")

        print("""
    ┌─────────────────────────────────────────────────────────────┐
    │              Page 工具安全与运行治理 全景图                    │
    ├─────────────────────────────────────────────────────────────┤
    │                                                             │
    │  ① 白名单         管理员控制 → tool_not_allowed               │
    │  ② 存在性         防模型幻觉 → unknown_tool                    │
    │  ③ 参数校验       核心安全   → invalid_arguments               │
    │     ├ 路径沙箱     resolve + commonpath 双重校验               │
    │     │              逃逸 → path_escape 安全事件                 │
    │     ├ 参数范围     timeout∈[1,120], start≥1, end≥start       │
    │     └ patch 精确   old_text 恰好出现 1 次 (str.count)         │
    │  ④ 防重复         最近 2 次相同 → repeated_identical_call      │
    │  ⑤ 审批           risky 工具  → approval_denied               │
    │     ├ auto         全部自动批准（默认）                        │
    │     ├ never        全部自动拒绝                               │
    │     ├ ask          input() 交互确认                          │
    │     └ read_only    模式 → 无条件拒绝所有写操作                 │
    │  ⑥ 快照对比       sha256 diff → partial_success 识别         │
    │                                                             │
    ├─────────────────────────────────────────────────────────────┤
    │  Security 模块 (security.py)                                 │
    │  ├ Secret 检测     正则扫描 API key 格式 (sk-/anth-/ollama-)  │
    │  ├ Shell 白名单    子进程只继承安全环境变量                    │
    │  └ 配置脱敏        .env 敏感值自动替换为 ***REDACTED***       │
    │                                                             │
    ├─────────────────────────────────────────────────────────────┤
    │  Metadata 系统                                               │
    │  └ ToolExecutionResult = content(给模型) + metadata(给系统)   │
    │     ├ tool_status:       ok / rejected / error / partial     │
    │     ├ tool_error_code:   精确到哪一层拦截                     │
    │     ├ security_event_type: path_escape / approval_denied     │
    │     ├ affected_paths:    被修改的文件列表                     │
    │     └ diff_summary:      created/modified/deleted           │
    │                                                             │
    └─────────────────────────────────────────────────────────────┘

    关键设计原则:
      ✦ 安全不能靠 prompt 约束，必须靠代码层硬拦截
      ✦ 每一层只检查一个风险维度，职责单一
      ✦ 顺序执行，第一层不通过就不会到第二层
      ✦ 每次拦截都返回精确的 error_code，确保可审计
      ✦ 内容 (content) 给模型看，元数据 (metadata) 给系统审计用
    """)


if __name__ == "__main__":
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  工具安全与运行治理 — 全部过程可视化演示                        ║")
    print("║  六层安检门 + Security 模块 + Metadata 系统                   ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    demo()

    print()
    print("=" * 68)
    print("  演示完毕。关注:")
    print("  [A] 六层安检门的执行顺序和拦截条件")
    print("  [B] Security 模块的脱敏、白名单、Secret 检测")
    print("  [C] Metadata 系统的统一格式")
    print("  [D] 综合场景中一次完整工具调用链的各层参与方式")
    print("=" * 68)
    print()
