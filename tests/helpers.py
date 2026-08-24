"""Shared test doubles."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

from tapeloop.events import Message, ModelResponse
from tapeloop.providers.stream import StreamEvent
from tapeloop.tools.registry import ToolSpec


def workspace_of(tmp_path: Path) -> Path:
    """The directory the agent can see. Tapes must live outside it."""
    ws = tmp_path / "workspace"
    ws.mkdir(exist_ok=True)
    return ws


class ScriptedClient:
    """Replays a fixed script. Counts calls so cache hits are observable."""

    def __init__(self, script: list[ModelResponse]) -> None:
        self._script = list(script)
        self.calls = 0
        self.seen_history: list[Message] = []

    @property
    def provider_id(self) -> str:
        return "scripted"

    def complete(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        max_tokens: int = 4096,
    ) -> ModelResponse:
        self.calls += 1
        self.seen_history = list(messages)
        if not self._script:
            raise AssertionError("the script ran out; the run took more steps than expected")
        return self._script.pop(0)

    def stream(self, **_kw: object) -> Iterator[StreamEvent]:  # pragma: no cover
        raise NotImplementedError

    def count_tokens(self, **_kw: object) -> int:
        return 0
