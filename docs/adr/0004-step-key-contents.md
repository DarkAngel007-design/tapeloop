# ADR-0004 — What goes into a step key

**Status:** Accepted · 2026-08-23

## Context

Replay depends on knowing whether a step's inputs changed. That question is answered by a hash,
and the hash's contents decide what counts as "the same run."

## Decision

```
key(n) = sha256(
    provider_id,             # "openai" | "anthropic" | "ollama"
    model_id,
    request_params,          # max_tokens, reasoning/thinking, effort, ...
    canonical(tool_schemas),
    canonical(events[0..n]), # the neutral tape, not wire format
)
```

Explicitly **excluded**: timestamps, run ids, machine identity, and anything else that would make
a byte-identical re-run miss.

## Consequences

- Change anything and every step from that index onward misses; every step before it hits. This
  is the same prefix property that governs server-side prompt caching, so the two reinforce
  each other rather than fight.
- Provider and model are *inside* the key, so cross-provider replay is a miss by definition.
  That is arithmetic, not a limitation — a different model is a different run. The useful
  operation across providers is **fork**, not replay. See [ADR-0011](0011-canonical-event-log.md).
- Canonical serialization (sorted keys, stable separators, explicit float format) is now
  load-bearing. It gets its own test.
