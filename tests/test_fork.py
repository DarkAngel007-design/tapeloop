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
