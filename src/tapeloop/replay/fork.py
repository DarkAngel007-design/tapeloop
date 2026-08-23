"""Fork: branch a recorded run at a step, then continue live.

The soundness question is ADR-0016. The short version: replaying a cached `write`
means the workspace does not match the history the model has been told about, so
the live steps afterwards are running against a world that disagrees with the
conversation. That does not make fork useless — most prefixes only read — but it
does mean fork has to say which case it is in rather than guess on the user's behalf.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from tapeloop.events import Message
from tapeloop.record.cache import StepCache
from tapeloop.replay.recording import RecordedTool, Recording


class Soundness(StrEnum):
    FAITHFUL = "faithful"
    """No `write` ran in the replayed prefix: the workspace was never mutated."""

    SIMULATED = "simulated"
    """A `write` result was replayed from cache. The workspace does not match history."""


class UnsoundFork(Exception):
    """Raised when --require-faithful meets a simulated fork."""


@dataclass(slots=True)
class ForkPlan:
    source: Path
    at: int
    history: list[Message]
    cache: StepCache
    soundness: Soundness
    replayed_writes: list[RecordedTool] = field(default_factory=list[RecordedTool])
    dropped_opaque: int = 0
    provider: str = ""
    model: str = ""

    def report(self) -> str:
        """What the user needs to know before trusting the result."""
        lines = [f"fork {self.source.name} @ step {self.at} — {self.soundness.value}"]
        if self.soundness is Soundness.SIMULATED:
            lines.append(
                f"  {len(self.replayed_writes)} write(s) replayed from cache; the workspace"
                " does not match this history."
            )
            for tool in self.replayed_writes:
                lines.append(f"    step {tool.step}: {tool.name}")
            lines.append("  Live steps will run against the real workspace. See ADR-0006.")
        if self.dropped_opaque:
            lines.append(
                f"  {self.dropped_opaque} opaque payload(s) dropped: they belong to"
                f" {self.source.name}'s provider and mean nothing to {self.provider}."
            )
        return "\n".join(lines)


def plan_fork(
    tape: Path,
    *,
    at: int,
    provider: str | None = None,
    model: str | None = None,
    system: str | None = None,
    require_faithful: bool = False,
) -> ForkPlan:
    """Build a fork without running anything.

    Separated from execution on purpose: the report can be shown, and a refusal can
    happen, before a single token is spent.
    """
    recording = Recording.load(tape)
    if at < 0 or at > len(recording.steps):
        raise ValueError(f"step {at} out of range; the tape has {len(recording.steps)} steps")

    history = recording.history_before(at)
    if system is not None and history and history[0].text is not None:
        from tapeloop.events import Role

        if history[0].role is Role.SYSTEM:
            history = [Message(role=Role.SYSTEM, text=system), *history[1:]]

    target_provider = provider or recording.provider
    crossing = target_provider != recording.provider

    dropped = 0
    if crossing:
        # ADR-0011: opaque payloads belong to the provider that produced them.
        # Dropping them is right; doing it silently is not.
        rebuilt: list[Message] = []
        for message in history:
            dropped += len(message.opaque)
            rebuilt.append(
                Message(
                    role=message.role,
                    text=message.text,
                    tool_calls=message.tool_calls,
                    tool_results=message.tool_results,
                )
                if message.opaque
                else message
            )
        history = rebuilt

    writes = recording.writes_before(at)
    soundness = Soundness.SIMULATED if writes else Soundness.FAITHFUL

    plan = ForkPlan(
        source=tape,
        at=at,
        history=history,
        # A changed prompt or provider means the keys diverge anyway; the cache is
        # still supplied so the untouched prefix of a same-config fork stays free.
        cache=StepCache.from_tape(tape),
        soundness=soundness,
        replayed_writes=writes,
        dropped_opaque=dropped,
        provider=target_provider,
        model=model or recording.model,
    )
    if require_faithful and soundness is Soundness.SIMULATED:
        raise UnsoundFork(plan.report())
    return plan
