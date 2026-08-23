# ADR-0005 — Three effect classes, defaulting to `write`

**Status:** Accepted · 2026-08-23

## Context

Replay is only sound if the runtime knows which tools touch the world. Serving a cached result
for a tool that mutated something is a silent lie; re-executing a tool that charged a credit card
is worse.

## Decision

Every tool declares one of three classes:

| Class   | Meaning                                          | On replay                                     |
|---------|--------------------------------------------------|-----------------------------------------------|
| `pure`  | Same input → same output; no observation, no mutation | Always served from cache                  |
| `read`  | Observes external state, mutates nothing         | Cached by default; `--fresh` re-executes      |
| `write` | Mutates filesystem, network, or database         | Policy: `cache` (default) · `reexecute` · `halt` |

An **undeclared tool is treated as `write`** — the most conservative class.

Why three and not two: collapsing `pure` and `read` loses the ability to re-run observations
against a changed world, which is the single most useful thing during debugging. Why not five:
finer distinctions (idempotent-write, append-only) did not change any replay decision.

## Consequences

- Misdeclaring a tool is the one way to silently corrupt a replay. The conservative default plus
  a lint rule for undeclared tools is the guard.
- Never widen a tool's class to make a test pass. That is written into `AGENTS.md`.
