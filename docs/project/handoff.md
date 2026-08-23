# Resuming in a new session

For picking this up cold — a different machine, a different account, a new assistant with no
memory of the project.

## The prompt to paste

```
I'm continuing work on tapeloop, a Python agent runtime with deterministic replay.
The repo is at <path>.

Read these first, in order:
  1. docs/project/charter.md   — what we're building and what's out of scope
  2. docs/project/state.md     — exactly where we are and the next action
  3. ROADMAP.md                — milestones and their ship criteria
  4. AGENTS.md                 — the rules for changing code here
  5. docs/adr/README.md        — the decision index; read any ADR a task touches

Then confirm the working state by running:
  uv sync && uv run pytest && uv run ruff check . && uv run pyright

Tell me what you found and what you think the next action is BEFORE changing anything.
```

That last line matters. A fresh session that starts editing before confirming the tests pass
cannot tell its own breakage from pre-existing breakage.

## What a successor must not do

- **Do not edit a decided ADR.** Supersede it with a new one. The record of what was believed
  and why is worth more than a tidy list.
- **Do not relitigate the charter's non-goals.** They were decided; the reasoning is written down.
- **Do not refactor `m0/`.** It is a frozen teaching artifact. Its ugliness is deliberate and
  `m0/README.md` explains exactly which parts are bad on purpose.
- **Do not widen a tool's effect class to make a test pass.** That silently breaks replay.
- **Do not weaken a ship criterion to close a milestone.** Several are executable tests; if one
  fails, the milestone is not done. Trim the code, not the criterion.

## What to update when finishing a session

1. `docs/project/state.md` — the whole point. Current milestone, what moved, next action.
2. `ROADMAP.md` — tick a milestone only when its criterion is *verified*, and record how.
3. A new ADR if any decision was made.
4. `CHANGELOG.md` if anything user-visible changed.

## If you are the author

`LOGBOOK.md` is your private KT journal and is gitignored, so it is not in a fresh clone. If you
are moving machines and want it, copy it out of band. Everything a *successor* needs is already
in this folder — the logbook holds what confused you, which is valuable to you and to nobody else.
