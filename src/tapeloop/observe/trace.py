"""OpenTelemetry spans over a tape.

Deliberately built *from the tape* rather than instrumented into the loop. The tape
already records everything a span would carry — step keys, usage, effect classes,
permission decisions, truncations, compactions, subagent links — so instrumenting
the loop a second time would create a parallel source of truth that could disagree
with the recording.

It also means a run recorded last week can be traced today, which live
instrumentation can never do.

OpenTelemetry is optional. Without it, the same walk produces plain span records
that the viewer renders, so the tape stays useful with no dependencies at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from tapeloop.observe.cost import Cost, PriceTable
from tapeloop.record.jsonl import read_records


@dataclass(slots=True)
class Span:
    name: str
    step: int
    attributes: dict[str, Any] = field(default_factory=dict[str, Any])
    children: list[Span] = field(default_factory=list["Span"])

    def walk(self) -> list[Span]:
        out: list[Span] = [self]
        for child in self.children:
            out.extend(child.walk())
        return out


@dataclass(slots=True)
class TraceSummary:
    tape: Path
    model: str = ""
    provider: str = ""
    spans: list[Span] = field(default_factory=list[Span])
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost: Cost | None = None
    children: list[TraceSummary] = field(default_factory=list["TraceSummary"])
    """Subagent traces. A trace is a tree of tapes (ADR-0021), not a nested document."""

    @property
    def steps(self) -> int:
        return sum(1 for s in self.spans if s.name == "step")

    def total_input(self) -> int:
        return self.input_tokens + sum(c.total_input() for c in self.children)

    def total_output(self) -> int:
        return self.output_tokens + sum(c.total_output() for c in self.children)


def build_trace(tape: Path, *, prices: PriceTable | None = None, _depth: int = 0) -> TraceSummary:
    """Read a tape into spans, following `subagent` records into child tapes."""
    table = prices or PriceTable()
    summary = TraceSummary(tape=tape)
    if _depth > 8:  # a cycle would mean a corrupt tape; refuse rather than recurse forever
        return summary

    for record in read_records(tape):
        kind = record["kind"]
        data = cast(dict[str, Any], record.get("data") or {})
        step = int(record.get("step", 0))

        if kind == "run_start":
            summary.model = str(data.get("model", ""))
            summary.provider = str(data.get("provider", ""))
        elif kind == "step":
            usage = cast(dict[str, Any], data.get("usage") or {})
            summary.input_tokens += int(usage.get("input_tokens", 0))
            summary.output_tokens += int(usage.get("output_tokens", 0))
            summary.cached_tokens += int(usage.get("cached_input_tokens", 0))
            message = cast(dict[str, Any], data.get("message") or {})
            calls = cast(list[dict[str, Any]], message.get("tool_calls") or [])
            summary.spans.append(
                Span(
                    name="step",
                    step=step,
                    attributes={
                        "key": record.get("key", "")[:12],
                        "stop_reason": data.get("stop_reason", ""),
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "tool_calls": [c["name"] for c in calls],
                        "text": (message.get("text") or "")[:200],
                    },
                )
            )
        elif kind in ("tool_result", "permission", "truncated", "compaction", "cancelled"):
            summary.spans.append(Span(name=kind, step=step, attributes=dict(data)))
        elif kind == "subagent":
            child_name = data.get("tape")
            summary.spans.append(Span(name="subagent", step=step, attributes=dict(data)))
            if isinstance(child_name, str):
                child_path = tape.parent / child_name
                if child_path.exists():
                    summary.children.append(
                        build_trace(child_path, prices=table, _depth=_depth + 1)
                    )

    summary.cost = table.cost(
        summary.model,
        input_tokens=summary.input_tokens,
        output_tokens=summary.output_tokens,
        cached=summary.cached_tokens,
    )
    return summary


def export_otel(summary: TraceSummary) -> int:
    """Emit to OpenTelemetry if it is installed. Returns the number of spans exported.

    Optional by design: the viewer needs no collector, and a project that emphasises
    working offline should not require one to see its own traces.
    """
    try:
        import importlib

        # Imported by name so the optional package's absent stubs cannot leak
        # `Unknown` into this module the way a plain `from x import y` would.
        otel: Any = importlib.import_module("opentelemetry.trace")
    except ImportError:
        return 0

    tracer = otel.get_tracer("tapeloop")
    exported = 0
    with tracer.start_as_current_span("run") as root:
        root.set_attribute("tapeloop.tape", summary.tape.name)
        root.set_attribute("tapeloop.model", summary.model)
        for span in summary.spans:
            with tracer.start_as_current_span(span.name) as s:
                for key, value in span.attributes.items():
                    s.set_attribute(f"tapeloop.{key}", str(value))
                exported += 1
    return exported
