"""Durable tool-action journal and deterministic resume reconciliation.

The journal deliberately covers file mutations first.  It is not a general
distributed transaction log and it never claims that arbitrary shell commands
are safe to replay.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .workspace import now


JOURNAL_SCHEMA_VERSION = "action-journal-v1"
PHASE_PLANNED = "planned"
PHASE_STARTED = "started"
PHASE_SUCCEEDED = "succeeded"
PHASE_FAILED = "failed"
PHASE_RECONCILED = "reconciled"
PHASE_MANUAL_REVIEW = "manual-review-required"
FILE_MUTATION_TOOLS = {"write_file", "patch_file"}


class InjectedCrash(RuntimeError):
    """Raised only by explicit test/demo fault injection."""


def _digest_bytes(value):
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _digest_text(value):
    return _digest_bytes(str(value).encode("utf-8"))


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _file_state(path):
    path = Path(path)
    if not path.exists():
        return "missing"
    if not path.is_file():
        return "not-a-file"
    try:
        return _digest_bytes(path.read_bytes())
    except OSError:
        return "unreadable"


class ActionJournal:
    def __init__(self, agent):
        self.agent = agent
        journal = agent.session.setdefault("action_journal", {})
        if not isinstance(journal, dict):
            journal = {}
            agent.session["action_journal"] = journal
        journal.setdefault("schema_version", JOURNAL_SCHEMA_VERSION)
        journal.setdefault("items", {})

    @property
    def state(self):
        return self.agent.session["action_journal"]

    def _save(self):
        self.agent.session_path = self.agent.session_store.save(self.agent.session)

    def normalize_args(self, name, args):
        normalized = dict(args or {})
        if "path" in normalized:
            normalized["path"] = self.agent.memory.canonical_path(normalized["path"])
        if name == "run_shell" and "command" in normalized:
            normalized["command"] = str(normalized["command"]).strip()
        return normalized

    def action_id(self, name, args):
        normalized = self.normalize_args(name, args)
        payload = {
            "session_id": self.agent.session.get("id", ""),
            "tool_name": str(name),
            "args": normalized,
        }
        return "act_" + hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:16]

    def _paths(self, name, args):
        if name not in FILE_MUTATION_TOOLS:
            return []
        raw_path = str((args or {}).get("path", "")).strip()
        if not raw_path:
            return []
        return [self.agent.memory.canonical_path(raw_path)]

    def _states(self, paths):
        return {path: _file_state(self.agent.path(path)) for path in paths}

    def _expected_after(self, name, args):
        paths = self._paths(name, args)
        if not paths:
            return {}
        path = self.agent.path(paths[0])
        if name == "write_file":
            return {paths[0]: _digest_text(str(args.get("content", "")))}
        if name == "patch_file" and path.is_file():
            text = path.read_text(encoding="utf-8")
            old_text = str(args.get("old_text", ""))
            new_text = str(args.get("new_text", ""))
            if old_text and text.count(old_text) == 1:
                return {paths[0]: _digest_text(text.replace(old_text, new_text, 1))}
        return {}

    @staticmethod
    def _states_match(expected, current):
        return bool(expected) and all(current.get(path) == value for path, value in expected.items())

    def get(self, action_id):
        return self.state.get("items", {}).get(str(action_id))

    def preflight(self, name, args):
        action_id = self.action_id(name, args)
        record = self.get(action_id)
        global_decision = dict(getattr(self.agent, "recovery_decision", {}) or {})
        if self.agent.resume_mode == "guarded" and global_decision.get("decision") == "refuse":
            return {"decision": "manual-review", "action_id": action_id, "record": record or {}}
        if self.agent.resume_mode == "blind" or record is None:
            return {"decision": "execute", "action_id": action_id, "record": record}

        record = self.reconcile_record(record, persist=True)
        decision = str(record.get("recovery_decision", ""))
        if decision == "skip":
            return {"decision": "skip", "action_id": action_id, "record": record}
        if decision == "retry":
            return {"decision": "execute", "action_id": action_id, "record": record}
        if decision in {"manual-review", "refuse"}:
            return {"decision": "manual-review", "action_id": action_id, "record": record}
        return {"decision": "execute", "action_id": action_id, "record": record}

    def begin(self, name, args, task_state):
        action_id = self.action_id(name, args)
        normalized_args = self.normalize_args(name, args)
        paths = self._paths(name, normalized_args)
        existing = self.get(action_id) or {}
        record = {
            **existing,
            "action_id": action_id,
            "run_id": task_state.run_id if task_state is not None else "",
            "task_id": task_state.task_id if task_state is not None else "",
            "checkpoint_id": task_state.checkpoint_id if task_state is not None else "",
            "tool_name": str(name),
            "arguments_digest": _digest_text(_canonical_json(normalized_args)),
            "affected_paths": paths,
            "before_hashes": self._states(paths),
            "expected_after_hashes": self._expected_after(name, normalized_args),
            "after_hashes": {},
            "expected_postcondition": "file_hash_match" if name in FILE_MUTATION_TOOLS else "unknown_side_effect",
            "automatic_recovery": name in FILE_MUTATION_TOOLS,
            "execution_count": int(existing.get("execution_count", 0)) + 1,
            "phase": PHASE_PLANNED,
            "error_code": "",
            "started_at": now(),
            "finished_at": "",
            "recovery_decision": "",
            "decision_reason": "",
        }
        self.state["items"][action_id] = record
        self._save()
        record["phase"] = PHASE_STARTED
        self._save()
        return record

    def finish(self, record, tool_status, error_code=""):
        paths = list(record.get("affected_paths", []))
        record["after_hashes"] = self._states(paths)
        record["error_code"] = str(error_code or "")
        record["finished_at"] = now()
        if tool_status == "ok":
            record["phase"] = PHASE_SUCCEEDED
            record["recovery_decision"] = "skip"
            record["decision_reason"] = "tool completed and post-state was persisted"
        else:
            record["phase"] = PHASE_FAILED
            record["recovery_decision"] = "manual-review" if record.get("tool_name") == "run_shell" else "retry"
            record["decision_reason"] = "tool did not complete successfully"
        self._save()
        return record

    def reconcile_record(self, record, persist=False):
        phase = str(record.get("phase", ""))
        paths = list(record.get("affected_paths", []))
        current = self._states(paths)
        before = dict(record.get("before_hashes", {}))
        expected_after = dict(record.get("expected_after_hashes", {}))
        tool_name = str(record.get("tool_name", ""))

        if tool_name == "run_shell" and phase in {PHASE_PLANNED, PHASE_STARTED}:
            record["phase"] = PHASE_MANUAL_REVIEW
            record["recovery_decision"] = "manual-review"
            record["decision_reason"] = "shell side effects cannot be proven safe to replay"
        elif phase in {PHASE_SUCCEEDED, PHASE_RECONCILED}:
            if self._states_match(record.get("after_hashes", {}) or expected_after, current):
                record["recovery_decision"] = "skip"
                record["decision_reason"] = "persisted post-state matches workspace"
            else:
                record["phase"] = PHASE_MANUAL_REVIEW
                record["recovery_decision"] = "manual-review"
                record["decision_reason"] = "workspace no longer matches the completed action"
        elif phase in {PHASE_PLANNED, PHASE_STARTED}:
            if self._states_match(expected_after, current):
                record["phase"] = PHASE_RECONCILED
                record["after_hashes"] = current
                record["finished_at"] = now()
                record["recovery_decision"] = "skip"
                record["decision_reason"] = "postcondition already holds after interrupted persistence"
            elif not paths or self._states_match(before, current):
                record["recovery_decision"] = "retry"
                record["decision_reason"] = "workspace still matches the pre-action state"
            else:
                record["phase"] = PHASE_MANUAL_REVIEW
                record["recovery_decision"] = "manual-review"
                record["decision_reason"] = "workspace matches neither pre-state nor expected post-state"
        elif phase == PHASE_FAILED:
            if paths and self._states_match(before, current):
                record["recovery_decision"] = "retry"
                record["decision_reason"] = "failed action left the workspace unchanged"
            else:
                record["recovery_decision"] = "manual-review"
                record["decision_reason"] = "failed action may have left partial side effects"
        elif phase == PHASE_MANUAL_REVIEW:
            record["recovery_decision"] = "manual-review"
            record.setdefault("decision_reason", "manual review is required")

        record["observed_hashes"] = current
        if persist:
            self._save()
        return record

    def reconcile_all(self, resume_status=""):
        if self.state.get("schema_version") != JOURNAL_SCHEMA_VERSION:
            result = {
                "mode": "guarded_resume",
                "decision": "refuse",
                "reason": "action journal schema mismatch",
                "resume_status": str(resume_status),
                "skipped_actions": [],
                "reconciled_actions": [],
                "retryable_actions": [],
                "manual_review_actions": list(self.state.get("items", {}).keys()),
            }
            self.agent.session["recovery_decision"] = result
            self._save()
            return result
        if self.agent.resume_mode == "blind":
            result = {
                "mode": "blind_resume",
                "decision": "continue-without-reconciliation",
                "reason": "benchmark baseline intentionally bypasses safeguards",
                "skipped_actions": [],
                "reconciled_actions": [],
                "retryable_actions": [],
                "manual_review_actions": [],
            }
            self.agent.session["recovery_decision"] = result
            self._save()
            return result

        skipped = []
        reconciled = []
        retryable = []
        manual = []
        for action_id, record in self.state.get("items", {}).items():
            before_phase = str(record.get("phase", ""))
            self.reconcile_record(record)
            decision = str(record.get("recovery_decision", ""))
            if decision == "skip":
                skipped.append(action_id)
            if before_phase != PHASE_RECONCILED and record.get("phase") == PHASE_RECONCILED:
                reconciled.append(action_id)
            if decision == "retry":
                retryable.append(action_id)
            if decision == "manual-review":
                manual.append(action_id)

        incompatible = str(resume_status) in {"workspace-mismatch", "schema-mismatch"}
        decision = "refuse" if incompatible or manual else "continue"
        reason = "runtime identity or checkpoint schema mismatch" if incompatible else (
            "one or more actions require manual review" if manual else "journal and workspace are consistent"
        )
        result = {
            "mode": "guarded_resume",
            "decision": decision,
            "reason": reason,
            "resume_status": str(resume_status),
            "skipped_actions": skipped,
            "reconciled_actions": reconciled,
            "retryable_actions": retryable,
            "manual_review_actions": manual,
        }
        self.agent.session["recovery_decision"] = result
        self._save()
        return result

    def summary(self):
        items = list(self.state.get("items", {}).values())
        counts = {}
        for item in items:
            phase = str(item.get("phase", "unknown"))
            counts[phase] = counts.get(phase, 0) + 1
        return {
            "schema_version": self.state.get("schema_version", ""),
            "action_count": len(items),
            "phase_counts": counts,
            "items": items,
        }
