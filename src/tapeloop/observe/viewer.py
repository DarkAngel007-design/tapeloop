"""The trace viewer: one self-contained HTML file per tape.

Static output rather than a server, for the same reason the tape is JSONL rather
than a database — a trace you can only read by running something is a trace you
cannot attach to a bug report. The file opens offline, forever, with no collector
and no daemon.

A trace is a **tree of tapes** (ADR-0021): each subagent has its own recording, so
children are rendered by the same function that renders the parent. Settling that
ADR before M9 is what makes this a recursive call rather than a second renderer.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import cast

from tapeloop.observe.cost import PriceTable
from tapeloop.observe.trace import Span, TraceSummary, build_trace

_STYLE = """
:root { --bg:#fbfbfa; --fg:#1a1a19; --dim:#6b6b68; --line:#e2e2df; --accent:#3b5bdb;
        --warn:#c2410c; --ok:#15803d; --mono: ui-monospace, SFMono-Regular, Menlo, monospace; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#16161a; --fg:#e8e8e6; --dim:#96968f; --line:#2c2c31; --accent:#8ba3f5;
          --warn:#fb923c; --ok:#4ade80; } }
* { box-sizing:border-box }
body { margin:0; padding:2rem 1.5rem 4rem; background:var(--bg);
       color:var(--fg); font:15px/1.55 system-ui, sans-serif; }
main { max-width:60rem; margin:0 auto }
h1 { font-size:1.35rem; margin:0 0 .25rem }
.meta { color:var(--dim); font-size:.85rem; margin-bottom:1.5rem }
.totals { display:flex; gap:1.5rem; flex-wrap:wrap; padding:.85rem 1rem;
          border:1px solid var(--line); border-radius:8px; margin-bottom:1.75rem;
          background:color-mix(in srgb, var(--fg) 3%, transparent) }
.totals div { font-size:.8rem; color:var(--dim) }
.totals b { display:block; font-size:1.15rem; color:var(--fg); font-family:var(--mono) }
.step { border-left:2px solid var(--line); padding:.5rem 0 .5rem 1rem; margin-left:.25rem }
.step.is-step { border-left-color:var(--accent) }
.step.is-permission { border-left-color:var(--warn) }
.step.is-compaction, .step.is-truncated { border-left-color:var(--dim) }
.hd { display:flex; gap:.6rem; align-items:baseline; flex-wrap:wrap }
.n { font-family:var(--mono); font-size:.75rem; color:var(--dim); min-width:2.5rem }
.kind { font-family:var(--mono); font-size:.75rem; color:var(--accent) }
.kind.warn { color:var(--warn) }
.tok { margin-left:auto; font-family:var(--mono); font-size:.75rem; color:var(--dim) }
.txt { margin:.35rem 0 0; color:var(--dim); font-size:.88rem }
.tools code { font-family:var(--mono); font-size:.78rem; padding:.1rem .35rem;
              border-radius:4px; margin-right:.3rem;
              background:color-mix(in srgb, var(--accent) 12%, transparent) }
details.child { margin:1rem 0 1rem 1.5rem; border:1px solid var(--line);
                border-radius:8px; padding:.6rem .9rem }
details.child summary { cursor:pointer; font-size:.85rem; color:var(--dim) }
.err { color:var(--warn) } .ok { color:var(--ok) }
footer { margin-top:3rem; color:var(--dim); font-size:.78rem;
         border-top:1px solid var(--line); padding-top:1rem }
"""


def _span_html(span: Span) -> str:
    attrs = span.attributes
    kind_class = "warn" if span.name in ("permission", "cancelled") else ""
    bits: list[str] = []

    if span.name == "step":
        tools = cast(list[object], attrs.get("tool_calls") or [])
        if tools:
            inner = "".join(f"<code>{html.escape(str(t))}</code>" for t in tools)
            bits.append(f'<p class="txt tools">{inner}</p>')
        if attrs.get("text"):
            bits.append(f'<p class="txt">{html.escape(str(attrs["text"]))}</p>')
        tokens = f"{attrs.get('input_tokens', 0)} in / {attrs.get('output_tokens', 0)} out"
    elif span.name == "tool_result":
        flag = (
            '<span class="err">error</span>'
            if attrs.get("is_error")
            else '<span class="ok">ok</span>'
        )
        bits.append(
            f'<p class="txt">{html.escape(str(attrs.get("tool", "")))} '
            f"<em>[{html.escape(str(attrs.get('effect', '')))}]</em> {flag}</p>"
        )
        tokens = ""
    elif span.name == "permission":
        bits.append(
            f'<p class="txt">{html.escape(str(attrs.get("tool", "")))} → '
            f"<b>{html.escape(str(attrs.get('verdict', '')))}</b> "
            f"<em>({html.escape(str(attrs.get('rule', '')))})</em></p>"
        )
        tokens = ""
    elif span.name == "truncated":
        bits.append(
            f'<p class="txt">{attrs.get("elided_lines", 0)} lines elided from '
            f"{html.escape(str(attrs.get('tool', '')))}</p>"
        )
        tokens = ""
    elif span.name == "compaction":
        bits.append(
            f'<p class="txt">{attrs.get("replaced", 0)} messages summarised · '
            f"{attrs.get('before_tokens', 0)} → {attrs.get('after_tokens', 0)} tokens</p>"
        )
        tokens = ""
    else:
        bits.append(f'<p class="txt">{html.escape(str(attrs)[:200])}</p>')
        tokens = ""

    return (
        f'<div class="step is-{span.name}"><div class="hd">'
        f'<span class="n">{span.step:02}</span>'
        f'<span class="kind {kind_class}">{span.name}</span>'
        f'<span class="tok">{tokens}</span></div>{"".join(bits)}</div>'
    )


def _trace_html(summary: TraceSummary, *, depth: int = 0) -> str:
    spans = "".join(_span_html(s) for s in summary.spans)
    children = "".join(
        f'<details class="child"><summary>subagent · {html.escape(c.tape.name)} '
        f"· {c.steps} steps · {c.total_input()} in / {c.total_output()} out</summary>"
        f"{_trace_html(c, depth=depth + 1)}</details>"
        for c in summary.children
    )
    return spans + children


def render(summary: TraceSummary) -> str:
    cost = str(summary.cost) if summary.cost else "—"
    unpriced = summary.cost is not None and not summary.cost.priced
    note = (
        ' <span class="err">(no price for this model — add prices.toml)</span>' if unpriced else ""
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(summary.tape.name)} — tapeloop</title>
<style>{_STYLE}</style></head><body><main>
<h1>{html.escape(summary.tape.name)}</h1>
<p class="meta">{html.escape(summary.provider or "?")} / {html.escape(summary.model or "?")}
 · {summary.steps} steps · {len(summary.children)} subagent(s)</p>
<div class="totals">
  <div>input tokens<b>{summary.total_input():,}</b></div>
  <div>output tokens<b>{summary.total_output():,}</b></div>
  <div>cost{note}<b>{html.escape(cost)}</b></div>
</div>
{_trace_html(summary)}
<footer>Generated from {html.escape(str(summary.tape))}. Self-contained: no server, no collector.
A trace you can only read by running something is a trace you cannot attach to a
bug report.</footer>
</main></body></html>
"""


def write_viewer(tape: Path, out: Path | None = None, *, prices: PriceTable | None = None) -> Path:
    summary = build_trace(tape, prices=prices or PriceTable.load())
    target = out or tape.with_suffix(".html")
    target.write_text(render(summary), encoding="utf-8")
    return target
