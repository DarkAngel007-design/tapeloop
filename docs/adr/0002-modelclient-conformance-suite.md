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

## Consequences

- Adding a provider is: implement the Protocol, pass the suite, add a row to the divergence table.
- The suite runs against recorded fixtures by default, so it is free; a `live` marker runs it
  against real endpoints when someone is paying.
- If a divergence is not in the table, the seam does not handle it. The table is the spec.
