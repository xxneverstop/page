"""Structured tool execution for the agent runtime."""

from dataclasses import dataclass
import re

from .action_journal import InjectedCrash
from .features import memory as memorylib
from .workspace import clip


@dataclass(frozen=True)
class ToolExecutionResult:
    content: str
    metadata: dict


def _metadata(
    tool_status,
    tool_error_code="",
    security_event_type="",
    risk_level="low",
    read_only=True,
    affected_paths=None,
    workspace_changed=False,
    workspace_fingerprint="",
    diff_summary=None,
):
    result = {
        "tool_status": tool_status,
        "tool_error_code": tool_error_code,
        "security_event_type": security_event_type,
        "risk_level": risk_level,
        "read_only": read_only,
        "affected_paths": list(affected_paths or []),
        "workspace_changed": bool(workspace_changed),
        "diff_summary": list(diff_summary or []),
    }
    if workspace_fingerprint:
        result["workspace_fingerprint"] = workspace_fingerprint
    return result


class ToolExecutor:
    def __init__(self, agent):
        self.agent = agent

    def execute(self, name, args):
        agent = self.agent
        if agent.allowed_tools is not None and name not in agent.allowed_tools:
            return ToolExecutionResult(
                content=f"error: tool '{name}' is not allowed in this run",
                metadata=_metadata(
                    "rejected",
                    tool_error_code="tool_not_allowed",
                    risk_level="high",
                    read_only=False,
                ),
            )

        tool = agent.tools.get(name)
        if tool is None:
            return ToolExecutionResult(
                content=f"error: unknown tool '{name}'",
                metadata=_metadata(
                    "rejected",
                    tool_error_code="unknown_tool",
                    risk_level="high",
                    read_only=False,
                ),
            )

        journaled = name in {"write_file", "patch_file", "run_shell"}
        preflight = agent.action_journal.preflight(name, args) if journaled else None
        if preflight and preflight["decision"] == "skip":
            record = dict(preflight.get("record") or {})
            return ToolExecutionResult(
                content=f"reconciled: action {preflight['action_id']} was already applied; skipped duplicate execution",
                metadata={
                    **_metadata(
                        "ok",
                        risk_level="high" if tool["risky"] else "low",
                        read_only=not tool["risky"],
                        affected_paths=record.get("affected_paths", []),
                        workspace_changed=False,
                        workspace_fingerprint=agent.workspace.fingerprint(),
                    ),
                    "action_id": preflight["action_id"],
                    "action_phase": record.get("phase", "reconciled"),
                    "recovery_action": "skipped_duplicate",
                },
            )
        if preflight and preflight["decision"] == "manual-review":
            record = dict(preflight.get("record") or {})
            return ToolExecutionResult(
                content=f"error: action {preflight['action_id']} requires manual review before retry",
                metadata={
                    **_metadata(
                        "rejected",
                        tool_error_code="manual_review_required",
                        security_event_type="uncertain_side_effect",
                        risk_level="high",
                        read_only=False,
                        affected_paths=record.get("affected_paths", []),
                    ),
                    "action_id": preflight["action_id"],
                    "action_phase": record.get("phase", "manual-review-required"),
                    "recovery_action": "manual_review",
                },
            )

        try:
            agent.validate_tool(name, args)
        except Exception as exc:
            example = agent.tool_example(name)
            message = f"error: invalid arguments for {name}: {exc}"
            if example:
                message += f"\nexample: {example}"
            security_event_type = "path_escape" if "path escapes workspace" in str(exc) else ""
            return ToolExecutionResult(
                content=message,
                metadata=_metadata(
                    "rejected",
                    tool_error_code="invalid_arguments",
                    security_event_type=security_event_type,
                    risk_level="high" if tool["risky"] else "low",
                    read_only=not tool["risky"],
                ),
            )

        if agent.repeated_tool_call(name, args):
            if name == "read_file":
                cached = next(
                    (
                        item.get("content", "")
                        for item in reversed(agent.session.get("history", []))
                        if item.get("role") == "tool" and item.get("name") == name and item.get("args") == args
                    ),
                    "",
                )
                if cached:
                    source_hash = memorylib.file_freshness(args.get("path", ""), agent.root)
                    return ToolExecutionResult(
                        content=(
                            "cached verified read; do not repeat the same read again. "
                            "Use the result below and return a final answer.\n" + str(cached)
                        ),
                        metadata={
                            **_metadata("ok", risk_level="low", read_only=True),
                            "deduplicated_read": True,
                            "recovery_action": "cached_read",
                            "source_path": agent.memory.canonical_path(args.get("path", "")),
                            "source_hash": source_hash,
                        },
                    )
            return ToolExecutionResult(
                content=f"error: repeated identical tool call for {name}; choose a different tool or return a final answer",
                metadata=_metadata(
                    "rejected",
                    tool_error_code="repeated_identical_call",
                    risk_level="high" if tool["risky"] else "low",
                    read_only=not tool["risky"],
                ),
            )

        if tool["risky"] and not agent.approve(name, args):
            return ToolExecutionResult(
                content=f"error: approval denied for {name}",
                metadata=_metadata(
                    "rejected",
                    tool_error_code="approval_denied",
                    security_event_type="read_only_block" if agent.read_only else "approval_denied",
                    risk_level="high",
                    read_only=False,
                ),
            )

        before_snapshot = agent.capture_workspace_snapshot() if tool["risky"] else {}
        after_snapshot = before_snapshot
        action_record = agent.action_journal.begin(name, args, agent.current_task_state) if journaled else None
        try:
            agent.maybe_inject_fault("before_tool_execution")
            content = clip(tool["run"](args))
            after_snapshot = agent.capture_workspace_snapshot() if tool["risky"] else before_snapshot
            affected_paths, diff_summary = agent.diff_workspace_snapshots(before_snapshot, after_snapshot)
            workspace_changed = bool(affected_paths)
            tool_status = "ok"
            tool_error_code = ""
            if name == "run_shell":
                match = re.search(r"exit_code:\s*(-?\d+)", content)
                exit_code = int(match.group(1)) if match else 0
                if exit_code != 0 and workspace_changed:
                    tool_status = "partial_success"
                    tool_error_code = "tool_partial_success"
                elif exit_code != 0:
                    tool_status = "error"
                    tool_error_code = "tool_failed"
            agent.maybe_inject_fault("after_tool_execution_before_commit")
            if action_record is not None:
                agent.action_journal.finish(action_record, tool_status, tool_error_code)
            agent.update_memory_after_tool(name, args, content)
            metadata = _metadata(
                tool_status,
                tool_error_code=tool_error_code,
                risk_level="high" if tool["risky"] else "low",
                read_only=not tool["risky"],
                affected_paths=affected_paths,
                workspace_changed=workspace_changed,
                workspace_fingerprint=agent.workspace.fingerprint(),
                diff_summary=diff_summary,
            )
            if action_record is not None:
                metadata.update(
                    {
                        "action_id": action_record["action_id"],
                        "action_phase": action_record["phase"],
                        "recovery_action": action_record.get("recovery_decision", ""),
                    }
                )
            if name == "read_file":
                metadata["source_path"] = agent.memory.canonical_path(args.get("path", ""))
                metadata["source_hash"] = memorylib.file_freshness(args.get("path", ""), agent.root)
            agent.record_process_note_for_tool(name, metadata)
            return ToolExecutionResult(content=content, metadata=metadata)
        except InjectedCrash:
            raise
        except Exception as exc:
            after_snapshot = agent.capture_workspace_snapshot() if tool["risky"] else before_snapshot
            affected_paths, diff_summary = agent.diff_workspace_snapshots(before_snapshot, after_snapshot)
            workspace_changed = bool(affected_paths)
            security_event_type = "path_escape" if "path escapes workspace" in str(exc) else ""
            metadata = _metadata(
                "partial_success" if workspace_changed else "error",
                tool_error_code="tool_partial_success" if workspace_changed else "tool_failed",
                security_event_type=security_event_type,
                risk_level="high" if tool["risky"] else "low",
                read_only=not tool["risky"],
                affected_paths=affected_paths,
                workspace_changed=workspace_changed,
                workspace_fingerprint=agent.workspace.fingerprint(),
                diff_summary=diff_summary,
            )
            if action_record is not None:
                agent.action_journal.finish(action_record, metadata["tool_status"], metadata["tool_error_code"])
                metadata.update(
                    {
                        "action_id": action_record["action_id"],
                        "action_phase": action_record["phase"],
                        "recovery_action": action_record.get("recovery_decision", ""),
                    }
                )
            agent.record_process_note_for_tool(name, metadata)
            return ToolExecutionResult(content=f"error: tool {name} failed: {exc}", metadata=metadata)
