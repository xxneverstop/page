import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "name,required,paths",
    [
        (
            "run_provider_experiments",
            ["--output-json", "result.json"],
            {
                "benchmark_path": "benchmarks/coding_tasks.json",
                "workspace_root": "artifacts/provider-workspaces",
                "artifact_root": "artifacts/provider-artifacts",
            },
        ),
        (
            "run_step_budget_experiment",
            ["--output-json", "result.json"],
            {
                "benchmark_path": "benchmarks/coding_tasks.json",
                "workspace_root": "artifacts/step-budget-workspaces",
            },
        ),
        (
            "run_large_scale_experiments",
            [
                "--benchmark-artifact", "benchmark.json",
                "--runs-root", "runs",
                "--provider-output-json", "provider.json",
                "--resume-output-json", "resume.json",
                "--resume-output-markdown", "resume.md",
                "--memory-output-json", "memory.json",
                "--context-output-json", "context.json",
                "--security-output-json", "security.json",
                "--final-report-markdown", "report.md",
            ],
            {
                "provider_benchmark_path": "benchmarks/coding_tasks.json",
                "provider_workspace_root": "artifacts/provider-workspaces",
                "provider_artifact_root": "artifacts/provider-artifacts",
            },
        ),
    ],
)
def test_default_paths_use_project_root_and_explicit_paths_use_cwd(tmp_path, monkeypatch, name, required, paths):
    monkeypatch.chdir(tmp_path)
    parser = load_script(name).build_arg_parser()
    defaults = parser.parse_args(required)
    for attribute, relative in paths.items():
        assert Path(getattr(defaults, attribute)) == ROOT / relative
    explicit_args = list(required)
    for attribute in paths:
        explicit_args.extend(["--" + attribute.replace("_", "-"), "custom/input"])
    explicit = parser.parse_args(explicit_args)
    for attribute in paths:
        assert Path(getattr(explicit, attribute)).resolve() == tmp_path / "custom/input"


def test_recovery_demo_paths_work_outside_project_without_running_models(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    script = load_script("interview_demo")
    recorded = []

    def fake_run(**kwargs):
        recorded.append(kwargs["artifact_path"])
        return {"model": "fake", "task_runs": 0, "variants": {}}

    monkeypatch.setattr(script, "run_recovery_experiment", fake_run)
    assert script.main([]) == 0
    assert recorded[-1] == ROOT / "artifacts/interview-recovery-fake.json"
    assert script.DEFAULT_DEEPSEEK_ARTIFACT == ROOT / "artifacts/interview-recovery-deepseek.json"
    assert script.main(["--output", "custom.json"]) == 0
    assert recorded[-1] == Path("custom.json")
    capsys.readouterr()

    archived = tmp_path / "archived.json"
    archived.write_text(json.dumps({"model": "fake", "task_runs": 1, "variants": {}}), encoding="utf-8")
    assert script.main(["--show-latest", "--output", str(archived)]) == 0
    assert len(recorded) == 2
    assert json.loads(capsys.readouterr().out)["task_runs"] == 1


@pytest.mark.parametrize(
    "name",
    [
        "run_provider_experiments",
        "run_large_scale_experiments",
        "collect_resume_metrics",
        "run_step_budget_experiment",
        "interview_demo",
    ],
)
def test_script_help_works_outside_project(tmp_path, name):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / f"{name}.py"), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()
