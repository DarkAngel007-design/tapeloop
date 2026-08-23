"""Compaction: replacing old history with a summary, as a recorded step.

ADR-0020. Summarising is a model call, so it is nondeterministic, so it must go
through the step machinery like everything else — keyed, cached, and written to the
tape. Done as a side effect it would produce a different summary on every replay and
every key after it would diverge, which is Contract 1 failing silently.

What is never dropped: the system prompt, the original task, and the most recent
turns. Losing the task is how a long run quietly starts solving a different problem.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from tapeloop.events import Message, Role, user

COMPACTION_PROMPT_VERSION = "1"

COMPACTION_PROMPT = """Summarise the conversation below so work can continue without it.

Preserve, in this order of priority:
1. What was asked for, exactly.
2. Decisions already made and why.
3. Facts discovered — file paths, values, error messages — that later steps will need.
4. What has already been done, so it is not repeated.

Drop: tool output that has been superseded, exploration that led nowhere, and
restatements. Do not speculate about what remains; describe only what happened.

CONVERSATION:
{history}"""


@dataclass(frozen=True, slots=True)
class CompactionPlan:
    """What would be replaced, decided before any model call is made."""

    keep_head: int
    """Messages preserved at the front: system prompt and original task."""
    compact_from: int
    compact_to: int
    keep_recent: int

    @property
    def replaces(self) -> int:
        return max(0, self.compact_to - self.compact_from)

    @property
    def worthwhile(self) -> bool:
        """Summarising two messages costs a model call to save almost nothing."""
        return self.replaces >= 4


def plan_compaction(messages: Sequence[Message], *, keep_recent: int = 6) -> CompactionPlan:
    """Decide the slice to summarise.

    Head is the system prompt plus the first user message — the task itself. Both
    are non-negotiable: a run that forgets what it was asked is worse than one that
    runs out of context, because it keeps going.
    """
    head = 0
    if messages and messages[0].role is Role.SYSTEM:
        head += 1
    if len(messages) > head and messages[head].role is Role.USER:
        head += 1

    tail_start = max(head, len(messages) - keep_recent)
    return CompactionPlan(
        keep_head=head, compact_from=head, compact_to=tail_start, keep_recent=keep_recent
    )


def render_for_summary(messages: Sequence[Message]) -> str:
    lines: list[str] = []
    for message in messages:
        if message.text:
            lines.append(f"[{message.role.value}] {message.text}")
        for call in message.tool_calls:
            lines.append(f"[tool_call] {call.name}({call.arguments})")
        for result in message.tool_results:
            flag = "ERROR " if result.is_error else ""
            lines.append(f"[tool_result] {flag}{result.content}")
    return "\n".join(lines)


def summary_request(messages: Sequence[Message]) -> list[Message]:
    """The messages sent to produce a summary. A normal request, so it keys normally."""
    return [user(COMPACTION_PROMPT.format(history=render_for_summary(messages)))]


def apply_compaction(
    messages: Sequence[Message], plan: CompactionPlan, summary: str
) -> list[Message]:
    """Splice the summary in. Marked as such so a reader of the tape sees the seam."""
    head = list(messages[: plan.keep_head])
    tail = list(messages[plan.compact_to :])
    marker = Message(
        role=Role.USER,
        text=(
            f"[compacted: {plan.replaces} earlier messages replaced by this summary]\n\n{summary}"
        ),
    )
    return [*head, marker, *tail]
