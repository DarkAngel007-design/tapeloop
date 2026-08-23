# ADR-0018 — LLM-as-judge, pinned and measured

**Status:** Accepted · 2026-08-24

## Context

Many useful agent tasks have no single correct output. "Refactor this to be clearer" cannot be
graded by string equality. The standard answer is LLM-as-judge, which introduces a nondeterministic
component into the one part of the system that has to be trustworthy — the part producing numbers
you will publish.

The alternative is to grade only deterministically-checkable tasks. That is honest but narrow, and
it biases the suite toward exactly the work agents are already good at, which makes the resulting
number flattering and useless.

## Decision

Judging is allowed, under four conditions.

**1. The judge model is pinned.** Its id lives in the suite config and is written into every
results file. A number produced by `gpt-4o-mini-2024-07-18` and a number produced by whatever
`gpt-4o-mini` points to next quarter are different numbers, and a results table that cannot say
which is not a baseline.

**2. The judgment is recorded.** Verdict and reasoning go into the results, not just a boolean. A
score you cannot audit is a score you cannot defend, and the reasoning is where a bad rubric shows
itself.

**3. The judge is measured, not assumed.** Each judged task is judged `k` times and the suite
reports **judge agreement** alongside the score. A task where the judge disagrees with itself is
reported as unreliable rather than averaged into silence. If the judge is nondeterministic, that
nondeterminism is data.

**4. Judged and deterministic results are reported separately.** Never a single blended headline
number. A reader who distrusts LLM judging must be able to discount that half without recomputing
anything.

The judge prompt is versioned in the repo like any other prompt, and changing it invalidates the
baseline exactly as a code change would.

## Consequences

- A results table carries `judge_model`, `judge_prompt_version`, `judge_agreement`, and separate
  deterministic and judged sub-scores. More columns, and each one answers a question a sceptical
  reader will actually ask.
- Judging costs tokens per task per repeat, so `k` is a real budget decision. Default 3: enough to
  see disagreement, cheap enough to run often.
- Every eval fork passes `--require-faithful` (ADR-0016). A silently simulated run inside a graded
  suite produces a number nobody can trust, and one bad number discredits the whole table.
- **The suite is written by hand, and held out.** A public benchmark the model memorized measures
  recall, not this harness.
