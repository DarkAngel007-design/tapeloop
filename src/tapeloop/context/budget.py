"""The context budget: what gets truncated, and when to compact.

One object so the two decisions cannot drift apart. Both are driven by the same
number — how much of the window is already spent — and both report *why* they
fired, because a run that quietly discarded half its history is one nobody can
debug afterwards.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from tapeloop.context.tokens import Method, TokenCount, count_text
from tapeloop.context.truncate import Truncation, truncate_middle
from tapeloop.events import Message


@dataclass(frozen=True, slots=True)
class Usage:
    tokens: int
    limit: int
    method: Method

    @property
    def fraction(self) -> float:
        return self.tokens / self.limit if self.limit else 0.0

    def __str__(self) -> str:
        return f"{self.tokens}/{self.limit} ({self.fraction:.0%}, {self.method.value})"


@dataclass(slots=True)
class ContextBudget:
    """Limits, and the decisions that follow from them."""

    context_window: int = 128_000
    reserve_for_output: int = 8_000
    """Held back so a full window still leaves room to answer."""
    compact_at: float = 0.75
    """Fraction of the usable window that triggers compaction."""
    max_tool_result_tokens: int = 4_000
    """Per-result cap. One large file read should not be most of the window."""
    keep_recent: int = 6
    """Turns held out of compaction. Too few and the model loses its place."""
    model: str = ""

    @property
    def usable(self) -> int:
        return max(1, self.context_window - self.reserve_for_output)

    def measure(self, messages: Sequence[Message]) -> Usage:
        text = "\n".join(_render(m) for m in messages)
        count: TokenCount = count_text(text, model=self.model)
        return Usage(tokens=count.tokens, limit=self.usable, method=count.method)

    def should_compact(self, messages: Sequence[Message]) -> tuple[bool, Usage]:
        usage = self.measure(messages)
        return usage.fraction >= self.compact_at, usage

    def fit_tool_result(self, content: str) -> Truncation:
        """Cap one tool result. Pure and deterministic — it feeds step keys."""
        return truncate_middle(content, max_tokens=self.max_tool_result_tokens, model=self.model)


def _render(message: Message) -> str:
    parts: list[str] = [message.text or ""]
    parts += [f"{c.name}{c.arguments}" for c in message.tool_calls]
    parts += [r.content for r in message.tool_results]
    return "\n".join(p for p in parts if p)
