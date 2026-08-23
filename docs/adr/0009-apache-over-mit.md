# ADR-0009 — Apache-2.0 over MIT

**Status:** Accepted · 2026-08-23

## Context

The project is intended to be used by other people, including inside companies. MIT is shorter
and more familiar; Apache-2.0 is the more careful choice for anything with an ecosystem.

## Decision

Apache-2.0.

## Consequences

- **Explicit patent grant.** Contributors grant patent rights to users, and the grant terminates
  for anyone who sues over patents. MIT is silent on patents, which makes corporate legal review
  slower, not faster.
- **Explicit trademark reservation** — the licence does not hand over the project name.
- **NOTICE file requirement** for redistributors. A small cost.
- Compatible with GPLv3 in one direction only. Not expected to matter here.
