"""What a ModelClient *is* — the contract, as executable checks.

ADR-0002 states that the Protocol is only a signature and the real definition of a
`ModelClient` is this suite. Until now that was a claim in a document with nothing
behind it. This is the thing behind it.

**Shipped in the package, not in tests/, on purpose.** Someone writing a third-party
adapter needs to run it:

    from tapeloop.providers.conformance import ConformanceTarget, run_conformance
    report = run_conformance(my_target)
    assert report.passed, report.render()

Every check corresponds to a row in `docs/explanation/provider-differences.md`. If a
divergence is not represented here, the seam does not handle it — the table and this
file are meant to be read together.

**No network.** Every check runs against synthetic wire payloads the adapter itself
constructs, so a new provider can be conformance-tested before anyone has an API key
for it. That is deliberate: an abstraction verified only by adapters that already work
is an abstraction verified by nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from tapeloop.events import (
    Message,
    ModelResponse,
    Role,
    StopReason,
    ToolCall,
    ToolResult,
    results,
    system,
    user,
)
from tapeloop.tools.effects import Effect
from tapeloop.tools.registry import Registry, ToolSpec


@dataclass(frozen=True, slots=True)
class WireResponse:
    """What an adapter must be able to fabricate so its parser can be tested."""

    text: str | None = None
    tool_calls: tuple[tuple[str, str, str], ...] = ()
    """(id, name, raw_argument_json) — raw, so malformed JSON can be exercised."""
    stop: str = "stop"
    """The provider's own vocabulary, not ours."""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    """Divergence #5. OpenAI reports this and offers no control; Anthropic is the
    reverse. Either way the adapter must surface it, because cache hit rate is a
    first-class operational signal and a silent zero looks like a cold cache."""
    extras: dict[str, Any] = field(default_factory=dict[str, Any])
    """Vendor fields the runtime does not model. Must survive as opaque payloads."""


@dataclass(frozen=True, slots=True)
class ConformanceTarget:
    """Everything an adapter supplies to be checked.

    Deliberately small. An adapter that cannot provide these four things has not
    separated rendering from parsing, which is the split the whole seam depends on.
    """

    name: str
    provider_id: str
    render_messages: Callable[[Sequence[Message]], list[Any]]
    render_tools: Callable[[Sequence[ToolSpec]], list[Any]]
    parse: Callable[[Any], ModelResponse]
    build_wire: Callable[[WireResponse], Any]
    stop_reasons: dict[str, StopReason]
    """The provider's documented vocabulary, mapped into ours."""
    count_tokens: Callable[[Sequence[Message]], int] | None = None


@dataclass(slots=True)
class Check:
    id: str
    divergence: str
    """Which row of provider-differences.md this enforces, or '-' for a general rule."""
    description: str
    passed: bool = False
    detail: str = ""


@dataclass(slots=True)
class ConformanceReport:
    target: str
    checks: list[Check] = field(default_factory=list[Check])

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    def render(self) -> str:
        ok = len(self.checks) - len(self.failures)
        lines = [f"conformance: {self.target} — {ok}/{len(self.checks)}"]
        for c in self.checks:
            mark = "ok  " if c.passed else "FAIL"
            lines.append(f"  {mark} {c.id} [{c.divergence}] {c.description}")
            if not c.passed and c.detail:
                lines.append(f"       {c.detail}")
        return "\n".join(lines)


# --------------------------------------------------------------- the fixtures
def _sample_tools() -> Registry:
    reg = Registry()

    @reg.tool(effect=Effect.READ)
    def read_file(path: str, limit: int = 100) -> str:
        """Read a file.

        Args:
            path: Where to read from.
            limit: How many lines.
        """
        return ""

    return reg


def _history_with_parallel_calls() -> list[Message]:
    calls = (
        ToolCall(id="c1", name="read_file", arguments={"path": "a.txt"}),
        ToolCall(id="c2", name="read_file", arguments={"path": "b.txt"}),
    )
    return [
        system("be helpful"),
        user("read both files"),
        Message(role=Role.ASSISTANT, tool_calls=calls),
        results(
            ToolResult(call_id="c1", content="A"),
            ToolResult(call_id="c2", content="B", is_error=True),
        ),
    ]


