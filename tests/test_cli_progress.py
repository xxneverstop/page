import io
import time

from page.cli import _Spinner, _ask_with_progress


class _TerminalBuffer(io.StringIO):
    def isatty(self):
        return True


def test_spinner_animates_and_clears_the_status_line():
    stream = _TerminalBuffer()

    with _Spinner("Working", stream=stream, interval=0.001):
        time.sleep(0.006)

    output = stream.getvalue()
    assert "Working" in output
    assert output.count("\r") >= 2
    assert output.endswith("\r\033[2K")


def test_ask_with_progress_returns_the_agent_response(monkeypatch):
    events = []

    class FakeSpinner:
        def __enter__(self):
            events.append("start")

        def __exit__(self, exc_type, exc, traceback):
            events.append("stop")

    class FakeAgent:
        def ask(self, prompt):
            events.append(prompt)
            return "done"

    monkeypatch.setattr("page.cli._Spinner", FakeSpinner)

    assert _ask_with_progress(FakeAgent(), "inspect") == "done"
    assert events == ["start", "inspect", "stop"]
