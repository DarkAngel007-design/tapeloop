# ADR-0008 — Exact-string replacement for the edit tool

**Status:** Accepted · 2026-08-23

## Context

Three ways to let a model change a file, each failing differently:

- **Unified diff** — compact, but models produce diffs with wrong line numbers and wrong context,
  and a diff that does not apply gives a useless error.
- **Whole-file rewrite** — always applies, but costs the whole file in output tokens and silently
  drops content the model did not think to repeat.
- **Exact-string replacement** — the model quotes the text to replace and the text to replace it
  with.

## Decision

Exact-string replacement, with two invariants:

1. **Read-before-edit** — a file must have been read in this run before it can be edited. Without
   this the model edits from imagination.
2. **Uniqueness** — the search string must match exactly once, or the tool errors and asks for
   more context. Ambiguous matches are how the wrong function gets edited.

Plus an **mtime check**: if the file changed since it was read, refuse and require a re-read.

## Consequences

- More round trips than a diff for large refactors. Accepted.
- The error messages are part of the design — "matched 3 times, add surrounding context" is what
  makes the model recover on the next step instead of retrying identically.
