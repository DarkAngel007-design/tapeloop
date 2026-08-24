"""Reading a tape back into something you can operate on.

A tape is self-describing: the header gives the format, `run_start` gives the
provider, model and tool names, and the interleaved `message` and `step` records
give the history. That means replay and fork need no configuration beyond a path.

Assistant turns live inside their `step` record rather than as separate `message`
records, so reconstruction walks the file in order and takes messages from both.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tapeloop.events import Message, ModelResponse
from tapeloop.record.codec import decode_message, decode_response
from tapeloop.record.jsonl import read_records
from tapeloop.tools.effects import Effect


@dataclass(frozen=True, slots=True)
class RecordedStep:
    index: int
    key: str
    response: ModelResponse


@dataclass(frozen=True, slots=True)
class RecordedTool:
    step: int
    name: str
    effect: Effect
    is_error: bool


@dataclass(slots=True)
class Recording:
    """A tape, parsed."""

    path: Path
    provider: str = ""
    model: str = ""
    tools: tuple[str, ...] = ()
    streaming: bool = False
    history: list[Message] = field(default_factory=list[Message])
    steps: list[RecordedStep] = field(default_factory=list[RecordedStep])
    tool_calls: list[RecordedTool] = field(default_factory=list[RecordedTool])
    parent: dict[str, Any] | None = None
    """Set when this tape is itself a fork. Provenance travels (ADR-0016)."""

    @classmethod
    def load(cls, path: Path) -> Recording:
        rec = cls(path=path)
        for record in read_records(path):
            kind = record["kind"]
            data: dict[str, Any] = record.get("data", {})

            if kind == "run_start":
                rec.provider = data.get("provider", "")
                rec.model = data.get("model", "")
                rec.tools = tuple(data.get("tools", []))
                rec.streaming = bool(data.get("streaming", False))
            elif kind == "fork":
                rec.parent = data
            elif kind == "message":
                rec.history.append(decode_message(data))
            elif kind == "step":
                response = decode_response(data)
                rec.steps.append(
                    RecordedStep(index=len(rec.steps), key=record["key"], response=response)
                )
                rec.history.append(response.message)
            elif kind == "tool_result":
                rec.tool_calls.append(
                    RecordedTool(
                        step=record.get("step", 0),
                        name=data.get("tool", "?"),
                        effect=Effect(data.get("effect", "write")),
                        is_error=bool(data.get("is_error", False)),
                    )
                )
        return rec

    def history_before(self, step: int) -> list[Message]:
        """The conversation as it stood **entering** ``step``.

        Anchored on the position of that step's own assistant response, and stopping
        just before it. The earlier version stopped *at* the response instead, leaving
        the slice one message short of what the tape had keyed — so a fork's step key
        never matched anything and the cache silently never hit. Found by forking a
        real recorded run and watching a supposedly unchanged fork miss 0/1.
        """
        if step < 0:
            return []
        if step >= len(self.steps):
            return list(self.history)
        anchor = self.steps[step].response.message
        for i, message in enumerate(self.history):
            if message is anchor:
                return self.history[:i]
        return list(self.history)

    def writes_before(self, step: int) -> list[RecordedTool]:
        """Every `write` tool that ran before ``step`` — the input to ADR-0016."""
        return [t for t in self.tool_calls if t.step < step and t.effect is Effect.WRITE]
