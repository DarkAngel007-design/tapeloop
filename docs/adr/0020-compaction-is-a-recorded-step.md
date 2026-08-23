# ADR-0020 — Compaction is a recorded step, not a side effect

**Status:** Accepted · 2026-08-24

## Context

Compaction replaces old history with a summary. Two properties of this project make the obvious
implementation wrong.

First, **summarising is itself a model call**, and therefore nondeterministic. If it happens
outside the step machinery, a replay produces a different summary, every key after it diverges,
and replay silently stops working — the exact failure mode Contract 1 exists to prevent.

Second, compaction changes the message history, so it changes every step key after it. That is
correct and unavoidable. What is not acceptable is for it to happen invisibly, leaving a tape whose
history cannot be explained.

## Decision

**Compaction is a step.** It has a step key, its result is cached, and it is written to the tape
as a `compaction` record naming what was replaced and what replaced it.

This means:

- Replaying a compacted run reuses the *same* summary from cache. The run is reproducible.
- A tape shows exactly where the model stopped seeing raw history, so a later "why did it forget
  that" question is answerable from the recording.
- The compaction prompt is versioned. Changing it invalidates keys from the compaction point on,
  the same as changing any other prompt.

**What is never compacted:** the system prompt, the original task, and the most recent `keep_recent`
turns. Losing the task is how a long run quietly starts solving a different problem.

## Consequences

- A compaction costs a model call, so the threshold is a real trade: compact too eagerly and you
  pay for summaries you did not need.
- A tape recorded with compaction cannot be replayed by a build with a different compaction prompt.
  That is the versioning rule doing its job, not a bug.
- **Truncation is deliberately not this.** Truncating an oversized tool result is a pure,
  deterministic function of its input — no model call, no key divergence beyond the changed
  content itself — so it happens inline and needs no record beyond the elision marker the model
  can already see.