# --------------------------------------------------------------- the checks
def run_conformance(target: ConformanceTarget) -> ConformanceReport:
    """Run every check. Never raises — a broken adapter produces failures, not a crash."""
    report = ConformanceReport(target=target.name)

    def check(cid: str, divergence: str, description: str) -> Callable[[Callable[[], None]], None]:
        def run(fn: Callable[[], None]) -> None:
            c = Check(id=cid, divergence=divergence, description=description)
            try:
                fn()
                c.passed = True
            except NotImplementedError as e:
                c.detail = f"not implemented: {e}"
            except Exception as e:
                c.detail = f"{type(e).__name__}: {e}"
            report.checks.append(c)

        return run

    # ---------------------------------------------------------------- identity
    @check("C01", "-", "provider_id is stable and non-empty")
    def _c01() -> None:
        assert target.provider_id, "provider_id is empty"
        assert target.provider_id == target.provider_id.strip().lower()

    # ---------------------------------------------------------------- rendering
    @check("C02", "-", "an empty history renders without crashing")
    def _c02() -> None:
        target.render_messages([])

    @check("C03", "#1", "assistant tool calls survive rendering")
    def _c03() -> None:
        wire = target.render_messages(_history_with_parallel_calls())
        blob = repr(wire)
        for needle in ("c1", "c2", "read_file", "a.txt", "b.txt"):
            assert needle in blob, f"{needle!r} did not survive rendering"

    @check("C04", "#2", "a TOOL_RESULTS set renders with every result present")
    def _c04() -> None:
        wire = repr(target.render_messages(_history_with_parallel_calls()))
        assert wire.count("c1") >= 2, "call id c1 must appear on both the call and its result"
        assert "A" in wire and "B" in wire, "a result content was dropped"

    @check("C05", "#2", "result order follows the calls, not arrival (ADR-0014)")
    def _c05() -> None:
        calls = (
            ToolCall(id="first", name="read_file", arguments={"path": "1"}),
            ToolCall(id="second", name="read_file", arguments={"path": "2"}),
        )
        history = [
            Message(role=Role.ASSISTANT, tool_calls=calls),
            # deliberately supplied in the wrong order
            results(
                ToolResult(call_id="second", content="TWO"),
                ToolResult(call_id="first", content="ONE"),
            ),
        ]
        wire = repr(target.render_messages(history))
        assert wire.index("ONE") < wire.index("TWO"), "results were not reordered to match calls"

    @check("C06", "#7", "registry schemas render unmodified")
    def _c06() -> None:
        specs = _sample_tools().specs()
        wire = repr(target.render_tools(specs))
        assert "read_file" in wire
        for prop in ("path", "limit"):
            assert prop in wire, f"parameter {prop!r} was lost"

    # ---------------------------------------------------------------- parsing
    @check("C07", "-", "a plain text response parses to an assistant message")
    def _c07() -> None:
        r = target.parse(target.build_wire(WireResponse(text="hello", stop="stop")))
        assert r.message.role is Role.ASSISTANT
        assert r.message.text == "hello"

    @check("C08", "#1", "tool calls parse with id, name and decoded arguments")
    def _c08() -> None:
        r = target.parse(
            target.build_wire(
                WireResponse(
                    tool_calls=(("c1", "read_file", '{"path": "x.txt"}'),),
                    stop=_first_tool_stop(target),
                )
            )
        )
        assert len(r.message.tool_calls) == 1
        call = r.message.tool_calls[0]
        assert call.id == "c1" and call.name == "read_file"
        assert call.arguments == {"path": "x.txt"}, "arguments must be decoded, not left a string"

    @check("C09", "#1", "parallel tool calls are all preserved, in order")
    def _c09() -> None:
        r = target.parse(
            target.build_wire(
                WireResponse(
                    tool_calls=(
                        ("c1", "read_file", "{}"),
                        ("c2", "read_file", "{}"),
                    ),
                    stop=_first_tool_stop(target),
                )
            )
        )
        assert [c.id for c in r.message.tool_calls] == ["c1", "c2"]

    @check("C10", "-", "malformed tool arguments are preserved, never dropped")
    def _c10() -> None:
        r = target.parse(
            target.build_wire(
                WireResponse(
                    tool_calls=(("c1", "read_file", '{"path": '),),
                    stop=_first_tool_stop(target),
                )
            )
        )
        assert len(r.message.tool_calls) == 1, "a call with bad JSON was dropped"
        assert "__malformed__" in r.message.tool_calls[0].arguments

    @check("C11", "#3", "every documented stop value maps into StopReason")
    def _c11() -> None:
        assert target.stop_reasons, "no stop-reason vocabulary declared"
        for raw, expected in target.stop_reasons.items():
            got = target.parse(target.build_wire(WireResponse(text="x", stop=raw))).stop_reason
            assert got is expected, f"{raw!r} mapped to {got}, expected {expected}"

    @check("C12", "#3", "an unknown stop value degrades to OTHER, never END_TURN")
    def _c12() -> None:
        got = target.parse(
            target.build_wire(WireResponse(text="x", stop="a_reason_invented_in_2030"))
        ).stop_reason
        assert got is StopReason.OTHER, f"unknown stop mapped to {got}"

    @check("C13", "#6", "vendor fields survive verbatim as opaque payloads")
    def _c13() -> None:
        blob = {"nested": [1, 2, {"deep": True}]}
        r = target.parse(
            target.build_wire(WireResponse(text="x", extras={"reasoning_content": blob}))
        )
        assert r.message.opaque, "vendor field was dropped"
        carried = next((o for o in r.message.opaque if o.data == blob), None)
        assert carried is not None, f"payload was altered: {[o.data for o in r.message.opaque]}"
        assert carried.provider == target.provider_id, (
            "opaque payload is not tagged with its origin"
        )

    @check("C14", "#6", "opaque payloads are never inspected or rebuilt")
    def _c14() -> None:
        sentinel = {"do": "not touch"}
        r = target.parse(target.build_wire(WireResponse(text="x", extras={"vendor_x": sentinel})))
        carried = next(o for o in r.message.opaque if o.kind == "vendor_x")
        assert carried.data is sentinel, "payload was copied or normalized rather than carried"

    @check("C15", "-", "usage is parsed when the provider reports it")
    def _c15() -> None:
        r = target.parse(
            target.build_wire(WireResponse(text="x", input_tokens=11, output_tokens=7))
        )
        assert r.usage.input_tokens == 11 and r.usage.output_tokens == 7

    @check("C17", "#5", "cached input tokens are surfaced when the provider reports them")
    def _c17() -> None:
        r = target.parse(
            target.build_wire(
                WireResponse(text="x", input_tokens=1000, output_tokens=10, cached_tokens=750)
            )
        )
        assert r.usage.cached_input_tokens == 750, (
            f"got {r.usage.cached_input_tokens}; a silent zero is indistinguishable from a "
            "cold cache, which is how a caching regression goes unnoticed"
        )
        assert r.usage.input_tokens == 1000, (
            "cached tokens are a subset of input, not a separate total"
        )

    @check("C18", "#5", "an absent cache report is zero, not a crash")
    def _c18() -> None:
        r = target.parse(target.build_wire(WireResponse(text="x", input_tokens=5, output_tokens=1)))
        assert r.usage.cached_input_tokens == 0

    # ---------------------------------------------------------------- counting
    @check("C16", "#4", "count_tokens returns a non-negative int and never crashes")
    def _c16() -> None:
        if target.count_tokens is None:
            raise NotImplementedError("no count_tokens supplied")
        for history in (
            [],
            [user("")],
            [user('日本語 🎛 <tag> \\ "q"')],
            _history_with_parallel_calls(),
        ):
            n = target.count_tokens(history)
            assert isinstance(n, int) and n >= 0, f"got {n!r}"

    return report


def _first_tool_stop(target: ConformanceTarget) -> str:
    """The provider's own word for 'I want to call a tool'."""
    for raw, mapped in target.stop_reasons.items():
        if mapped is StopReason.TOOL_USE:
            return raw
    return "tool_calls"


__all__ = [
    "Check",
    "ConformanceReport",
    "ConformanceTarget",
    "WireResponse",
    "run_conformance",
]
