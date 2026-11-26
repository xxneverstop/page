"""Coding Agent 的工作区与副作用安全策略。"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class SecurityError(Exception):
    """策略拒绝或有界执行失败，并提供稳定错误码。"""

    def __init__(self, code: str, message: str | None = None):
        self.code = code
        super().__init__(message or code)


def truncate_text(text: str, limit: int) -> str:
    if limit < 1:
        return ""
    if len(text) <= limit:
        return text
    marker = f"\n...[truncated {len(text) - limit} chars]"
    if len(marker) >= limit:
        return text[:limit]
    keep = max(0, limit - len(marker))
    return text[:keep] + marker


@dataclass
class SecurityPolicy:
    workspace: Path
    allow_write: bool = False
    allow_shell: bool = False
    approval: Callable[..., bool] | None = None
    max_output_chars: int = 12_000
    shell_timeout_seconds: float = 30.0
    allowed_env: tuple[str, ...] = ("PATH", "PATHEXT", "SYSTEMROOT", "TEMP", "TMP", "PYTHONPATH")
    _root: Path = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._root = Path(self.workspace).expanduser().resolve()
        if not self._root.exists() or not self._root.is_dir():
            raise ValueError(f"workspace must be an existing directory: {self._root}")
        self.max_output_chars = max(1, int(self.max_output_chars))
        self.shell_timeout_seconds = max(0.1, float(self.shell_timeout_seconds))

    def resolve_path(self, value: str | os.PathLike[str], *, must_exist: bool = False) -> Path:
        raw = os.fspath(value)
        if "\x00" in raw:
            raise SecurityError("invalid_path", "path contains NUL")
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = self._root / candidate
        # 先跟随已有符号链接，再检查最终路径，防止通过链接逃出工作区。
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise SecurityError("path_outside_workspace", str(value)) from exc
        if must_exist and not resolved.exists():
            raise SecurityError("path_not_found", str(value))
        return resolved

    def authorize(self, action: str, **details: Any) -> None:
        allowed = self.allow_write if action in {"write_file", "edit_file"} else self.allow_shell if action == "run_shell" else True
        if allowed:
            return
        if self.approval is not None:
            try:
                approved = bool(self.approval(action, details))
            except TypeError:
                approved = bool(self.approval(action))
            if approved:
                return
        raise SecurityError("approval_required", action)

    def shell_environment(self) -> dict[str, str]:
        # 只传递运行命令所需的环境变量，避免把无关凭据暴露给 Shell。
        return {key: os.environ[key] for key in self.allowed_env if key in os.environ}
