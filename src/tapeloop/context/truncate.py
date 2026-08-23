"""Truncating oversized tool output.

A single `read_file` on a large log can be most of a context window. Dropping the
tail loses the answer as often as dropping the head does, so this keeps both ends
and elides the middle, with a marker the model can see and act on — an agent that
knows it is looking at an excerpt can narrow its search; one handed a silently
truncated file cannot.

**Deterministic by construction.** Same input, same output, always. Truncation feeds
straight into step keys (ADR-0004), so anything time- or environment-dependent here
would break replay. This is a pure function and stays one — which is also why it
needs no tape record, unlike compaction (ADR-0020).
"""

from __future__ import annotations

from dataclasses import dataclass

from tapeloop.context.tokens import CHARS_PER_TOKEN, TokenCount, count_text


@dataclass(frozen=True, slots=True)
class Truncation:
    text: str
    elided_lines: int
    elided_chars: int

    @property
    def happened(self) -> bool:
        return self.elided_chars > 0


def truncate_middle(
    text: str,
    *,
    max_tokens: int,
    model: str = "",
    head_fraction: float = 0.6,
) -> Truncation:
    """Keep the head and tail, elide the middle, say so in between.

    Head gets the larger share by default: for file reads and command output the
    beginning is more often the orienting part, while the tail usually holds the
    result or the error.
    """
    count: TokenCount = count_text(text, model=model)
    if count.tokens <= max_tokens:
        return Truncation(text=text, elided_lines=0, elided_chars=0)

    budget_chars = int(max_tokens * CHARS_PER_TOKEN)
    marker_allowance = 80
    keep = max(0, budget_chars - marker_allowance)
    head_chars = int(keep * head_fraction)
    tail_chars = keep - head_chars

    # Cut on line boundaries so neither end is a fragment of a line.
    head = text[:head_chars].rsplit("\n", 1)[0] if "\n" in text[:head_chars] else text[:head_chars]
    tail_raw = text[-tail_chars:] if tail_chars else ""
    tail = tail_raw.split("\n", 1)[1] if "\n" in tail_raw else tail_raw

    elided = text[len(head) : len(text) - len(tail)]
    marker = f"\n\n... [{elided.count(chr(10))} lines / {len(elided)} chars elided] ...\n\n"
    return Truncation(
        text=head + marker + tail,
        elided_lines=elided.count("\n"),
        elided_chars=len(elided),
    )
