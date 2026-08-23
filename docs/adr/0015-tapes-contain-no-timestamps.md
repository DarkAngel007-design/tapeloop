# ADR-0015 — The tape contains no timestamps

**Status:** Accepted · 2026-08-23

## Context

M3's ship criterion is that re-running an unchanged agent is a 100% cache hit, **byte-identical**.
Any wall-clock value written into the tape defeats that immediately: two identical runs produce
two different files, and no comparison is meaningful any more.

The obvious workaround — write timestamps but exclude them from hashing — sounds fine and is a
trap. It creates two notions of equality, "the same tape" and "the same tape except the bits we
agreed not to look at", and every later feature has to remember which one it wants. Diff, cache
lookup, fixtures, and the replay-equivalence test would each need the exclusion list, and the
first one to forget it produces a silent wrong answer.

## Decision

**No timestamps anywhere in a tape.** Not in the header, not on any record.

Time is recovered from the filesystem instead: a run's identity is its filename, and when it
happened is the file's mtime. Both are facts *about* the tape rather than contents *of* it.

The header is therefore fully deterministic:

```json
{"v":1,"kind":"header","tapeloop":"0.0.0"}
```

## Consequences

- Byte-identity is a real, checkable property with no exclusion list to remember. Two runs of the
  same agent produce the same file, and `cmp` is the whole test.
- Per-step latency is not recorded at M3. It is genuinely wanted for the cost and performance
  view at M9, and will go in a **separate sidecar file** keyed by step index — never inside the
  tape. A sidecar can be deleted without losing the run, which is the correct relationship
  between a recording and its measurements.
- Anything that needs "when" must reach for the filesystem, and that inconvenience is the point:
  it keeps the question outside the format.
