# ADR-0003 — JSONL as the source of truth, SQLite as an index

**Status:** Accepted · 2026-08-23

## Context

A tape must survive the library that wrote it. If reading a run requires importing tapeloop, the
tape is a lock-in format and a debugging dead end at exactly the moment you need it most.

## Decision

The tape is **append-only JSONL** on disk: one canonical event per line. SQLite may be introduced
later purely as a derived index for fast lookup across many runs.

## Consequences

- Tapes are greppable, diffable, and readable with `head` and `jq`. This matters more than speed.
- Any index is **derived and disposable** — deleting it must never lose information.
- Append-only means corrections are new events, never edits. A tape is a log, not a document.
- Large tool outputs bloat tapes. Deferred: content-addressed side storage for big blobs.
