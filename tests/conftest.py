import os
import re
import tempfile
from pathlib import Path

import pytest


SLOW_TEST_NAMES = {
    "test_run_fixed_benchmark_uses_fresh_fixture_copy_and_fresh_run_directory",
    "test_run_fixed_benchmark_reports_metadata_and_success_definition",
    "test_run_fixed_benchmark_covers_recovery_and_durable_contract_rows",
    "test_run_harness_regression_v2_writes_named_artifact",
    "test_run_context_ablation_v2_writes_expected_artifact",
    "test_run_memory_ablation_v2_writes_expected_artifact",
    "test_run_recovery_ablation_v2_writes_expected_artifact",
    "test_write_benchmark_core_report_marks_resume_safe_metrics",
    "test_recovery_experiment_compares_blind_and_guarded_modes",
    "test_run_task_anchors_paths_to_fixture_copy_even_inside_repo_workspace",
    "test_delegate_child_is_read_only",
    "test_agent_only_stores_reusable_epistemic_notes",
    "test_agent_retries_after_malformed_tool_payload",
    "test_delegate_uses_child_agent",
    "test_retries_do_not_consume_the_whole_budget",
    "test_prompt_metadata_refreshes_prefix_when_workspace_changes",
    "test_explicit_memory_promotion_supersedes_matching_durable_fact",
    "test_resume_records_runtime_identity_mismatch_fields_in_metadata_and_trace",
    "test_agent_saves_and_resumes_session",
    "test_resume_marks_no_checkpoint_when_session_has_no_checkpoint_state",
    "test_agent_runs_tool_then_final",
    "test_explicit_memory_promotion_dedupes_duplicate_durable_note",
    "test_agent_loop_runs_same_control_flow_as_pico_ask",
    "test_resume_prompt_uses_checkpoint_state_not_just_history",
    "test_successful_run_persists_run_artifacts_and_stop_reason",
    "test_agent_retries_after_empty_model_output",
    "test_resume_marks_workspace_mismatch_when_checkpoint_runtime_identity_is_stale",
    "test_agent_accepts_xml_write_file_tool",
}


def _effective_user_name():
    """Return the OS account behind the current process, not a masked env var."""
    if os.name == "nt":
        import ctypes

        buffer = ctypes.create_unicode_buffer(256)
        size = ctypes.c_ulong(len(buffer))
        if ctypes.windll.advapi32.GetUserNameW(buffer, ctypes.byref(size)):
            return buffer.value
    return os.environ.get("USERNAME") or os.environ.get("USER") or "local"


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    """Keep pytest temp roots isolated across Windows user identities.

    Codex sandbox runs and interactive Windows runs use different accounts. If
    both rely on pytest's shared ``%TEMP%\\pytest-of-<name>`` directory, the
    first account can leave an ACL that denies the other account. A per-user
    directory under the system temp root avoids that cross-account collision.
    It must stay outside the repository so workspace discovery cannot inherit
    the real project's ``.git`` directory or ``.env`` configuration.
    """
    if config.getoption("basetemp") is not None:
        return
    identity = _effective_user_name()
    safe_identity = re.sub(r"[^A-Za-z0-9_.-]+", "_", identity).strip("._") or "local"
    config.option.basetemp = str(Path(tempfile.gettempdir()) / f"page-pytest-{safe_identity}")


def pytest_collection_modifyitems(items):
    slow = pytest.mark.slow
    for item in items:
        if item.name in SLOW_TEST_NAMES:
            item.add_marker(slow)
