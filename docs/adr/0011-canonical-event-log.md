# ADR-0011 — Canonical event log, with opaque provider payloads

**Status:** Accepted · 2026-08-23

## Context

If the tape stores a provider's wire format, it is not portable, and a run recorded against one
model can never be branched onto another. But the runtime also cannot fully *understand* every
provider — reasoning blobs, encrypted items, and vendor-specific fields are meaningful only to the
provider that produced them.

## Decision

The tape stores a **canonical event log**. Each `ModelClient` renders canonical events out to its
API shape and parses responses back in.

Anything the runtime cannot interpret is stored as an **opaque payload**: kept verbatim, tagged
with the provider that produced it, and handed straight back to that provider on the next turn.
The harness never inspects, rewrites, or migrates an opaque payload.

## Consequences

- **Cross-provider fork works.** `tapeloop fork run_8f2 --at 12 --model claude-opus-5` branches a
  real run onto a different model with identical history — the comparison people actually want
  when choosing a model, normally impossible because history is locked in one vendor's format.
- Opaque payloads are dropped when forking to a *different* provider, because they are meaningless
  there. This must be surfaced in the fork output, not silently swallowed.
- Nothing outside `src/tapeloop/providers/` may reference a wire format. Enforced by review and
  written into `CLAUDE.md`.
