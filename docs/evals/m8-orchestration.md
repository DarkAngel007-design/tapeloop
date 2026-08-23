# M8 — the orchestration delta

The M8 ship criterion asks for the orchestration delta "measured in either direction". Here it is,
and it points both ways depending on the workload — which is the useful result.

## Pipeline vs barrier

Two ways to run items through several stages. **Barrier**: every item clears stage 1 before any
starts stage 2. **Pipeline**: each item flows through all stages independently.

Measured with a deterministic cost model — `cost(item, stage)` is a pure function, so the numbers
are a property of the workload rather than of the machine:

| Workload | Barrier | Pipeline | Saved |
|---|---:|---:|---:|
| A different item is slowest in each stage | 30 | 12 | **18 (60%)** |
| One item is slowest in every stage | 27 | 27 | **0 (0%)** |

**The second row is the important one.** When a single item dominates every stage, pipelining
saves nothing — the slow chain is the wall-clock either way, and reaching for orchestration would
be pure overhead. The gain only appears when *which* item is slow varies by stage, because then a
barrier makes everybody wait for a different laggard each time.

This is why the default is pipeline and the guidance is "reach for a barrier only when stage N+1
genuinely needs cross-item context". Not because pipelining is always faster — it demonstrably is
not — but because a barrier's cost is *invisible*. It never fails; it only wastes.

## What was not measured

**The eval suite shows no orchestration delta, because no task in it is fan-out shaped.** Every
task is a single line of work on a single workspace. Running the suite through subagents would
measure the overhead of spawning and nothing else.

That is stated rather than papered over with a number. Measuring it properly needs a task that
genuinely decomposes — "summarise each of these twelve files and reconcile them" — and the suite
does not have one yet. Adding one is a suite change, and suite changes belong in their own commit
with their own null-model check, not bundled into a milestone that wants a favourable number.

## Cost of a subagent

A child run carries its own system prompt and its own first turn, so a fan-out of *n* children
pays that preamble *n* times. The trade is context isolation: the parent never sees the child's
exploration, only its conclusion. For a task where the exploration is large and the conclusion is
small — searching, surveying, reviewing — that trade is strongly positive. For a task where the
child does one tool call, it is strongly negative.

The runtime does not decide this for you, and does not pretend to.
