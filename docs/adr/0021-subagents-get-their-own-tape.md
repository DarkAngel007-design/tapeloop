# ADR-0021 — A subagent run gets its own tape

**Status:** Accepted · 2026-08-24

## Context

A subagent is spawned with a fresh context, a narrowed tool set, and a task of its own. Its output
comes back to the parent as a structured value. The question is where its steps are recorded:
nested inside the parent's tape, or in a tape of its own.

Nesting keeps one run in one file, which is appealing — until you look at what a tape is for.

## Decision

**Each subagent run writes its own tape.** The parent records a `subagent` entry naming the child
tape, the task it was given, and the structured result it returned. The child's header names its
parent, so provenance runs both ways.

The deciding argument is step keys. A subagent's keys are computed from *its own* message prefix,
not the parent's — its context is isolated, which is the entire reason to spawn one. Two
independent key-spaces in one file would force every consumer, the cache included, to know which
namespace a key belongs to, and that ambiguity is exactly the kind of thing that surfaces as an
inexplicable cache miss.

Independent keys, independent tapes.

## Consequences

- **`replay`, `fork`, `show` and `diff` work on a subagent unchanged.** Forking just the research
  step of a run and re-running it with a different prompt costs nothing extra to support, because
  a child tape is simply a tape.
- The unit of storage is a run, not a task. A task spawning ten subagents leaves eleven files in
  the tapes directory, related by name and by their `subagent` / `parent` records.
- **The M9 viewer walks references rather than parsing nesting.** A trace is a tree of tapes, and
  each node renders with the same code that renders a single run.
- A tape is no longer necessarily self-contained: reading a parent without its children shows the
  structured results but not how they were reached. `show` says how many children exist so their
  absence is visible rather than silent.
- The transcript format (ADR-0010) gains two record kinds and no structural change. Version stays 1.
