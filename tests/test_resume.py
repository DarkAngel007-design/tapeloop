"""ADR-0006's other half: replay is a simulation, resume is real.

The distinction these tests exist to pin: `fork` serves cached results for `write`
tools and is therefore disconnected from the world, while `resume` serves nothing
from cache and every step it takes actually happens.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers import ScriptedClient, workspace_of

from tapeloop.core.cancel import CancellationToken
from tapeloop.core.loop import Agent
from tapeloop.events import Message, ModelResponse, Role, StopReason, ToolCall, Usage
from tapeloop.record.cache import StepCache
from tapeloop.record.jsonl import JsonlStore, read_records
from tapeloop.replay.resume import (
    NothingToResume,
    StoppedBecause,
    plan_resume,
)
from tapeloop.sandbox.snapshot import SnapshotStore
from tapeloop.tools import builtin


def _write(step: int, path: str, content: str) -> ModelResponse:
    return ModelResponse(
        message=Message(
            role=Role.ASSISTANT,
            tool_calls=(
                ToolCall(
                    id=f"c{step}", name="write_file", arguments={"path": path, "content": content}
                ),
            ),
        ),
        stop_reason=StopReason.TOOL_USE,
        usage=Usage(input_tokens=10, output_tokens=4),
    )


def _done(text: str) -> ModelResponse:
    return ModelResponse(
        message=Message(role=Role.ASSISTANT, text=text), stop_reason=StopReason.END_TURN
    )


def _agent(tmp: Path, tape: Path, script: list[ModelResponse], **kw: object) -> Agent:
    return Agent(
        client=ScriptedClient(script),  # pyright: ignore[reportArgumentType]
        registry=builtin.build(workspace_of(tmp)),
        model="m",
        store=JsonlStore(tape),
        **kw,  # pyright: ignore[reportArgumentType]
    )


def _interrupted_run(tmp: Path) -> tuple[Path, Path]:
    """A run that writes one file, then is cancelled. The realistic starting point."""
    ws, tapes = workspace_of(tmp), tmp / "tapes"
    tapes.mkdir(parents=True, exist_ok=True)
    tape = tapes / "run.jsonl"
    token = CancellationToken()

    class CancelsAfterOneWrite(ScriptedClient):
        def complete(self, **kw: object) -> ModelResponse:
            r = super().complete(**kw)  # pyright: ignore[reportArgumentType]
            if self.calls >= 2:
                token.cancel("interrupted by user")
            return r

    agent = Agent(
        client=CancelsAfterOneWrite(  # pyright: ignore[reportArgumentType]
            [_write(0, "one.txt", "1"), _write(1, "two.txt", "2")]
        ),
        registry=builtin.build(ws),
        model="m",
        store=JsonlStore(tape),
    )
    agent.run("write some files", token=token)
    return tape, ws


# ============================================================ the distinction
def test_resume_serves_nothing_from_cache(tmp_path: Path) -> None:
    """The whole of ADR-0006 in one assertion.

    fork replays a prefix and is a simulation; resume replays nothing, so every step
    it takes is a real call producing real effects.
    """
    tape, ws = _interrupted_run(tmp_path)
    plan = plan_resume(tape, workspace=ws)

    client = ScriptedClient([_write(2, "three.txt", "3"), _done("all written")])
    agent = Agent(
        client=client,  # pyright: ignore[reportArgumentType]
        registry=builtin.build(ws),
        model="m",
        store=JsonlStore(tmp_path / "tapes" / "resumed.jsonl"),
    )
    result = agent.resume(plan.history)

    assert result.text == "all written"
    assert client.calls == 2, "resume must make real calls, not serve cached ones"
    assert (ws / "three.txt").read_text(encoding="utf-8") == "3", "the effect really happened"
    # And the earlier work is untouched.
    assert (ws / "one.txt").read_text(encoding="utf-8") == "1"


def test_resume_does_not_rewind_the_workspace_by_default(tmp_path: Path) -> None:
    """Rewinding would delete the work being continued. That is the point."""
    tape, ws = _interrupted_run(tmp_path)
    before = sorted(p.name for p in ws.iterdir())
    plan = plan_resume(tape, workspace=ws)

    assert plan.restored_from is None
    assert sorted(p.name for p in ws.iterdir()) == before, "the workspace was modified"
    assert plan.workspace_is_assumed, "there were writes, so the workspace is being trusted"
    assert "assumed to still hold them" in plan.report()
    assert "Nothing is served from cache" in plan.report()


def test_restoring_is_explicit_and_says_what_it_destroyed(tmp_path: Path) -> None:
    ws, tapes = workspace_of(tmp_path), tmp_path / "tapes"
    tapes.mkdir(parents=True)
    tape = tapes / "run.jsonl"
    snapshots = SnapshotStore(tmp_path / "snapshots")

    agent = _agent(tmp_path, tape, [_write(0, "made.txt", "v1"), _done("done")])
    agent.snapshots = snapshots
    agent.workspace = ws
    agent.run("write it")
    assert (ws / "made.txt").exists()

    plan = plan_resume(tape, workspace=ws, snapshots=snapshots, restore_from=0)
    assert plan.restored_from == 0
    assert not (ws / "made.txt").exists(), "restore should have rewound past the write"
    assert "work done after that point is gone" in plan.report()
    assert not plan.workspace_is_assumed, "nothing is assumed when it was rebuilt"


def test_restoring_without_a_snapshot_store_is_refused(tmp_path: Path) -> None:
    tape, ws = _interrupted_run(tmp_path)
    with pytest.raises(ValueError, match="needs a snapshot store"):
        plan_resume(tape, workspace=ws, restore_from=0)


def test_restoring_from_a_step_with_no_snapshot_is_an_error(tmp_path: Path) -> None:
    tape, ws = _interrupted_run(tmp_path)
    with pytest.raises(FileNotFoundError, match="no snapshot"):
        plan_resume(tape, workspace=ws, snapshots=SnapshotStore(tmp_path / "none"), restore_from=3)


# =============================================================== diagnosis
def test_it_reports_why_the_run_stopped(tmp_path: Path) -> None:
    tape, ws = _interrupted_run(tmp_path)
    assert plan_resume(tape, workspace=ws).stopped_because is StoppedBecause.CANCELLED


def test_a_finished_run_is_still_resumable_and_says_so(tmp_path: Path) -> None:
    ws, tapes = workspace_of(tmp_path), tmp_path / "tapes"
    tapes.mkdir(parents=True)
    tape = tapes / "run.jsonl"
    _agent(tmp_path, tape, [_done("finished")]).run("go")
    plan = plan_resume(tape, workspace=ws)
    assert plan.stopped_because is StoppedBecause.FINISHED
    assert not plan.writes
    assert "nothing about the workspace is assumed" in plan.report()


def test_an_empty_tape_cannot_be_resumed(tmp_path: Path) -> None:
    tapes = tmp_path / "tapes"
    tapes.mkdir(parents=True)
    tape = tapes / "empty.jsonl"
    tape.write_text('{"kind":"header","tapeloop":"0.1.1","v":1}\n', encoding="utf-8")
    with pytest.raises(NothingToResume):
        plan_resume(tape, workspace=workspace_of(tmp_path))


# ============================================================== provenance
def test_a_resumed_run_is_marked_as_one(tmp_path: Path) -> None:
    """A resumed tape is not a whole run, and anything reading it must be able to tell."""
    tape, ws = _interrupted_run(tmp_path)
    out = tmp_path / "tapes" / "resumed.jsonl"
    agent = Agent(
        client=ScriptedClient([_done("continued")]),  # pyright: ignore[reportArgumentType]
        registry=builtin.build(ws),
        model="m",
        store=JsonlStore(out),
    )
    agent.resume(plan_resume(tape, workspace=ws).history)

    starts = [r for r in read_records(out) if r["kind"] == "run_start"]
    assert starts and starts[0]["data"]["resumed"] is True

    fresh = tmp_path / "tapes" / "fresh.jsonl"
    _agent(tmp_path, fresh, [_done("x")]).run("go")
    fresh_start = next(r for r in read_records(fresh) if r["kind"] == "run_start")
    assert fresh_start["data"]["resumed"] is False


def test_resume_can_carry_a_nudge(tmp_path: Path) -> None:
    tape, ws = _interrupted_run(tmp_path)
    client = ScriptedClient([_done("ok")])
    agent = Agent(
        client=client,  # pyright: ignore[reportArgumentType]
        registry=builtin.build(ws),
        model="m",
        store=JsonlStore(tmp_path / "tapes" / "r.jsonl"),
    )
    agent.resume(plan_resume(tape, workspace=ws).history, nudge="skip the third file")
    last_user = [m for m in client.seen_history if m.role is Role.USER][-1]
    assert last_user.text == "skip the third file"


def test_resume_and_fork_differ_on_cache_use(tmp_path: Path) -> None:
    """Stated as a test because it is the distinction people will get wrong."""
    from tapeloop.replay.fork import plan_fork

    tape, ws = _interrupted_run(tmp_path)
    forked = plan_fork(tape, at=1)
    assert isinstance(forked.cache, StepCache), "fork carries a cache: it simulates"
    resumed = plan_resume(tape, workspace=ws)
    assert not hasattr(resumed, "cache"), "resume has no cache by construction"
