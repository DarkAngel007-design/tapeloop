"""The canonical event model.

Contract 5: the tape stores *these* types, never a provider's wire format. Each
``ModelClient`` renders these out to its API shape and parses responses back in.

The one rule that shapes everything here: results from parallel tool calls belong
to a single step, as a set. OpenAI renders that set as one message per result;
Anthropic renders it as one message containing every result. Neither layout is
allowed to leak into the tape, so the tape stores the set.

See ``docs/explanation/provider-differences.md`` and ADR-0011.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_RESULTS = "tool_results"


class StopReason(StrEnum):
    """Normalized across providers.

    OpenAI ``finish_reason`` and Anthropic ``stop_reason`` use different words for
    overlapping concepts; adapters map into this vocabulary and the loop only ever
    sees these. ``OTHER`` exists so an unknown future value degrades to a stop
    rather than being mistaken for a completed turn.
    """

    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"
    REFUSAL = "refusal"
    FILTERED = "filtered"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class Opaque:
    """A payload the runtime does not understand and must not touch.

    Reasoning blobs, encrypted items, vendor-specific fields. Stored verbatim,
    tagged with the provider that produced it, handed straight back to that same
    provider on the next turn — and dropped, visibly, when forking elsewhere.
    """

    provider: str
    kind: str
    data: Any


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()
    opaque: tuple[Opaque, ...] = ()


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ModelResponse:
    message: Message
    stop_reason: StopReason
    usage: Usage = field(default_factory=Usage)


def system(text: str) -> Message:
    return Message(role=Role.SYSTEM, text=text)


def user(text: str) -> Message:
    return Message(role=Role.USER, text=text)


def results(*items: ToolResult) -> Message:
    """Wrap tool results as one step's worth. Never split these across messages."""
    return Message(role=Role.TOOL_RESULTS, tool_results=tuple(items))
