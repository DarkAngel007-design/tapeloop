# ADR-0002 — A conformance suite defines what a ModelClient is

**Status:** Accepted · 2026-08-23

## Context

A Protocol says what methods exist. It cannot say that tool results must be grouped one way on
one provider and another way elsewhere. The interesting part of a provider adapter is behavioural,
and behaviour needs tests, not type hints.

## Decision

`ModelClient` is defined by a **conformance suite** every adapter must pass. The Protocol is the
signature; the suite is the contract. It covers seven known divergences, documented in
[`../explanation/provider-differences.md`](../explanation/provider-differences.md):

1. Assistant tool-call representation
2. Tool-result grouping
3. Stop-reason vocabulary
4. Token counting mechanism
5. Prompt-cache control
6. Reasoning payload handling
7. Strict-schema constraints

## Status of the implementation

Built 2026-08-24 in `src/tapeloop/providers/conformance.py`, shipped in the package rather than
in `tests/` so a third-party adapter author can import and run it. 18 checks, one per row of the
divergence table plus general invariants. `tapeloop conformance` runs them.

Two real bugs surfaced on its first run — an adapter that had been in production since M1:

- The OpenAI renderer did not order tool results against their calls. That ordering lived only in
  the tape codec, so a `Message` built in memory and handed straight to the renderer reached the
  wire unordered. ADR-0014 describes a canonical invariant; the renderer was relying on someone
  else having enforced it.
- A check for prompt-cache reporting did not exist at all, found by a test asserting that every
  documented divergence has a check behind it. Divergence #5 was in the table and verified by
  nothing.

## Consequences

- Adding a provider is: implement the Protocol, pass the suite, add a row to the divergence table.
- The suite runs against recorded fixtures by default, so it is free; a `live` marker runs it
  against real endpoints when someone is paying.
- If a divergence is not in the table, the seam does not handle it. The table is the spec.
