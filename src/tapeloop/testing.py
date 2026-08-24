"""Test doubles, shipped.

Anyone building on tapeloop has the same problem this project had from M0: you need
to exercise an agent without paying for it or waiting for it. `ScriptedClient` answers
a fixed sequence of responses, so a test — or a documentation example — runs offline,
instantly, and identically every time.

It is in the package rather than in `tests/` for the same reason the conformance suite
is: the people who need it are downstream.

    from tapeloop.testing import ScriptedClient, says, calls

    client = ScriptedClient([calls("read_file", path="notes.md"), says("Two lines.")])
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

from tapeloop.events import Message, ModelResponse, Role, StopReason, ToolCall, Usage
from tapeloop.providers.stream import StreamEnd, StreamEvent, TextDelta
from tapeloop.tools.registry import ToolSpec


def says(text: str, *, input_tokens: int = 10, output_tokens: int = 5) -> ModelResponse:
    """A final answer: the model is done."""
    return ModelResponse(
        message=Message(role=Role.ASSISTANT, text=text),
        stop_reason=StopReason.END_TURN,
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def calls(name: str, *, call_id: str | None = None, **arguments: Any) -> ModelResponse:
    """A tool call: the model wants something run before it can continue."""
    return ModelResponse(
        message=Message(
            role=Role.ASSISTANT,
            tool_calls=(ToolCall(id=call_id or f"call_{name}", name=name, arguments=arguments),),
        ),
        stop_reason=StopReason.TOOL_USE,
        usage=Usage(input_tokens=10, output_tokens=5),
    )


class ScriptedClient:
    """A ModelClient that answers from a fixed list.

    Running out of script raises rather than improvising, because a run that took more
    steps than expected is a finding, not something to paper over.
    """

    def __init__(self, script: Sequence[ModelResponse], *, provider: str = "scripted") -> None:
        self._script = list(script)
        self._provider = provider
        self.calls = 0
        self.seen: list[list[Message]] = []
        """The history handed over at each call. Assert on this to check what the model saw."""

    @property
    def provider_id(self) -> str:
        return self._provider

    @property
    def exhausted(self) -> bool:
        return not self._script

    def complete(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        max_tokens: int = 4096,
    ) -> ModelResponse:
        self.calls += 1
        self.seen.append(list(messages))
        if not self._script:
            raise AssertionError(
                f"the script ran out after {self.calls} call(s): the run took more steps "
                "than expected, which is worth looking at rather than padding the script"
            )
        return self._script.pop(0)

    def stream(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        max_tokens: int = 4096,
    ) -> Iterator[StreamEvent]:
        response = self.complete(model=model, messages=messages, tools=tools, max_tokens=max_tokens)
        if response.message.text:
            for word in response.message.text.split(" "):
                yield TextDelta(text=word + " ")
        yield StreamEnd(response=response)

    def count_tokens(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
    ) -> int:
        return sum(len(m.text or "") for m in messages) // 4


def last_assistant_text(messages: Sequence[Message]) -> str | None:
    """The final thing the model said, for asserting on a RunResult's history."""
    return next((m.text for m in reversed(messages) if m.role is Role.ASSISTANT and m.text), None)


__all__ = ["ScriptedClient", "calls", "last_assistant_text", "says"]
