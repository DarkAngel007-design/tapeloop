# ADR-0017 — Permission decisions are events on the tape

**Status:** Accepted · 2026-08-24

## Context

The agent executes model-authored commands. Something has to decide which ones are allowed, and
three questions come with that: what granularity, where do the rules live, and does an approval
persist.

There is also a question specific to this project that does not arise in other harnesses. A
permission prompt happens *during* a run. If the decision is not recorded, replay either re-prompts
— which makes replay interactive, and therefore useless in an eval — or silently assumes an answer,
which is worse.

## Decision

**Three states, per tool and per argument.** `allow` / `ask` / `deny`. A rule matches a tool name
and an argument pattern, so `run_command(git status)` is a different rule from `run_command(*)`.
First matching rule wins; an explicit `deny` beats an explicit `allow`.

**Defaults come from the effect class** (ADR-0005), because that information already exists:

| Effect | Default |
|--------|---------|
| `pure` | allow |
| `read` | allow |
| `write` | ask |

**Rules live in `.tapeloop/permissions.toml`, per project.** A permission set is a property of a
codebase, not of a person, and putting it in the repo means it can be reviewed in a pull request
like any other security-relevant change.

**A grant given by answering a prompt is session-only** unless `--remember` is passed, which writes
it to the project file. Persisting by default would mean an approval quietly outliving the reason
it was given.

**Every decision is recorded on the tape**, as a `permission` record naming the tool, the matched
rule, and the outcome. Replay reads the decision instead of asking again.

Denials produce an ordinary tool result — `ERROR: denied by policy` — rather than an exception.
The model can read that and choose something else, which is the same errors-are-data rule the
harness has followed since M0.

## Consequences

- Replay of a run containing permission prompts is fully non-interactive, which is what makes
  evals possible at M6.
- A denial is part of the history, so it is inside the step key already. No special handling.
- **Injection defence follows from this, not from detection.** You cannot reliably spot a hostile
  instruction in a file, and a harness that claims to is lying. What you can do is ensure that
  persuading the model does not grant it capability: the dangerous action still needs a rule that
  permits it. The hostile-README test asserts exactly that, and nothing about detection.
- Argument patterns are matched against a *rendered* argument string, so a tool whose arguments are
  structured needs a documented rendering. That is a real cost, and the alternative — permissions
  at tool granularity only — is too coarse to be useful.
