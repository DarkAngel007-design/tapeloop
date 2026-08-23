# ADR-0006 — Replay and resume are separate operations

**Status:** Accepted · 2026-08-23

## Context

Two things people want from a tape look similar and are not:

- "What would the model have done if I changed the prompt?"
- "My four-hour run died at minute 200; continue it."

The first wants speed and cares nothing for real side effects. The second needs the world to
actually be in the right state.

## Decision

Two commands, two guarantees, two documentation pages.

**`replay`** is a *simulation*. Cached `write` results are returned without touching the world,
so the filesystem is **not** in the state the tape implies. Correct for every prompt experiment,
every eval, every fork.

**`resume`** is *real*. It restores a workspace snapshot taken at step *n* and re-executes forward
for genuine effects. Slower, requires the sandbox (M5), and is what you use after a crash.

## Consequences

- One command with a `--real` flag was rejected: the failure mode is a replay that appears to
  succeed while the working tree quietly disagrees with the tape, and a flag is too easy to
  not-pass.
- `resume` blocks on M5, because snapshotting is a sandbox capability.
- `explanation/replay-vs-resume.md` is mandatory reading in the docs, not an appendix.
