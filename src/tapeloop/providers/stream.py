"""Streaming events, and the accumulator that reassembles tool calls.

The hard part of streaming is not text. Text arrives in pieces and you print the
pieces. Tool *arguments* also arrive in pieces — as fragments of a JSON string, split
at arbitrary points, possibly for several calls interleaved by index:

    chunk 1:  index=0  id="call_a"  name="write_file"  args='{"pa'
    chunk 2:  index=0                                  args='th": "out'
    chunk 3:  index=1  id="call_b"  name="read_file"   args='{"path"'
    chunk 4:  index=0                                  args='.txt"}'

Nothing is valid JSON until the stream ends. The accumulator below keys fragments by
index, concatenates in arrival order, and parses once at the end.

``render_partial`` exists for the live display: it repairs an incomplete fragment well
enough to show the user what is being typed. Its output is **never** parsed back into
arguments — it is a picture, not data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from tapeloop.events import ModelResponse, ToolCall


@dataclass(frozen=True, slots=True)
class TextDelta:
    """A fragment of assistant text."""

    text: str


@dataclass(frozen=True, slots=True)
class ToolCallDelta:
    """A fragment of a tool call. Any field but ``index`` may be absent."""

    index: int
    id: str | None = None
    name: str | None = None
    arguments_fragment: str = ""


@dataclass(frozen=True, slots=True)
class StreamEnd:
    """Always the final event. Carries the assembled response."""

    response: ModelResponse


StreamEvent = TextDelta | ToolCallDelta | StreamEnd


@dataclass(slots=True)
class _Partial:
    id: str | None = None
    name: str | None = None
    arguments: str = ""


@dataclass(slots=True)
class ToolCallAccumulator:
    """Reassembles fragmented tool calls, keyed by stream index."""

    _by_index: dict[int, _Partial] = field(default_factory=dict[int, "_Partial"])

    def add(self, delta: ToolCallDelta) -> None:
        slot = self._by_index.setdefault(delta.index, _Partial())
        if delta.id is not None:
            slot.id = delta.id
        if delta.name is not None:
            slot.name = delta.name
        slot.arguments += delta.arguments_fragment

    def render_partial(self, index: int) -> str:
        """A best-effort readable form of an in-flight fragment, for display only.

        Closes an unterminated string and any open brackets. Never fed back into
        argument parsing — a repaired fragment is a guess, and guesses must not become
        tool inputs.
        """
        slot = self._by_index.get(index)
        if slot is None:
            return ""
        text = slot.arguments
        in_string = False
        escaped = False
        stack: list[str] = []
        for ch in text:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = not in_string
            elif not in_string and ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif not in_string and ch in "}]" and stack:
                stack.pop()
        if escaped:
            text = text[:-1]
        if in_string:
            text += '"'
        return text + "".join(reversed(stack))

    def finish(self) -> tuple[ToolCall, ...]:
        """Parse every accumulated call. Malformed arguments are preserved, not dropped.

        A call whose JSON never became valid is still a call the model made. Keeping the
        raw text under ``__malformed__`` lets the loop hand back a readable error the
        model can correct, instead of silently losing the request.
        """
        calls: list[ToolCall] = []
        for index in sorted(self._by_index):
            slot = self._by_index[index]
            if slot.id is None or slot.name is None:
                continue
            arguments: dict[str, Any]
            try:
                arguments = json.loads(slot.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {"__malformed__": slot.arguments}
            calls.append(ToolCall(id=slot.id, name=slot.name, arguments=arguments))
        return tuple(calls)
