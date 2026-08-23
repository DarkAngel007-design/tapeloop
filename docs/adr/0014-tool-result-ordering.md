# ADR-0014 — Tool results are ordered by their calls, not by arrival

**Status:** Accepted · 2026-08-23

## Context

A step can produce several tool calls, executed in parallel. Their results must go on the tape
in *some* order, and that order is hashed into the step key (ADR-0004). Pick wrong and identical
re-runs miss the cache, which presents as "replay is broken" and is miserable to debug.

Three candidates:

- **Arrival order.** What actually happened. Also genuinely nondeterministic — with concurrent
  execution the fast tool finishes first, and which one is fast varies run to run. Unusable.
- **Sorted by `call_id`.** Stable, but arbitrary: ids are provider-generated opaque strings, so
  the resulting order carries no meaning and scrambles the model's own sequencing.
- **The order of the calls in the preceding assistant message.** Also stable, and it means
  something.

## Decision

**Tool results are canonically ordered by the position of their corresponding `tool_call` in the
assistant message that requested them.**

This order comes from the model's own output, which is already on the tape, so it is stable
without being arbitrary. Both providers give a definite call order — OpenAI by array position
and stream index, Anthropic by content-block position — so the rule is provider-independent
without either provider's layout leaking in.

Execution order remains free. Tools may run concurrently and finish in any order; only the
*recorded* order is fixed.

## Consequences

- Serialization sorts results against the call list, and a result whose `call_id` matches no call
  is a corrupt tape, not something to tolerate quietly.
- Timing information is deliberately lost. That is correct: how long a tool took is observability
  (M9), not part of what the run *was*. Recording it here would put a nondeterministic value
  inside a hashed structure.
- A future parallel executor cannot change replay behaviour by changing scheduling, which is
  exactly the property that makes concurrency safe to add later.
