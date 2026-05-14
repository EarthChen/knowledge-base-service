from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class AgentEvent:
    """Base class for all agent lifecycle events."""
    type: str


@dataclass
class ThinkingEvent(AgentEvent):
    """Emitted at the start of each ReAct round."""
    type: str = "thinking"
    round_num: int = 0
    text: str = ""


@dataclass
class ToolCallEvent(AgentEvent):
    """Emitted when LLM selects a tool to call."""
    type: str = "tool_call"
    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResultEvent(AgentEvent):
    """Emitted after tool dispatch completes."""
    type: str = "tool_result"
    tool: str = ""
    summary: str = ""


@dataclass
class ContentEvent(AgentEvent):
    """Emitted when LLM generates content."""
    type: str = "content"
    text: str = ""


@dataclass
class DoneEvent(AgentEvent):
    """Emitted when the agent loop finishes normally."""
    type: str = "done"
    result: Any = None


@dataclass
class ErrorEvent(AgentEvent):
    """Emitted on failure."""
    type: str = "error"
    message: str = ""


EventCallback = Callable[[AgentEvent], Awaitable[None]] | None
