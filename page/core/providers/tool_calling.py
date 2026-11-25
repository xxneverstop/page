"""Provider-neutral native tool-calling data structures and adapters."""

from dataclasses import asdict, dataclass, field
import json


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class ToolObservation:
    call_id: str
    name: str
    content: str
    is_error: bool = False

    def to_dict(self):
        return asdict(self)


@dataclass
class ModelResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    continuation: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


def parse_json_arguments(value):
    """Normalize provider arguments to a JSON object."""
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str):
        raise ValueError("tool arguments must be a JSON object")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("tool arguments contain malformed JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("tool arguments must be a JSON object")
    return parsed


def neutral_tool_definitions(tools):
    return [
        {
            "name": name,
            "description": str(tool.get("description", "")),
            "input_schema": dict(tool["input_schema"]),
        }
        for name, tool in tools.items()
    ]


def openai_tool_definitions(tools):
    return [
        {
            "type": "function",
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
            "strict": False,
        }
        for tool in tools
    ]


def anthropic_tool_definitions(tools):
    return [
        {
            "name": tool["name"],
            "description": tool["description"],
            "input_schema": tool["input_schema"],
        }
        for tool in tools
    ]


def openai_tool_calls(data):
    calls = []
    for item in data.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "function_call":
            continue
        calls.append(
            ToolCall(
                call_id=str(item.get("call_id") or item.get("id") or ""),
                name=str(item.get("name") or ""),
                arguments=parse_json_arguments(item.get("arguments", {})),
            )
        )
    return calls


def anthropic_tool_calls(data):
    calls = []
    for item in data.get("content", []):
        if not isinstance(item, dict) or item.get("type") != "tool_use":
            continue
        calls.append(
            ToolCall(
                call_id=str(item.get("id") or ""),
                name=str(item.get("name") or ""),
                arguments=parse_json_arguments(item.get("input", {})),
            )
        )
    return calls
