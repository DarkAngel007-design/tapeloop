# ADR-0016 — Fork declares its own soundness from the effects it replayed

**Status:** Accepted · 2026-08-23

## Context

Forking a tape at step *n* replays steps 0..n from cache and runs live from there. If any replayed
step included a `write` tool, the workspace is **not** in the state that history claims — the
model has been told it created a file that does not exist.

The danger is not the replayed prefix; nothing executes there. It is the *live* steps afterwards,
which run against a workspace that disagrees with the conversation. A `read_file` on something the
history says was written returns stale content or an error, and the fork quietly stops being a
test of the thing you changed.

Three obvious answers, all wrong on their own:

- **Refuse without a snapshot.** Correct, and it makes fork unusable until M5 — which removes the
  entire reason M4 exists.
- **Warn always.** Cries wolf. Most forks in practice replay only `read` steps and are perfectly
  faithful; a warning on those trains people to ignore it.
- **Simulate silently.** Fast, and produces confidently wrong eval numbers.

The effect classes from ADR-0005 already carry exactly the information needed to tell these apart,
and until now nothing has used them.

## Decision

**A fork classifies its own soundness from the effect classes in the prefix it replayed, and says
so.** Two tiers:

| Tier | Condition | Behaviour |
|------|-----------|-----------|
| `faithful` | No `write` tool in steps 0..n | Proceed silently. The workspace was never mutated, so the fork is genuinely what would have happened. |
| `simulated` | One or more `write` results replayed | Proceed, but report it loudly — naming the specific tools and step numbers — and record the tier on the new tape. |

`--require-faithful` promotes `simulated` to a refusal. Evals use it: a silently simulated run
poisons a results table, and a number you cannot trust is worse than a number you do not have.

The forked tape carries a `fork` record naming its parent tape, the fork step, and the tier, so a
forked run can never be mistaken for a fresh one. Provenance travels with the recording.

The same reporting path covers cross-provider forks, where opaque payloads are dropped because
they are meaningless to the new provider (ADR-0011). Dropping them is correct; doing it silently
is not.

## Consequences

- Fork is useful now, at M4, without waiting for snapshots.
- The effect classes stop being bookkeeping and start doing work, which is also the first real
  test of whether the three-class split from ADR-0005 was the right cut.
- **M5 upgrades a tier rather than changing an interface.** With workspace snapshotting, a
  `simulated` fork becomes `faithful` by restoring state before the live steps. Nothing in the
  CLI or the report shape has to change.
- A tool declared `read` that actually writes silently produces a `faithful` label on a fork that
  is not. That is the same trust the whole replay model already places in effect declarations —
  which is why an undeclared tool defaults to `write`, and why `CLAUDE.md` forbids widening a
  class to make a test pass.
