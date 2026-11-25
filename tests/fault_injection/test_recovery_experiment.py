from page.evaluation.recovery_experiment import run_recovery_experiment


def test_recovery_experiment_compares_blind_and_guarded_modes(tmp_path):
    artifact = run_recovery_experiment(
        artifact_path=tmp_path / "recovery.json",
        repetitions=1,
    )

    assert artifact["task_runs"] == 6
    assert artifact["variants"]["guarded_resume"]["verifier_pass_rate"] == 1.0
    assert artifact["variants"]["guarded_resume"]["skipped_duplicate_actions"] == 2
    assert artifact["variants"]["guarded_resume"]["journal_execution_count"] < artifact["variants"]["blind_resume"]["journal_execution_count"]
    stale_row = next(
        row
        for row in artifact["rows"]
        if row["variant"] == "guarded_resume" and row["task_id"] == "stale_file_drift"
    )
    assert stale_row["stale_summary_invalidations"] >= 1
