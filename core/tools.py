"""工具注册、工作区工具与串行执行。

执行器把失败保留为模型可见的 ``ToolResult``。测试或命令失败是下一轮
修复所需的反馈，不应静默终止整个任务。
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ToolCall, ToolResult, ToolSpec
from .security import SecurityError, SecurityPolicy, truncate_text


@dataclass
class ToolOutput:
    """需要暴露退出码的工具处理器使用的返回值。"""

    output: str = ""
    exit_code: int | None = None
    ok: bool = True


@dataclass
class RegisteredTool:
    spec: ToolSpec
    run: Callable[[dict[str, Any]], str | ToolOutput]


@dataclass
class ToolContext:
    workspace: Path
    policy: SecurityPolicy


class ToolExecutor:
    """一次校验并执行一个工具调用。

    ``context`` 可选，便于 FakeProvider 单测；Coding Agent 应使用
    :meth:`for_workspace` 获取带安全边界的标准工具集。
    """

    def __init__(
        self,
        tools: Iterable[RegisteredTool] | None = None,
        *,
        context: ToolContext | None = None,
    ):
        self.context = context
        self._tools = {item.spec.name: item for item in tools or []}

    @classmethod
    def for_workspace(
        cls,
        workspace: str | os.PathLike[str],
        *,
        policy: SecurityPolicy | None = None,
        approval: Callable[..., bool] | None = None,
    ) -> "ToolExecutor":
        """构建标准 read/search/write/edit/shell 工具集。"""

        root = Path(workspace).expanduser().resolve()
        tool_context = ToolContext(
            workspace=root,
            policy=policy or SecurityPolicy(root, approval=approval),
        )
        return cls(_workspace_tools(tool_context), context=tool_context)

    def register(self, tool: RegisteredTool) -> None:
        self._tools[tool.spec.name] = tool

    def specs(self) -> list[ToolSpec]:
        return [item.spec for item in self._tools.values()]

    def execute(self, call: ToolCall, *, context: ToolContext | None = None) -> ToolResult:
        started = time.monotonic()
        active_context = context or self.context
        item = self._tools.get(call.name)
        if item is None:
            return _result(call, False, error="unknown_tool", duration=_elapsed(started))
        try:
            output = item.run(call.arguments)
            if isinstance(output, ToolOutput):
                rendered = output.output
                if active_context is not None:
                    rendered = truncate_text(rendered, active_context.policy.max_output_chars)
                return _result(
                    call,
                    output.ok,
                    output=rendered,
                    exit_code=output.exit_code,
                    duration=_elapsed(started),
                )
            rendered = str(output)
            if active_context is not None:
                rendered = truncate_text(rendered, active_context.policy.max_output_chars)
            return _result(call, True, output=rendered, duration=_elapsed(started))
        except Exception as exc:  # 失败回填模型，不能留下孤立 call_id
            return _result(
                call,
                False,
                error=f"{_error_code(exc)}: {exc}",
                duration=_elapsed(started),
            )


def _result(
    call: ToolCall,
    ok: bool,
    *,
    output: str = "",
    error: str | None = None,
    exit_code: int | None = None,
    duration: int | None = None,
) -> ToolResult:
    return ToolResult(
        call_id=call.call_id,
        name=call.name,
        ok=ok,
        output=output,
        error=error,
        exit_code=exit_code,
        duration_ms=duration,
    )


def _elapsed(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _error_code(exc: Exception) -> str:
    if isinstance(exc, SecurityError):
        return exc.code
    if isinstance(exc, (KeyError, TypeError, ValueError)):
        return "invalid_arguments"
    return type(exc).__name__.lower()


def _workspace_tools(context: ToolContext) -> list[RegisteredTool]:
    return [
        RegisteredTool(
            ToolSpec("read_file", "Read a UTF-8 text file inside the workspace.", _schema({"path": "string"})),
            lambda args: _read_file(context, args),
        ),
        RegisteredTool(
            ToolSpec("search", "Search text in workspace files.", _schema({"query": "string"})),
            lambda args: _search(context, args),
        ),
        RegisteredTool(
            ToolSpec("write_file", "Write UTF-8 text to a workspace file.", _schema({"path": "string", "content": "string"})),
            lambda args: _write_file(context, args),
        ),
        RegisteredTool(
            ToolSpec("edit_file", "Replace text in a workspace file.", _schema({"path": "string", "old": "string", "new": "string"})),
            lambda args: _edit_file(context, args),
        ),
        RegisteredTool(
            ToolSpec("run_shell", "Run a bounded shell command in the workspace.", _schema({"command": "string"})),
            lambda args: _run_shell(context, args),
        ),
    ]


def _schema(properties: dict[str, str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {name: {"type": kind} for name, kind in properties.items()},
        "required": list(properties),
    }


def _arg(args: dict[str, Any], name: str, *, allow_empty: bool = False) -> Any:
    value = args.get(name)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"missing or invalid {name}")
    return value


def _read_file(context: ToolContext, args: dict[str, Any]) -> str:
    path = context.policy.resolve_path(_arg(args, "path"), must_exist=True)
    text = path.read_text(encoding="utf-8")
    start = args.get("start_line")
    end = args.get("end_line")
    if start is not None or end is not None:
        lines = text.splitlines()
        first = max(1, int(start or 1))
        last = min(len(lines), int(end or len(lines)))
        text = "\n".join(lines[first - 1 : last])
    return truncate_text(text, context.policy.max_output_chars)


def _search(context: ToolContext, args: dict[str, Any]) -> str:
    query = _arg(args, "query")
    root = context.policy.resolve_path(args.get("path", "."))
    if root.is_file():
        candidates = [root]
    else:
        pattern = str(args.get("glob", "**/*"))
        candidates = [item for item in root.glob(pattern) if item.is_file()]
    use_regex = bool(args.get("regex", False))
    case_sensitive = bool(args.get("case_sensitive", False))
    needle = query if case_sensitive else query.lower()
    max_results = max(1, min(int(args.get("max_results", 100)), 1000))
    hits: list[str] = []
    for path in candidates:
        if any(part in {".git", ".page", "__pycache__"} for part in path.parts):
            continue
        try:
            # 工作区内的符号链接可能指向外部，逐个文件再次校验最终路径。
            path = context.policy.resolve_path(path, must_exist=True)
        except SecurityError:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(lines, 1):
            haystack = line if case_sensitive else line.lower()
            match = re.search(query, line) if use_regex else needle in haystack
            if match:
                rel = path.relative_to(context.workspace)
                hits.append(f"{rel}:{number}: {line}")
                if len(hits) >= max_results:
                    return truncate_text("\n".join(hits), context.policy.max_output_chars)
    return truncate_text("\n".join(hits), context.policy.max_output_chars)


def _write_file(context: ToolContext, args: dict[str, Any]) -> str:
    path = context.policy.resolve_path(_arg(args, "path"))
    content = _arg(args, "content", allow_empty=True)
    context.policy.authorize("write_file", path=str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"wrote {path.relative_to(context.workspace)} ({len(content)} chars)"


def _edit_file(context: ToolContext, args: dict[str, Any]) -> str:
    path = context.policy.resolve_path(_arg(args, "path"), must_exist=True)
    old = _arg(args, "old", allow_empty=True)
    new = _arg(args, "new", allow_empty=True)
    context.policy.authorize("edit_file", path=str(path))
    text = path.read_text(encoding="utf-8")
    count = int(args.get("count", 1))
    if old not in text:
        raise ValueError("text_to_replace_not_found")
    updated = text.replace(old, new) if count == 0 else text.replace(old, new, count)
    path.write_text(updated, encoding="utf-8")
    return f"edited {path.relative_to(context.workspace)} ({text.count(old)} match(es))"


def _run_shell(context: ToolContext, args: dict[str, Any]) -> ToolOutput:
    command = _arg(args, "command")
    context.policy.authorize("run_shell", command=command)
    cwd = context.policy.resolve_path(args.get("cwd", "."))
    if not cwd.is_dir():
        raise ValueError("cwd_not_directory")
    timeout = min(float(args.get("timeout", context.policy.shell_timeout_seconds)), context.policy.shell_timeout_seconds)
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=context.policy.shell_environment(),
        shell=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=flags,
        start_new_session=os.name != "nt",
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_tree(process)
        stdout, stderr = process.communicate()
        output = _command_output(stdout or exc.stdout, stderr or exc.stderr)
        raise SecurityError("shell_timeout", f"command exceeded {timeout:g}s: {truncate_text(output, context.policy.max_output_chars)}")
    output = _command_output(stdout, stderr)
    return ToolOutput(
        truncate_text(output, context.policy.max_output_chars),
        process.returncode,
        process.returncode == 0,
    )


def _command_output(stdout: Any, stderr: Any) -> str:
    values = [value.decode(errors="replace") if isinstance(value, bytes) else str(value or "") for value in (stdout, stderr)]
    return "".join(values)


def _terminate_process_tree(process: subprocess.Popen) -> None:
    """超时后终止 Shell 及其子进程，避免临时工作区被锁定。"""

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        process.kill()
