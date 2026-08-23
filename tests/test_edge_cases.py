"""Degenerate inputs. Written before the first release, because the first bug report
is always something nobody thought to type.

The rule these all test: a malformed or empty input should produce a clear failure or
a clean empty result, never a confident wrong answer and never a stack trace from
three layers down.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from helpers import ScriptedClient, workspace_of

from tapeloop.context.budget import ContextBudget
from tapeloop.context.compact import plan_compaction
from tapeloop.context.truncate import truncate_middle
from tapeloop.core.loop import Agent
from tapeloop.events import Message, ModelResponse, Role, StopReason, ToolCall, Usage, user
from tapeloop.observe.cost import PriceTable
from tapeloop.observe.trace import build_trace
from tapeloop.observe.viewer import render
from tapeloop.record.cache import StepCache
from tapeloop.record.canonical import canonical_json, digest
from tapeloop.record.codec import UnsupportedFormat
from tapeloop.record.jsonl import JsonlStore, read_records
from tapeloop.replay.diff import diff_tapes
from tapeloop.replay.fork import plan_fork
from tapeloop.replay.recording import Recording
from tapeloop.sandbox.permissions import PermissionPolicy
from tapeloop.tools.effects import Effect
from tapeloop.tools.registry import Registry


def _done(text: str = "ok") -> list[ModelResponse]:
    return [
        ModelResponse(
            message=Message(role=Role.ASSISTANT, text=text),
            stop_reason=StopReason.END_TURN,
            usage=Usage(input_tokens=5, output_tokens=2),
        )
    ]


def _agent(tmp_path: Path, tape: Path, script: list[ModelResponse], **kw: object) -> Agent:
    return Agent(
        client=ScriptedClient(script),  # pyright: ignore[reportArgumentType]
        registry=Registry(),
        model="fake-1",
        store=JsonlStore(tape),
        **kw,  # pyright: ignore[reportArgumentType]
    )


# ================================================================ empty tapes
def test_a_zero_byte_tape_yields_nothing_rather_than_crashing(tmp_path: Path) -> None:
    tape = tmp_path / "empty.jsonl"
    tape.write_text("", encoding="utf-8")
    assert list(read_records(tape)) == []
    assert Recording.load(tape).steps == []
    assert StepCache.from_tape(tape).responses == {}


def test_a_header_only_tape_is_valid_and_empty(tmp_path: Path) -> None:
    """A run that was cancelled before its first step leaves exactly this."""
    tape = tmp_path / "h.jsonl"
    tape.write_text('{"kind":"header","tapeloop":"0.0.0","v":1}\n', encoding="utf-8")
    rec = Recording.load(tape)
    assert rec.steps == [] and rec.history == []
    summary = build_trace(tape)
    assert summary.steps == 0
    assert "<!doctype html>" in render(summary), "the viewer must still render it"


def test_a_truncated_line_fails_loudly(tmp_path: Path) -> None:
    """A half-written line means the process died mid-flush. Do not guess at it."""
    tape = tmp_path / "cut.jsonl"
    tape.write_text(
        '{"kind":"header","tapeloop":"0.0.0","v":1}\n{"kind":"step","seq":0,"step"\n',
        encoding="utf-8",
    )
    with pytest.raises(json.JSONDecodeError):
        list(read_records(tape))


def test_a_tape_whose_first_line_is_not_a_header_is_rejected(tmp_path: Path) -> None:
    tape = tmp_path / "bad.jsonl"
    tape.write_text('{"kind":"step","seq":0}\n', encoding="utf-8")
    with pytest.raises(UnsupportedFormat, match="not a header"):
        list(read_records(tape))


# ================================================================= zero work
def test_max_steps_zero_completes_without_calling_the_model(tmp_path: Path) -> None:
    tape = tmp_path / "t" / "run.jsonl"
    client = ScriptedClient(_done())
    agent = Agent(
        client=client,  # pyright: ignore[reportArgumentType]
        registry=Registry(),
        model="fake-1",
        store=JsonlStore(tape),
        max_steps=0,
    )
    result = agent.run("do nothing")
    assert client.calls == 0
    assert result.text is None
    assert Recording.load(tape).steps == []


def test_an_empty_registry_still_runs(tmp_path: Path) -> None:
    """An agent with no tools is a chat loop. It should not be a special case."""
    tape = tmp_path / "t" / "run.jsonl"
    result = _agent(tmp_path, tape, _done("nothing to use")).run("hello")
    assert result.text == "nothing to use"


def test_a_tool_with_no_parameters_produces_a_valid_schema() -> None:
    reg = Registry()

    @reg.tool(effect=Effect.PURE)
    def ping() -> str:
        """Return pong."""
        return "pong"

    spec = reg.specs()[0]
    assert spec.parameters == {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }
    assert reg.dispatch("ping", {}) == "pong"


# ============================================================ fork boundaries
def test_fork_at_zero_and_at_the_last_step(tmp_path: Path) -> None:
    tapes = tmp_path / "t"
    tapes.mkdir(parents=True)
    tape = tapes / "run.jsonl"
    _agent(tmp_path, tape, _done()).run("go")

    at_zero = plan_fork(tape, at=0)
    assert at_zero.history == [], "forking at 0 means starting over with no history"

    last = len(Recording.load(tape).steps)
    assert plan_fork(tape, at=last).at == last, "forking at the end is a re-run, not an error"

    with pytest.raises(ValueError, match="out of range"):
        plan_fork(tape, at=last + 1)
    with pytest.raises(ValueError, match="out of range"):
        plan_fork(tape, at=-1)


def test_diff_of_tapes_with_different_lengths(tmp_path: Path) -> None:
    tapes = tmp_path / "t"
    tapes.mkdir(parents=True)
    short, long = tapes / "a.jsonl", tapes / "b.jsonl"
    _agent(tmp_path, short, _done("one")).run("go")
    _agent(
        tmp_path,
        long,
        [
            ModelResponse(
                # A real call: TOOL_USE with an empty tool_calls list is a provider
                # anomaly and the loop stops on it, which is why this needs one.
                message=Message(
                    role=Role.ASSISTANT,
                    tool_calls=(ToolCall(id="c1", name="nosuchtool", arguments={}),),
                ),
                stop_reason=StopReason.TOOL_USE,
            ),
            *_done("two"),
        ],
    ).run("go")

    report = diff_tapes(short, long)
    assert not report.identical
    assert report.steps[-1].status.value == "only-b"
    assert "diverged at step" in report.render()


# =================================================================== unicode
def test_unicode_survives_the_whole_round_trip(tmp_path: Path) -> None:
    """Tape, cache key, and viewer. Any of the three mangling it breaks replay."""
    text = '日本語 · émoji 🎛 · \\backslash · "quote" · <tag> · null\x00ish'
    safe = text.replace("\x00", "")  # NUL is not valid in JSON strings
    tape = tmp_path / "t" / "run.jsonl"
    _agent(tmp_path, tape, _done(safe)).run("go")

    assert Recording.load(tape).steps[0].response.message.text == safe
    page = render(build_trace(tape))
    assert "日本語" in page and "🎛" in page
    assert "&lt;tag&gt;" in page, "and it is still escaped"


def test_canonical_json_is_stable_for_awkward_values() -> None:
    """Round-tripping must be a fixed point, or a re-serialized tape changes its keys."""
    values: list[dict[str, Any]] = [
        {"a": ""},
        {"a": []},
        {"a": {}},
        {"a": 0},
        {"a": False},
        {"a": None},
        {"a": -0.0},
        {"a": 1e300},
        {"": "empty key"},
    ]
    for value in values:
        once = canonical_json(value)
        assert canonical_json(json.loads(once)) == once
        assert digest(json.loads(once)) == digest(value)


# ================================================================== sizing
def test_truncating_to_a_tiny_budget_still_produces_valid_output() -> None:
    t = truncate_middle("x" * 10_000, max_tokens=1)
    assert t.happened
    assert "elided" in t.text


def test_an_empty_string_truncates_to_itself() -> None:
    assert truncate_middle("", max_tokens=100).text == ""


def test_compaction_declines_on_a_history_too_short_to_help() -> None:
    assert not plan_compaction([user("only one")]).worthwhile
    assert not plan_compaction([]).worthwhile


def test_a_zero_width_context_budget_does_not_divide_by_zero() -> None:
    budget = ContextBudget(context_window=0, reserve_for_output=0, model="m")
    assert budget.usable >= 1
    due, usage = budget.should_compact([user("x")])
    assert isinstance(due, bool)
    assert usage.fraction >= 0


# ==================================================================== cost
def test_a_run_with_zero_tokens_costs_zero_not_none() -> None:
    from tapeloop.observe.cost import Price

    table = PriceTable(prices={"m": Price(input_per_m=1.0, output_per_m=2.0)})
    cost = table.cost("m", input_tokens=0, output_tokens=0)
    assert cost.priced and cost.usd == 0.0
    assert str(cost) == "$0.00"


def test_an_empty_price_table_loads_from_a_missing_file(tmp_path: Path) -> None:
    assert PriceTable.load(tmp_path / "nope.toml").prices == {}


# ============================================================== permissions
def test_a_tool_with_no_arguments_renders_an_empty_pattern() -> None:
    policy = PermissionPolicy()
    decision = policy.decide("ping", {}, Effect.PURE)
    assert decision.allowed
    assert decision.rendered == ""


def test_permission_rules_do_not_match_across_tools() -> None:
    from tapeloop.sandbox.permissions import Rule, Verdict

    policy = PermissionPolicy(rules=[Rule("run_command", "*", Verdict.DENY)])
    assert policy.decide("read_file", {"path": "a"}, Effect.READ).allowed


# ================================================================ workspace
def test_path_confinement_covers_absolute_paths_and_symlink_escapes(tmp_path: Path) -> None:
    from tapeloop.tools import builtin

    ws = workspace_of(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (ws / "link").symlink_to(tmp_path)

    reg = builtin.build(ws)
    for path in ("/etc/passwd", str(outside), "../outside.txt", "link/outside.txt"):
        out = reg.dispatch("read_file", {"path": path})
        assert out.startswith("ERROR:"), f"{path!r} was not refused: {out[:60]}"
