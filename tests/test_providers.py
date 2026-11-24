import io
import json
from unittest.mock import patch
import urllib.error

import pytest

from page import AnthropicCompatibleModelClient, OllamaModelClient, OpenAICompatibleModelClient


def test_ollama_client_posts_expected_payload():
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"response": "<final>ok</final>"}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    client = OllamaModelClient(
        model="qwen3.5:4b",
        host="http://127.0.0.1:11434",
        temperature=0.2,
        top_p=0.9,
        timeout=30,
    )

    with patch("urllib.request.urlopen", fake_urlopen):
        result = client.complete("hello", 42)

    assert result == "<final>ok</final>"
    assert captured["url"] == "http://127.0.0.1:11434/api/generate"
    assert captured["timeout"] == 30
    assert captured["body"]["model"] == "qwen3.5:4b"
    assert captured["body"]["prompt"] == "hello"
    assert captured["body"]["stream"] is False


def test_openai_compatible_client_posts_expected_responses_payload():
    captured = {}

    class FakeResponse:
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"output_text": "<final>ok</final>"}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    client = OpenAICompatibleModelClient(
        model="right.codes/codex-mini",
        base_url="https://right.codes/v1",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
    )

    with patch("urllib.request.urlopen", fake_urlopen):
        result = client.complete("hello", 42)

    assert result == "<final>ok</final>"
    assert captured["url"] == "https://right.codes/v1/responses"
    assert captured["timeout"] == 30
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["headers"]["Content-type"] == "application/json"
    assert captured["headers"]["Accept"] == "application/json"
    assert captured["headers"]["User-agent"] == "page/0.1"
    assert captured["body"] == {
        "model": "right.codes/codex-mini",
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "hello",
                    }
                ],
            }
        ],
        "max_output_tokens": 42,
        "stream": False,
        "temperature": 0.2,
    }


def test_openai_compatible_client_sends_prompt_cache_fields_and_records_usage():
    captured = {}

    class FakeResponse:
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "output_text": "<final>ok</final>",
                    "usage": {
                        "input_tokens": 2048,
                        "input_tokens_details": {"cached_tokens": 1536},
                        "output_tokens": 32,
                        "total_tokens": 2080,
                    },
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    client = OpenAICompatibleModelClient(
        model="right.codes/codex-mini",
        base_url="https://right.codes/v1",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
    )

    with patch("urllib.request.urlopen", fake_urlopen):
        result = client.complete(
            "hello",
            42,
            prompt_cache_key="prefix-hash-123",
            prompt_cache_retention="in_memory",
        )

    assert result == "<final>ok</final>"
    assert captured["body"]["prompt_cache_key"] == "prefix-hash-123"
    assert captured["body"]["prompt_cache_retention"] == "in_memory"
    assert client.last_completion_metadata["prompt_cache_supported"] is True
    assert client.last_completion_metadata["cached_tokens"] == 1536
    assert client.last_completion_metadata["cache_hit"] is True
    assert client.last_completion_metadata["input_tokens"] == 2048


def test_openai_compatible_client_extracts_text_from_event_stream():
    class FakeResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return (
                'data: {"type":"response.created","response":{"id":"resp_1","output":[]}}\n'
                'data: {"type":"response.completed","response":{"output":[{"content":[{"text":"<final>stream ok</final>"}]}]}}\n'
                "data: [DONE]\n"
            ).encode("utf-8")

    client = OpenAICompatibleModelClient(
        model="right.codes/codex-mini",
        base_url="https://right.codes/v1",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
    )

    with patch("urllib.request.urlopen", return_value=FakeResponse()):
        result = client.complete("hello", 42)

    assert result == "<final>stream ok</final>"


def test_openai_compatible_client_extracts_text_from_event_stream_deltas():
    class FakeResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return (
                'event: response.output_text.delta\n'
                'data: {"type":"response.output_text.delta","delta":"<final>"}\n'
                'event: response.output_text.delta\n'
                'data: {"type":"response.output_text.delta","delta":"OK"}\n'
                'event: response.output_text.done\n'
                'data: {"type":"response.output_text.done","text":"<final>OK</final>"}\n'
                "data: [DONE]\n"
            ).encode("utf-8")

    client = OpenAICompatibleModelClient(
        model="right.codes/codex-mini",
        base_url="https://right.codes/v1",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
    )

    with patch("urllib.request.urlopen", return_value=FakeResponse()):
        result = client.complete("hello", 42)

    assert result == "<final>OK</final>"


def test_anthropic_compatible_client_posts_expected_messages_payload():
    captured = {}

    class FakeResponse:
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "content": [
                        {
                            "type": "text",
                            "text": "<final>ok</final>",
                        }
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    client = AnthropicCompatibleModelClient(
        model="claude-sonnet-4-5-20250929",
        base_url="https://www.right.codes/claude-aws/v1",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
    )

    with patch("urllib.request.urlopen", fake_urlopen):
        result = client.complete("hello", 42)

    assert result == "<final>ok</final>"
    assert captured["url"] == "https://www.right.codes/claude-aws/v1/messages"
    assert captured["timeout"] == 30
    assert captured["headers"]["X-api-key"] == "sk-test"
    assert captured["headers"]["Anthropic-version"] == "2023-06-01"
    assert captured["headers"]["Content-type"] == "application/json"
    assert captured["body"] == {
        "model": "claude-sonnet-4-5-20250929",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "hello",
                    }
                ],
            }
        ],
        "max_tokens": 42,
        "stream": False,
        "temperature": 0.2,
    }


