"""tapeloop — an agent runtime that records every step.

M1 exposes the pieces; there is no stable public API until the tape lands at M3.
"""

from tapeloop.core.loop import Agent, RunResult
from tapeloop.events import Message, ModelResponse, StopReason, ToolCall, ToolResult, Usage
from tapeloop.tools.effects import Effect
from tapeloop.tools.registry import Registry, ToolSpec

__version__ = "0.0.0"

__all__ = [
    "Agent",
    "Effect",
    "Message",
    "ModelResponse",
    "Registry",
    "RunResult",
    "StopReason",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "Usage",
]
