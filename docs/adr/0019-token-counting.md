# ADR-0019 — Token counting is exact where possible, and always labelled

**Status:** Accepted · 2026-08-24

## Context

Every context decision — truncate this result, compact now, refuse this request — depends on
knowing how many tokens something is. Until now `count_tokens` for OpenAI has been
`len(blob) // 4`, labelled in its own docstring as crude. A budget built on a 30% error either
compacts far too early, wasting quality, or blows the window, which is the failure it exists to
prevent.

`tiktoken` gives exact counts, at the cost of a dependency that downloads encoding files on first
use — awkward for a project that emphasises offline determinism, and stated as a non-goal
("not dependency-maximal").

It is also less decisive than it looks. The pinned model here is `gpt-5.4-mini-2026-03-17`, newer
than any encoding table tiktoken ships, so it falls back to a default encoding anyway. Exactness
for *this* model is not on offer from either route.

## Decision

**Optional exactness, mandatory honesty.**

- `tiktoken` is an optional extra (`pip install tapeloop[tokens]`). When importable and when it
  knows the model, counts are exact.
- Otherwise a calibrated estimator is used, and its error is *measured* against the provider's
  own reported `usage` rather than assumed.
- **Every count carries how it was produced**: `exact`, `approximate` (tiktoken, fallback
  encoding), or `estimated`. A budget decision made on an estimate is visible as such, in the
  logs and on the tape.

The estimator is calibrated from real data: the M6 baseline recorded actual input tokens across
105 runs, and a test asserts the estimator stays within a stated error band of them. When it
drifts, that test fails — which is the difference between an estimate and a guess.

## Consequences

- The dependency list stays at two for the default install.
- `TokenCount` carries `method`, so nothing downstream can silently treat an estimate as a
  measurement.
- The error band is a committed number that can regress, not a comment.
- Provider-reported `usage` remains the ground truth after the fact; counting is only needed
  *before* a call, to decide whether to make it.
