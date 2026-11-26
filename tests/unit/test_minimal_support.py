import json

from core.evaluation import EvaluationTask, evaluate, summarize
from core.observability import RunArtifacts, TraceWriter, ViewerTraceAdapter
from core.recovery import ActionJournal, Checkpoint, CheckpointStore, make_resume_decision
from core.skills import SkillStore, render_skill_context


def test_trace_writer_writes_viewer_artifacts(tmp_path):
    artifacts = RunArtifacts.create(tmp_path / ".page" / "runs", "run_test")
    writer = TraceWriter(artifacts)
    writer.emit("run_started", user_request="read")
    writer.emit("turn_start", turn_id="turn_1")
    writer.emit("tool_end", tool_call_id="call_1", ok=True)
    writer.finish(status="completed", stop_reason="final")

    lines = [json.loads(line) for line in artifacts.trace_path.read_text(encoding="utf-8").splitlines()]
    assert lines[-1]["event"] == "agent_end"
    assert ViewerTraceAdapter().adapt(lines[0])["schema_version"] == "page-trace-v2"
    assert json.loads(artifacts.state_path.read_text(encoding="utf-8"))["status"] == "completed"


def test_skill_store_loads_body_on_selection(tmp_path):
    path = tmp_path / "skills" / "demo"
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text("name: demo\ndescription: test\n\nDo the thing.\n", encoding="utf-8")
    store = SkillStore(tmp_path / "skills")
    metadata = store.discover()
    assert metadata[0].name == "demo"
    assert metadata[0].description == "test"
    assert "Do the thing" in render_skill_context(store.select(["demo"]))


def test_recovery_uses_independent_call_identity(tmp_path):
    journal = ActionJournal(tmp_path / "journal.jsonl")
    first = journal.append(tool="write_file", args={"path": "a"}, status="applied")
    second = journal.append(tool="write_file", args={"path": "a"}, status="unknown")
    assert first != second
    assert make_resume_decision(journal)["can_resume"] is False

    checkpoint_path = tmp_path / "checkpoint.json"
    CheckpointStore(checkpoint_path).save(Checkpoint("s", "running", 2, 1))
    assert CheckpointStore(checkpoint_path).load().turn_count == 2


def test_evaluation_distinguishes_agent_completion_from_verifier():
    task = EvaluationTask("t", "fix", verifier=lambda: False)
    result = evaluate(task, lambda prompt: {"status": "completed", "tool_count": 1})
    report = summarize([result])
    assert report["agent_completed"] == 1
    assert report["verifier_passed"] == 0

