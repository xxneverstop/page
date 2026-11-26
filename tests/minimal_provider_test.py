import json
from unittest.mock import patch

from core.models import ModelTurn
from core.provider import FakeProvider, OpenAICompatibleProvider


def test_fake_provider_model_error_is_explicit():
    turn = FakeProvider([ModelTurn(error="upstream unavailable")]).complete([], [])
    assert turn.is_error and turn.error == "upstream unavailable"


def test_openai_compatible_provider_parses_native_tool_call():
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            body = {
                "choices": [{
                    "message": {
                        "content": "",
                        "tool_calls": [{
                            "id": "c1",
                            "function": {"name": "read_file", "arguments": json.dumps({"path": "a.txt"})},
                        }],
                    },
                    "finish_reason": "tool_calls",
                }],
                "usage": {"total_tokens": 4},
            }
            return json.dumps(body).encode()

    with patch("urllib.request.urlopen", return_value=Response()):
        turn = OpenAICompatibleProvider("https://example.test", "secret", "model").complete([], [])
    assert turn.tool_calls[0].call_id == "c1"
    assert turn.tool_calls[0].arguments == {"path": "a.txt"}
    assert turn.usage["total_tokens"] == 4
