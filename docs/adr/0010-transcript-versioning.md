# ADR-0010 — Transcript schema versioning and migration policy

**Status:** Accepted · 2026-08-23

## Context

The moment anyone has a saved tape, the tape format is a compatibility promise. A run recorded in
January must still replay in December, or replay is a party trick rather than a tool.

## Decision

Every tape carries a `format_version` on its first line. The rules:

- A **breaking change ships with a migration**, in `how-to/migrate-a-transcript-version.md`, or it
  does not ship.
- Migrations are forward-only and non-destructive: they write a new tape, never rewrite in place.
- Reading a tape with an unknown future version is a clear error naming the version, never a
  best-effort parse.
- `reference/transcript-format.md` is the normative spec. Changing it requires a new ADR.

## Consequences

- Additive fields are cheap; removals and renames are expensive. This biases the format toward
  being slightly verbose, which is the right trade for an archival log.
- Test fixtures must include at least one tape from every historical version, committed to the
  repo, and the suite replays all of them.