def test_anthropic_compatible_client_extracts_first_text_block():
    class FakeResponse:
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "content": [
                        {"type": "thinking", "thinking": "hidden"},
                        {"type": "text", "text": "<final>ok</final>"},
                    ]
                }
            ).encode("utf-8")

    client = AnthropicCompatibleModelClient(
        model="claude-sonnet-4-5-20250929",
        base_url="https://www.right.codes/claude-aws/v1",
        api_key="sk-test",
        temperature=0.2,
        timeout=30,
    )

    with patch("urllib.request.urlopen", return_value=FakeResponse()):
        result = client.complete("hello", 42)

    assert result == "<final>ok</final>"


@pytest.fixture(params=("ollama", "openai", "anthropic"))
def http_trace_client(request):
    base_url = "https://trace-user:trace-password@example.test"
    if request.param == "ollama":
        return OllamaModelClient("test-model", base_url, 0.0, 1.0, 30)
    client_class = OpenAICompatibleModelClient if request.param == "openai" else AnthropicCompatibleModelClient
    return client_class("test-model", base_url, "trace-api-key", 0.0, 30)


class _TraceResponse(io.BytesIO):
    status = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, body):
        super().__init__(body.encode("utf-8"))
        self.read_count = 0

    def read(self):
        self.read_count += 1
        return super().read()


def test_http_trace_records_actual_body_once_without_credentials(http_trace_client):
    body = json.dumps(
        {
            "response": "<final>中文</final>",
            "output_text": "<final>中文</final>",
            "content": [{"type": "text", "text": "<final>中文</final>"}],
        },
        ensure_ascii=False,
    )
    response = _TraceResponse(body)
    events = []
    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        result = http_trace_client.complete("hello", 42, trace_callback=lambda name, data: events.append((name, data)))

    assert http_trace_client.supports_http_trace is True
    assert result == "<final>中文</final>"
    assert response.read_count == 1
    assert [name for name, _ in events] == ["model_http_request", "model_http_response"]
    request_event, response_event = [data for _, data in events]
    actual_request = urlopen.call_args.args[0]
    assert request_event["body"] == json.loads(actual_request.data)
    assert response_event["body"] == body
    assert response_event["status"] == 200
    assert all(data["attempt"] == 1 for _, data in events)
    assert all(data["url"].startswith("https://example.test/") for _, data in events)
    # 日志只采集正文和去掉 userinfo 的 URL，不采集认证头。
    serialized = json.dumps(events)
    assert "trace-user" not in serialized
    assert "trace-password" not in serialized
    assert "trace-api-key" not in serialized
    assert "headers" not in serialized


def test_http_trace_records_http_error_body_before_raising(http_trace_client):
    body = '{"error": "rate limited"}'
    response = _TraceResponse(body)
    error = urllib.error.HTTPError("https://example.test", 429, "Too Many Requests", {}, response)
    events = []
    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(RuntimeError, match="HTTP 429"):
            http_trace_client.complete("hello", 42, trace_callback=lambda name, data: events.append((name, data)))

    assert response.read_count == 1
    assert [name for name, _ in events] == ["model_http_request", "model_http_response"]
    assert events[1][1]["status"] == 429
    assert events[1][1]["body"] == body


def test_http_trace_records_each_connection_attempt_without_changing_retries(http_trace_client):
    events = []
    attempts = 1 if isinstance(http_trace_client, OllamaModelClient) else 3
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")) as urlopen:
        with patch("page.providers.clients.time.sleep"):
            with pytest.raises(RuntimeError, match="Could not reach"):
                http_trace_client.complete("hello", 42, trace_callback=lambda name, data: events.append((name, data)))

    assert urlopen.call_count == attempts
    assert [name for name, _ in events] == ["model_http_request", "model_http_error"] * attempts
    assert [data["attempt"] for name, data in events if name == "model_http_request"] == list(range(1, attempts + 1))
    assert all(data["error"] == "<urlopen error offline>" for name, data in events if name == "model_http_error")


def test_http_trace_preserves_timeout_exception_without_extra_retries(http_trace_client):
    events = []
    with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")) as urlopen:
        with pytest.raises(TimeoutError, match="timed out"):
            http_trace_client.complete("hello", 42, trace_callback=lambda name, data: events.append((name, data)))

    assert urlopen.call_count == 1
    assert [name for name, _ in events] == ["model_http_request", "model_http_error"]


def test_openai_http_trace_keeps_raw_sse_body():
    body = 'data: {"type":"response.output_text.done","text":"<final>ok</final>"}\n\ndata: [DONE]\n'
    response = _TraceResponse(body)
    response.headers = {"Content-Type": "text/event-stream"}
    client = OpenAICompatibleModelClient("test-model", "https://example.test", "test-key", 0.0, 30)
    events = []
    with patch("urllib.request.urlopen", return_value=response):
        result = client.complete("hello", 42, trace_callback=lambda name, data: events.append((name, data)))

    assert result == "<final>ok</final>"
    assert response.read_count == 1
    assert events[1][1]["body"] == body


def test_anthropic_http_trace_includes_retried_response_without_final_text():
    empty_response = _TraceResponse('{"content": [{"type": "thinking", "thinking": "wait"}]}')
    final_response = _TraceResponse('{"content": [{"type": "text", "text": "<final>ok</final>"}]}')
    client = AnthropicCompatibleModelClient("test-model", "https://example.test", "test-key", 0.0, 30)
    events = []
    with patch("urllib.request.urlopen", side_effect=[empty_response, final_response]):
        with patch("page.providers.clients.time.sleep"):
            result = client.complete("hello", 42, trace_callback=lambda name, data: events.append((name, data)))

    assert result == "<final>ok</final>"
    assert [name for name, _ in events] == ["model_http_request", "model_http_response"] * 2
    assert [data["attempt"] for _, data in events] == [1, 1, 2, 2]
    assert empty_response.read_count == final_response.read_count == 1
