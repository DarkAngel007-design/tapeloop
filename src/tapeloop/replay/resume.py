"""Resume: continue a run that stopped, for real.

The other half of ADR-0006. `replay` and `fork` serve cached results for `write`
tools — which makes them *simulations*: fast, repeatable, and disconnected from the
world. `resume` serves nothing from cache. Every step it takes is real.

**It does not restore a snapshot by default,** and that is the decision worth
explaining. When a four-hour run dies at minute 200, the workspace already holds
everything those 200 minutes produced. That state *is* what you are resuming.
Rewinding it to a snapshot would delete the work you are trying to continue.

Restoring is therefore a separate, explicit request — `--restore-from N` — for the
different question: "it went wrong around step 12, put the workspace back and let it
try again." That is a *fork* of intent even though it reuses this machinery, and the
report says which one you got.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from tapeloop.events import Message
from tapeloop.replay.recording import RecordedTool, Recording
from tapeloop.sandbox.snapshot import SnapshotStore
from tapeloop.tools.effects import Effect


class StoppedBecause(StrEnum):
    CANCELLED = "cancelled"
    """Interrupted. The most common reason to resume."""

    STEP_CEILING = "step_ceiling"
    """Hit max_steps. Resuming gives it another budget."""

    FINISHED = "finished"
    """The model said it was done. Resuming is unusual but legitimate."""

    INCOMPLETE = "incomplete"
    """No run_end record: the process died before it could write one."""


class NothingToResume(Exception):
    """The tape holds no steps, so there is no run to continue."""


@dataclass(slots=True)
class ResumePlan:
    tape: Path
    workspace: Path
    history: list[Message]
    completed_steps: int
    stopped_because: StoppedBecause
    writes: list[RecordedTool] = field(default_factory=list[RecordedTool])
    restored_from: int | None = None

    @property
    def workspace_is_assumed(self) -> bool:
        """True when we are trusting the workspace to be where the run left it."""
        return self.restored_from is None and bool(self.writes)

    def report(self) -> str:
        lines = [
            f"resume {self.tape.name} after {self.completed_steps} step(s) "
            f"— stopped: {self.stopped_because.value}"
        ]
        if self.restored_from is not None:
            lines.append(
                f"  workspace restored to the state entering step {self.restored_from};"
                " work done after that point is gone."
            )
        elif self.writes:
            lines.append(
                f"  {len(self.writes)} write(s) happened in this run. The workspace is"
                " assumed to still hold them — resume continues from the world as it is,"
                " it does not rebuild it."
            )
        else:
            lines.append("  no writes in this run; nothing about the workspace is assumed.")
        lines.append("  Nothing is served from cache. Every step from here is real.")
        return "\n".join(lines)


def plan_resume(
    tape: Path,
    *,
    workspace: Path,
    snapshots: SnapshotStore | None = None,
    restore_from: int | None = None,
) -> ResumePlan:
    """Work out what continuing this tape means, without running anything."""
    recording = Recording.load(tape)
    if not recording.steps:
        raise NothingToResume(f"{tape.name} records no steps")

    kinds = [e for e in _kinds(tape)]
    if "cancelled" in kinds:
        stopped = StoppedBecause.CANCELLED
    elif "run_end" not in kinds:
        stopped = StoppedBecause.INCOMPLETE
    else:
        last = recording.steps[-1].response.stop_reason.value
        stopped = StoppedBecause.STEP_CEILING if last == "other" else StoppedBecause.FINISHED

    restored: int | None = None
    if restore_from is not None:
        if snapshots is None:
            raise ValueError("--restore-from needs a snapshot store")
        at = snapshots.latest_before(restore_from)
        if at is None:
            raise FileNotFoundError(
                f"no snapshot at or before step {restore_from} in {snapshots.root}"
            )
        snapshots.restore(workspace, step=at)
        restored = at

    return ResumePlan(
        tape=tape,
        workspace=workspace,
        history=list(recording.history),
        completed_steps=len(recording.steps),
        stopped_because=stopped,
        writes=[t for t in recording.tool_calls if t.effect is Effect.WRITE],
        restored_from=restored,
    )


def _kinds(tape: Path) -> list[str]:
    from tapeloop.record.jsonl import read_records

    return [str(r["kind"]) for r in read_records(tape)]
