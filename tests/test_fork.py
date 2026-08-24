"""M4 ship criterion: edit the system prompt, fork at step N, replay the prefix in <1s."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from helpers import ScriptedClient, workspace_of

from tapeloop.core.loop import Agent
from tapeloop.events import Message, ModelResponse, Opaque, Role, StopReason, ToolCall, Usage
from tapeloop.record.jsonl import JsonlStore
from tapeloop.replay.diff import StepStatus, diff_tapes
from tapeloop.replay.fork import Soundness, UnsoundFork, plan_fork
from tapeloop.replay.recording import Recording
from tapeloop.tools import builtin
from tapeloop.tools.registry import Registry


def _reads(n: int) -> list[ModelResponse]:
    """A run of `n` read-only steps, then a final answer. Prefix is faithful."""
    out: list[ModelResponse] = [
        ModelResponse(
            message=Message(
                role=Role.ASSISTANT,
                tool_calls=(ToolCall(id=f"c{i}", name="list_files", arguments={"pattern": "*"}),),
            ),
            stop_reason=StopReason.TOOL_USE,
            usage=Usage(input_tokens=5, output_tokens=2),
        )
        for i in range(n)
    ]
    out.append(
        ModelResponse(
            message=Message(role=Role.ASSISTANT, text="all done"),
            stop_reason=StopReason.END_TURN,
        )
    )
    return out


def _agent(tmp: Path, tape: Path, client: ScriptedClient, **kw: object) -> Agent:
    return Agent(
        client=client,  # pyright: ignore[reportArgumentType]
        registry=builtin.build(workspace_of(tmp)),
        model="scripted-1",
        store=JsonlStore(tape),
        **kw,  # pyright: ignore[reportArgumentType]
    )


# ============================================================ SHIP CRITERION
def test_ship_criterion_fork_at_step_12_replays_the_prefix_in_under_a_second(
    tmp_path: Path,
) -> None:
    tapes = tmp_path / "tapes"
    tapes.mkdir(parents=True)
    original = tapes / "run.jsonl"

    # max_steps defaults to 12, so a 16-step script needs the ceiling raised.
    _agent(tmp_path, original, ScriptedClient(_reads(15)), max_steps=20).run("survey the tree")
    recording = Recording.load(original)
    assert len(recording.steps) >= 13, f"only {len(recording.steps)} steps recorded"

    started = time.perf_counter()
    plan = plan_fork(original, at=12, system="You are terse. Answer in one line.")
    forked = _agent(tmp_path, tapes / "fork.jsonl", ScriptedClient(_reads(4)), cache=plan.cache)
    forked.run("survey the tree", history=plan.history)
    elapsed = time.perf_counter() - started

    assert plan.at == 12
    assert len(plan.history) > 0
    assert elapsed < 1.0, f"fork+replay took {elapsed:.3f}s"


# ================================================================ soundness
def test_a_read_only_prefix_forks_faithfully(tmp_path: Path) -> None:
    tapes = tmp_path / "tapes"
    tapes.mkdir(parents=True)
    tape = tapes / "run.jsonl"
    _agent(tmp_path, tape, ScriptedClient(_reads(3))).run("look around")

    plan = plan_fork(tape, at=2)
    assert plan.soundness is Soundness.FAITHFUL
    assert "faithful" in plan.report()
    assert not plan.replayed_writes


def test_a_prefix_containing_a_write_forks_as_simulated(tmp_path: Path) -> None:
    """ADR-0016: the workspace does not match the history, and fork must say so."""
    tapes = tmp_path / "tapes"
    tapes.mkdir(parents=True)
    tape = tapes / "run.jsonl"

    script = [
        ModelResponse(
            message=Message(
                role=Role.ASSISTANT,
                tool_calls=(
                    ToolCall(
                        id="w1", name="write_file", arguments={"path": "a.txt", "content": "x"}
                    ),
                ),
            ),
            stop_reason=StopReason.TOOL_USE,
        ),
        ModelResponse(
            message=Message(role=Role.ASSISTANT, text="written"), stop_reason=StopReason.END_TURN
        ),
    ]
    _agent(tmp_path, tape, ScriptedClient(script)).run("write a file")

    plan = plan_fork(tape, at=1)
    assert plan.soundness is Soundness.SIMULATED
    assert [t.name for t in plan.replayed_writes] == ["write_file"]

    report = plan.report()
    assert "simulated" in report
    assert "write_file" in report, "the report must name the specific tool, not just warn"


def test_require_faithful_refuses_a_simulated_fork(tmp_path: Path) -> None:
    """Evals use this: a silently simulated run poisons a results table."""
    tapes = tmp_path / "tapes"
    tapes.mkdir(parents=True)
    tape = tapes / "run.jsonl"
    script = [
        ModelResponse(
            message=Message(
                role=Role.ASSISTANT,
                tool_calls=(
                    ToolCall(id="w1", name="write_file", arguments={"path": "a", "content": "x"}),
                ),
            ),
            stop_reason=StopReason.TOOL_USE,
        ),
        ModelResponse(
            message=Message(role=Role.ASSISTANT, text="ok"), stop_reason=StopReason.END_TURN
        ),
    ]
    _agent(tmp_path, tape, ScriptedClient(script)).run("write")

    with pytest.raises(UnsoundFork, match="simulated"):
        plan_fork(tape, at=1, require_faithful=True)


def test_crossing_providers_drops_opaque_payloads_visibly(tmp_path: Path) -> None:
    """ADR-0011: dropping them is correct; doing it silently is not."""
    tapes = tmp_path / "tapes"
    tapes.mkdir(parents=True)
    tape = tapes / "run.jsonl"
    script = [
        ModelResponse(
            message=Message(
                role=Role.ASSISTANT,
                text="thought",
                opaque=(Opaque(provider="scripted", kind="reasoning", data={"z": 1}),),
            ),
            stop_reason=StopReason.END_TURN,
        )
    ]
    Agent(
        client=ScriptedClient(script),  # pyright: ignore[reportArgumentType]
        registry=Registry(),
        model="scripted-1",
        store=JsonlStore(tape),
    ).run("think")

    plan = plan_fork(tape, at=1, provider="anthropic")
    assert plan.dropped_opaque == 1
    assert "opaque payload" in plan.report()
    assert all(not m.opaque for m in plan.history)


def test_fork_beyond_the_end_is_rejected(tmp_path: Path) -> None:
    tapes = tmp_path / "tapes"
    tapes.mkdir(parents=True)
    tape = tapes / "run.jsonl"
    _agent(tmp_path, tape, ScriptedClient(_reads(2))).run("go")
    with pytest.raises(ValueError, match="out of range"):
        plan_fork(tape, at=99)


# ===================================================================== diff
def test_diff_identifies_the_first_divergence(tmp_path: Path) -> None:
    tapes = tmp_path / "tapes"
    tapes.mkdir(parents=True)
    a, b = tapes / "a.jsonl", tapes / "b.jsonl"

    _agent(tmp_path, a, ScriptedClient(_reads(3))).run("go")
    _agent(tmp_path, b, ScriptedClient(_reads(3))).run(
        "go", history=[Message(role=Role.SYSTEM, text="different prompt")]
    )

    report = diff_tapes(a, b)
    assert not report.identical
    assert report.diverged_at == 0, "a changed system prompt diverges from the very first step"
    assert "diverged at step 0" in report.render()


def test_diff_of_a_tape_with_itself_is_identical(tmp_path: Path) -> None:
    tapes = tmp_path / "tapes"
    tapes.mkdir(parents=True)
    tape = tapes / "a.jsonl"
    _agent(tmp_path, tape, ScriptedClient(_reads(3))).run("go")

    report = diff_tapes(tape, tape)
    assert report.identical
    assert all(s.status is StepStatus.SAME for s in report.steps)
    assert "identical" in report.render()


def test_a_snapshot_upgrades_a_simulated_fork_to_faithful(tmp_path: Path) -> None:
    """ADR-0016 promised M5's snapshotting would upgrade a tier, not change an interface.

    Same call, same report shape, one field more — the fork stops being a simulation
    because the workspace has been put back the way it was.
    """
    from tapeloop.sandbox.snapshot import SnapshotStore

    ws = workspace_of(tmp_path)
    tapes = tmp_path / "tapes"
    tapes.mkdir(parents=True)
    tape = tapes / "run.jsonl"
    snapshots = SnapshotStore(tmp_path / "snapshots")

    script = [
        ModelResponse(
            message=Message(
                role=Role.ASSISTANT,
                tool_calls=(
                    ToolCall(
                        id="w1", name="write_file", arguments={"path": "made.txt", "content": "v1"}
                    ),
                ),
            ),
            stop_reason=StopReason.TOOL_USE,
        ),
        ModelResponse(
            message=Message(role=Role.ASSISTANT, text="written"), stop_reason=StopReason.END_TURN
        ),
    ]
    agent = _agent(tmp_path, tape, ScriptedClient(script))
    agent.snapshots = snapshots
    agent.workspace = ws
    agent.run("write a file")

    assert (ws / "made.txt").exists(), "the run really did write it"

    # Without snapshots the same fork is a simulation.
    assert plan_fork(tape, at=1).soundness is Soundness.SIMULATED

    # Something else changes the workspace afterwards, as real work does.
    (ws / "made.txt").write_text("clobbered later", encoding="utf-8")
    (ws / "stray.txt").write_text("junk", encoding="utf-8")

    # Forking AT step 1 means replaying step 0, so the world must look the way it did
    # *entering* step 1 -- which includes step 0's write. That is what makes the
    # replayed write real rather than simulated.
    plan = plan_fork(tape, at=1, snapshots=snapshots, workspace=ws)
    assert plan.soundness is Soundness.FAITHFUL
    assert plan.restored_from == 1
    assert "restored from snapshot" in plan.report()
    assert (ws / "made.txt").read_text(encoding="utf-8") == "v1", "the replayed write is real"
    assert not (ws / "stray.txt").exists(), "and later changes are gone"


def test_forking_an_unchanged_run_actually_hits_the_cache(tmp_path: Path) -> None:
    """Two bugs made this impossible, and neither failed loudly.

    `history_before(n)` stopped *at* step n's assistant response rather than before it,
    so the slice was one message short of what the tape had keyed and no fork key ever
    matched. And the fork command called `run(task, history=...)`, which appends its
    task argument — but the forked history already contains the task, so it was sent
    twice, changing the history again.

    Found by forking a real recorded run and noticing a fork with nothing changed
    reported 0 hits.
    """
    from tapeloop.record.cache import StepCache
    from tapeloop.replay.recording import Recording

    tapes = tmp_path / "tapes"
    tapes.mkdir(parents=True)
    tape = tapes / "run.jsonl"
    script = [
        ModelResponse(
            message=Message(
                role=Role.ASSISTANT,
                tool_calls=(ToolCall(id=f"c{i}", name="list_files", arguments={}),),
            ),
            stop_reason=StopReason.TOOL_USE,
        )
        for i in range(3)
    ] + [
        ModelResponse(
            message=Message(role=Role.ASSISTANT, text="done"), stop_reason=StopReason.END_TURN
        )
    ]
    _agent(tmp_path, tape, ScriptedClient(script)).run("THE TASK")

    recording = Recording.load(tape)
    # Entering step n, the history is the system prompt, the task, and n completed
    # turns of two messages each.
    for n in range(len(recording.steps)):
        assert len(recording.history_before(n)) == 2 + 2 * n, f"slice wrong at step {n}"

    plan = plan_fork(tape, at=2)
    # An empty script: any live call raises.
    forked = _agent(tmp_path, tapes / "forked.jsonl", ScriptedClient([]), cache=plan.cache)
    forked.resume(plan.history)
    assert plan.cache.stats.hits >= 1, "an unchanged fork must reuse the tape"
    assert isinstance(plan.cache, StepCache)

    # And the task appears exactly once, not twice.
    assert sum(1 for m in plan.history if m.text == "THE TASK") == 1
