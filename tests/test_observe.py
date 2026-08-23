"""M9 ship criterion: a trace can be opened, and per-step cost is visible in it."""

from __future__ import annotations

from pathlib import Path

from helpers import ScriptedClient, workspace_of

from tapeloop.agents.subagent import Spawner
from tapeloop.core.loop import Agent
from tapeloop.events import Message, ModelResponse, Role, StopReason, ToolCall, Usage
from tapeloop.observe.cost import Cost, PriceTable
from tapeloop.observe.trace import build_trace, export_otel
from tapeloop.observe.viewer import render, write_viewer
from tapeloop.record.jsonl import JsonlStore
from tapeloop.tools import builtin
from tapeloop.tools.registry import Registry


def _run(tmp_path: Path, tape: Path, *, store: JsonlStore | None = None) -> Agent:
    script = [
        ModelResponse(
            message=Message(
                role=Role.ASSISTANT,
                tool_calls=(ToolCall(id="c1", name="list_files", arguments={"pattern": "*"}),),
            ),
            stop_reason=StopReason.TOOL_USE,
            usage=Usage(input_tokens=1200, output_tokens=40),
        ),
        ModelResponse(
            message=Message(role=Role.ASSISTANT, text="Two files, both text."),
            stop_reason=StopReason.END_TURN,
            usage=Usage(input_tokens=1500, output_tokens=25),
        ),
    ]
    return Agent(
        client=ScriptedClient(script),  # pyright: ignore[reportArgumentType]
        registry=builtin.build(workspace_of(tmp_path)),
        model="gpt-4o-mini",
        store=store or JsonlStore(tape),
    )


def _prices() -> PriceTable:
    from tapeloop.observe.cost import Price

    return PriceTable(prices={"gpt-4o-mini": Price(input_per_m=0.15, output_per_m=0.60)})


# ============================================================ SHIP CRITERION
def test_ship_criterion_a_trace_opens_offline_with_cost_visible(tmp_path: Path) -> None:
    tape = tmp_path / "tapes" / "run.jsonl"
    _run(tmp_path, tape).run("survey the directory")

    out = write_viewer(tape, prices=_prices())
    assert out.exists()
    page = out.read_text(encoding="utf-8")

    # Self-contained: no server, no collector, no external asset.
    assert page.startswith("<!doctype html>")
    assert "<style>" in page
    for forbidden in ("http://", "https://", "<script"):
        assert forbidden not in page, f"the page must not reference {forbidden}"

    # Per-step cost is visible: totals plus per-step token counts.
    assert "2,700" in page, "total input tokens"
    assert "$0.000444" in page, "a real cost figure at useful precision"
    assert "1200 in / 40 out" in page, "per-step usage"
    assert "list_files" in page


def test_an_unpriced_model_shows_as_unknown_never_as_zero(tmp_path: Path) -> None:
    """A cost figure that is quietly wrong is worse than one that is visibly absent."""
    tape = tmp_path / "tapes" / "run.jsonl"
    _run(tmp_path, tape).run("go")
    summary = build_trace(tape, prices=PriceTable())
    assert summary.cost is not None
    assert not summary.cost.priced
    assert str(summary.cost) == "—"
    assert "add prices.toml" in render(summary)


def test_cost_uses_the_cheaper_rate_for_cached_input() -> None:
    from tapeloop.observe.cost import Price

    table = PriceTable(
        prices={"m": Price(input_per_m=1.0, output_per_m=2.0, cached_input_per_m=0.25)}
    )
    full: Cost = table.cost("m", input_tokens=1_000_000, output_tokens=0)
    half: Cost = table.cost("m", input_tokens=1_000_000, output_tokens=0, cached=500_000)
    assert full.usd == 1.0
    assert half.usd == 0.625, "half at 1.00, half at 0.25"


# ==================================================================== tree
def test_a_trace_is_a_tree_of_tapes(tmp_path: Path) -> None:
    """ADR-0021: children are rendered by the same code that renders the parent."""
    tapes = tmp_path / "tapes"
    tapes.mkdir(parents=True)
    parent_tape = tapes / "parent.jsonl"
    parent_store = JsonlStore(parent_tape)

    def build(tools: Registry, tape: Path) -> Agent:
        return Agent(
            client=ScriptedClient(  # pyright: ignore[reportArgumentType]
                [
                    ModelResponse(
                        message=Message(role=Role.ASSISTANT, text=f"child {tape.stem} done"),
                        stop_reason=StopReason.END_TURN,
                        usage=Usage(input_tokens=300, output_tokens=10),
                    )
                ]
            ),
            registry=tools,
            model="gpt-4o-mini",
            store=JsonlStore(tape),
        )

    spawner = Spawner(build=build, tapes=tapes, parent_store=parent_store, parent_tape=parent_tape)
    _run(tmp_path, parent_tape, store=parent_store).run("delegate")
    spawner.spawn("sub work", tools=Registry(), label="kid")

    summary = build_trace(parent_tape, prices=_prices())
    assert len(summary.children) == 1
    assert summary.children[0].tape.name == "kid.jsonl"
    # Totals roll up through the tree.
    assert summary.input_tokens == 2700
    assert summary.total_input() == 3000

    page = render(summary)
    assert "subagent · kid.jsonl" in page
    assert "child kid done" in page


def test_permission_and_context_records_appear_in_the_trace(tmp_path: Path) -> None:
    """Everything the tape already records shows up; M9 is presentation, not instrumentation."""
    from tapeloop.context.budget import ContextBudget
    from tapeloop.sandbox.permissions import PermissionPolicy, Rule, Verdict

    tape = tmp_path / "tapes" / "run.jsonl"
    agent = _run(tmp_path, tape)
    agent.policy = PermissionPolicy(rules=[Rule("list_files", "*", Verdict.DENY)])
    agent.budget = ContextBudget(model="gpt-4o-mini")
    agent.run("go")

    page = render(build_trace(tape, prices=_prices()))
    assert "permission" in page
    assert "deny" in page
    assert "list_files" in page


def test_otel_export_is_optional_and_says_so(tmp_path: Path) -> None:
    """Without the package installed it exports nothing rather than failing."""
    tape = tmp_path / "tapes" / "run.jsonl"
    _run(tmp_path, tape).run("go")
    assert export_otel(build_trace(tape)) >= 0


def test_html_is_escaped(tmp_path: Path) -> None:
    """Model output and tool output both reach this page, and both are arbitrary text."""
    tape = tmp_path / "tapes" / "run.jsonl"
    agent = Agent(
        client=ScriptedClient(  # pyright: ignore[reportArgumentType]
            [
                ModelResponse(
                    message=Message(
                        role=Role.ASSISTANT, text="<script>alert('xss')</script> & <b>bold</b>"
                    ),
                    stop_reason=StopReason.END_TURN,
                )
            ]
        ),
        registry=builtin.build(workspace_of(tmp_path)),
        model="gpt-4o-mini",
        store=JsonlStore(tape),
    )
    agent.run("go")
    page = render(build_trace(tape))
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page
    assert "&amp;" in page
