# pyright: basic
#
# Stages are bare lambdas standing in for real work, and the fakes are
# structural stand-ins for the ModelClient Protocol.
"""M8 — subagents and orchestration shape. Zero API spend."""

from __future__ import annotations

from pathlib import Path

from helpers import ScriptedClient, workspace_of

from tapeloop.agents.orchestrate import ShapeComparison, barrier, compare_shapes, pipeline
from tapeloop.agents.subagent import Spawner, fan_out
from tapeloop.core.loop import Agent
from tapeloop.events import Message, ModelResponse, Role, StopReason, Usage
from tapeloop.record.base import InMemoryStore
from tapeloop.record.jsonl import JsonlStore
from tapeloop.replay.recording import Recording
from tapeloop.tools import builtin
from tapeloop.tools.registry import Registry


def _says(text: str) -> list[ModelResponse]:
    return [
        ModelResponse(
            message=Message(role=Role.ASSISTANT, text=text),
            stop_reason=StopReason.END_TURN,
            usage=Usage(input_tokens=7, output_tokens=3),
        )
    ]


def _spawner(
    tmp_path: Path, replies: dict[str, str], store: InMemoryStore | None = None
) -> Spawner:
    def build(tools: Registry, tape: Path) -> Agent:
        label = tape.stem
        return Agent(
            client=ScriptedClient(_says(replies.get(label, "nothing"))),  # pyright: ignore[reportArgumentType]
            registry=tools,
            model="fake-1",
            store=JsonlStore(tape),
        )

    return Spawner(
        build=build,
        tapes=tmp_path / "tapes",
        parent_store=store,
        parent_tape=tmp_path / "tapes" / "parent.jsonl",
    )


# ================================================================ own tape
def test_each_subagent_writes_its_own_tape(tmp_path: Path) -> None:
    """ADR-0021: independent key-spaces, independent tapes."""
    store = InMemoryStore()
    spawner = _spawner(tmp_path, {"a": "found A", "b": "found B"}, store)
    tools = builtin.build(workspace_of(tmp_path))

    results = fan_out(spawner, [("a", "look for A"), ("b", "look for B")], tools=tools)

    assert [r.text for r in results] == ["found A", "found B"]
    tapes = sorted(p.name for p in (tmp_path / "tapes").glob("*.jsonl"))
    assert tapes == ["a.jsonl", "b.jsonl"]

    # Each child is a complete, ordinary tape -- so show/fork/diff work on it unchanged.
    child = Recording.load(tmp_path / "tapes" / "a.jsonl")
    assert len(child.steps) == 1
    assert child.steps[0].response.message.text == "found A"


def test_provenance_runs_both_ways(tmp_path: Path) -> None:
    store = InMemoryStore()
    spawner = _spawner(tmp_path, {"a": "done"}, store)
    spawner.spawn("go", tools=Registry(), label="a")

    parent_records = [e for e in store.events() if e.kind == "subagent"]
    assert len(parent_records) == 1
    assert parent_records[0].payload["tape"] == "a.jsonl"
    assert parent_records[0].payload["task"] == "go"
    assert parent_records[0].payload["ok"] is True

    child_text = (tmp_path / "tapes" / "a.jsonl").read_text(encoding="utf-8")
    assert '"kind":"parent"' in child_text
    assert "parent.jsonl" in child_text


def test_the_parent_gets_a_conclusion_not_a_context(tmp_path: Path) -> None:
    """The narrow return is what makes a subagent composable rather than recursive."""
    spawner = _spawner(tmp_path, {"a": "the answer is 42"})
    result = spawner.spawn("work it out", tools=Registry(), label="a")
    assert result.text == "the answer is 42"
    assert result.steps == 1
    assert result.input_tokens == 7
    assert not hasattr(result, "messages"), "the child's history must not leak upward"


def test_one_failed_child_does_not_take_down_the_fan_out(tmp_path: Path) -> None:
    store = InMemoryStore()

    def build(tools: Registry, tape: Path) -> Agent:
        script = [] if tape.stem == "b" else _says("fine")  # empty script raises mid-run
        return Agent(
            client=ScriptedClient(script),  # pyright: ignore[reportArgumentType]
            registry=tools,
            model="fake-1",
            store=JsonlStore(tape),
        )

    spawner = Spawner(build=build, tapes=tmp_path / "tapes", parent_store=store)
    results = fan_out(spawner, [("a", "ok"), ("b", "boom"), ("c", "ok")], tools=Registry())

    assert [r.ok for r in results] == [True, False, True]
    assert results[1].error is not None
    assert [e.payload["ok"] for e in store.events() if e.kind == "subagent"] == [True, False, True]


# ============================================================== orchestration
def test_pipeline_beats_a_barrier_when_items_differ_in_cost() -> None:
    """The barrier's cost is invisible: it does not fail, it just wastes wall-clock."""
    items = ["fast", "fast", "slow"]
    stages = [lambda x: x, lambda x: x, lambda x: x]

    def cost(item: str, _stage: int) -> int:
        return 9 if item == "slow" else 1

    comparison: ShapeComparison = compare_shapes(items, stages, cost=cost)
    # barrier: every stage waits for `slow` -> 9 + 9 + 9
    assert comparison.barrier_time == 27
    # pipeline: the longest single chain -> 9 + 9 + 9 for `slow`, others run alongside
    assert comparison.pipeline_time == 27


def test_the_barrier_penalty_shows_when_slowness_moves_between_stages() -> None:
    """Each stage has a different laggard, so a barrier waits for all of them in turn."""
    items = ["a", "b", "c"]
    stages = [lambda x: x, lambda x: x, lambda x: x]
    slow_at = {"a": 0, "b": 1, "c": 2}

    def cost(item: str, stage: int) -> int:
        return 10 if slow_at[item] == stage else 1

    c = compare_shapes(items, stages, cost=cost)
    assert c.barrier_time == 30, "10 + 10 + 10: a different item is slow in each stage"
    assert c.pipeline_time == 12, "any single chain is 10 + 1 + 1"
    assert c.saved == 18
    assert "saved=18" in str(c)


def test_both_shapes_produce_the_same_results() -> None:
    """Shape is a scheduling choice. It must never change the answer."""
    items = [1, 2, 3]
    stages = [lambda x: x + 1, lambda x: x * 2]
    b, _ = barrier(items, stages)
    p, _ = pipeline(items, stages)
    assert b == p == [4, 6, 8]
