# Project docs — start here

These four files exist so someone (or some agent) with **no context at all** can pick this
project up and be productive in about ten minutes.

They deliberately **do not restate** the README, ROADMAP, or ADRs. Duplicated documentation
drifts, and a drifted handoff is worse than no handoff. Everything here either points at a
source of truth or contains something that lives nowhere else.

## Read in this order

| # | File | What it answers | Changes |
|---|------|-----------------|---------|
| 1 | [charter.md](charter.md) | What are we building, for whom, and what is explicitly out of scope? | Rarely |
| 2 | [state.md](state.md) | Where exactly are we *right now*? What is the next action? | **Every session** |
| 3 | [glossary.md](glossary.md) | What do these words mean? | Occasionally |
| 4 | [handoff.md](handoff.md) | How do I resume in a brand-new session? | Rarely |

## Sources of truth elsewhere

| Question | File |
|----------|------|
| What is this project, for a user? | [`README.md`](../../README.md) |
| What is built and what is next? | [`ROADMAP.md`](../../ROADMAP.md) |
| Why was this decided this way? | [`docs/adr/`](../adr/) — numbered, immutable |
| What are the rules for changing code? | [`CLAUDE.md`](../../CLAUDE.md) |
| How do providers differ? | [`docs/explanation/provider-differences.md`](../explanation/provider-differences.md) |

## The one thing that does not travel

`LOGBOOK.md` is the author's private learning journal and is **gitignored on purpose** — it
records what was confusing, not what was decided. It will not be in a fresh clone, and that is
correct. Everything from it that a successor genuinely needs has been lifted into
[glossary.md](glossary.md) and [state.md](state.md).
