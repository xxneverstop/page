from __future__ import annotations

import time

from core.models import ToolCall
from core.security import SecurityPolicy
from core.tools import ToolExecutor


def test_workspace_tools_read_search_write_and_edit(tmp_path):
    (tmp_path / "sample.txt").write_text("before\nneedle\n", encoding="utf-8")
    executor = ToolExecutor.for_workspace(
        tmp_path,
        policy=SecurityPolicy(tmp_path, allow_write=True, allow_shell=True),
    )

    read = executor.execute(ToolCall("read_file", {"path": "sample.txt"}, "r1"))
    assert read.ok and "needle" in read.output
    found = executor.execute(ToolCall("search", {"query": "needle"}, "s1"))
    assert found.ok and "sample.txt:2" in found.output
    written = executor.execute(ToolCall("write_file", {"path": "new.txt", "content": "old"}, "w1"))
    assert written.ok and (tmp_path / "new.txt").read_text(encoding="utf-8") == "old"
    edited = executor.execute(
        ToolCall("edit_file", {"path": "new.txt", "old": "old", "new": "new"}, "e1")
    )
    assert edited.ok and (tmp_path / "new.txt").read_text(encoding="utf-8") == "new"


def test_path_escape_and_approval_are_rejected(tmp_path):
    outside = tmp_path.parent / "outside-page-test.txt"
    executor = ToolExecutor.for_workspace(tmp_path)
    escaped = executor.execute(ToolCall("read_file", {"path": str(outside)}, "x1"))
    assert not escaped.ok and escaped.error.startswith("path_outside_workspace")
    denied = executor.execute(ToolCall("write_file", {"path": "x.txt", "content": "x"}, "x2"))
    assert not denied.ok and denied.error.startswith("approval_required")


def test_shell_keeps_nonzero_exit_as_result_and_bounds_output(tmp_path):
    policy = SecurityPolicy(tmp_path, allow_shell=True, max_output_chars=64)
    executor = ToolExecutor.for_workspace(tmp_path, policy=policy)
    result = executor.execute(ToolCall("run_shell", {"command": "python -c \"print('x'*200); raise SystemExit(3)\""}, "sh1"))
    # A non-zero exit is a failed tool observation, but remains in Session so
    # the model can repair the task and retry it.
    assert not result.ok
    assert result.exit_code == 3
    assert len(result.output) <= 64
    assert "truncated" in result.output


def test_shell_timeout_is_model_visible_failure(tmp_path):
    policy = SecurityPolicy(tmp_path, allow_shell=True, shell_timeout_seconds=0.1)
    executor = ToolExecutor.for_workspace(tmp_path, policy=policy)
    result = executor.execute(ToolCall("run_shell", {"command": "python -c \"import time; time.sleep(1)\""}, "sh2"))
    assert not result.ok
    assert result.error.startswith("shell_timeout")
