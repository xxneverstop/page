"""Minimal, provider-neutral coding agent core.

The package is deliberately small: structured messages are the source of truth,
and the agent loop only coordinates context, model turns, and tool results.
"""

from .agent import Agent
from .context import Context
from .events import EventSink, MemoryEventSink
from .models import (
    AgentEvent,
    AgentResult,
    Message,
    ModelTurn,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from .provider import FakeProvider, OpenAICompatibleProvider, Provider
from .session import Session
from .tools import ToolExecutor
from .observability import RunArtifacts, TraceWriter, ViewerTraceAdapter
from .recovery import ActionJournal, Checkpoint, CheckpointStore, make_resume_decision
from .skills import SkillStore, render_skill_context

__all__ = [
    "Agent",
    "AgentEvent",
    "AgentResult",
    "Context",
    "EventSink",
    "FakeProvider",
    "MemoryEventSink",
    "Message",
    "ModelTurn",
    "OpenAICompatibleProvider",
    "Provider",
    "Session",
    "ToolCall",
    "ToolExecutor",
    "ToolResult",
    "ToolSpec",
    "RunArtifacts",
    "TraceWriter",
    "ViewerTraceAdapter",
    "ActionJournal",
    "Checkpoint",
    "CheckpointStore",
    "make_resume_decision",
    "SkillStore",
    "render_skill_context",
]
