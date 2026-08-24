# Replay is not resume

Two things people want from a tape look similar and are not:

> *"What would the model have done if I changed the prompt?"*
> *"My four-hour run died at minute 200 — continue it."*

The first wants speed and cares nothing for real side effects. The second needs the
world to actually be in the right state. Conflating them produces a run that appears to
succeed while the filesystem quietly disagrees with the history, so they are separate
commands with separate guarantees.

## Replay — a simulation

`replay` and `fork` serve cached results for `write` tools **without touching the
world**. The filesystem is *not* in the state the tape implies.

That is exactly right for every prompt experiment, every eval, every fork: you are
asking what the model would do, not rebuilding what it did.

It is also why a fork classifies itself:

- **`faithful`** — no `write` in the replayed prefix. Nothing was mutated, so the fork
  is genuinely what would have happened.
- **`simulated`** — a `write` was replayed. The report names the specific tools and
  steps, because a warning that does not say *which* trains people to ignore warnings.

`--require-faithful` turns simulated into a refusal. Evals use it: a silently simulated
run poisons a results table, and one bad number discredits the whole thing.

## Resume — real

`resume` serves **nothing** from cache. Every step it takes is a real call with real
effects, against the workspace as it actually is.

Which is why it does **not** restore a snapshot by default. When a long run dies, the
workspace already holds everything that run produced — that state *is* what you are
resuming. Rewinding would delete the work you are trying to continue.

The original ADR got this wrong, assuming rewinding was the normal case. Implementing
it corrected the decision rather than the other way round.

## Restoring, when you actually mean it

`--restore-from N` answers the third question: *"it went wrong around step 12, put the
workspace back and let it try again."* That needs snapshots, it destroys work done
after that step, and the report says so.

It also upgrades a fork: a `simulated` fork whose workspace has been restored to the
matching step becomes `faithful`, because the replayed writes are no longer pretend.

## Why not one command with a flag

Because the failure mode is a replay that appears to succeed while the working tree
disagrees with the tape, and a flag is too easy not to pass. Two commands, two names,
two pages.

| | `replay` / `fork` | `resume` |
|---|---|---|
| Cache | Serves from it | Uses none |
| Effects | Simulated | Real |
| Workspace | Untouched | As it is, unless you say otherwise |
| For | Experiments, evals, A/B | Continuing after a crash |

See [ADR-0006](../adr/0006-replay-is-not-resume.md) and
[ADR-0016](../adr/0016-fork-declares-its-own-soundness.md).
