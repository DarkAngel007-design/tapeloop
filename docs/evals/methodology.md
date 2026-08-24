# Evaluation methodology

## Why this exists

Almost every agent project reports a number from one run. Agent runs are high-variance, so one
pass is not a result — it is an anecdote you will end up quoting. This suite reports **mean ±
spread across seeds**, and reports judged and deterministic tasks separately, because those are
the two things a sceptical reader will ask for first.

## Producing a baseline

```bash
uv run tapeloop eval --model <pinned-model-id> --judge-model <pinned-judge-id> --repeats 5
```

Use **dated model ids**. `gpt-4o-mini` and `gpt-4o-mini-2024-07-18` are different numbers, and a
table that cannot say which is not a baseline (ADR-0018).

Results land in `evals/latest/results.md` alongside every workspace and tape, so any row can be
opened and inspected rather than argued about.

## The suite

`starter-v1`: 13 deterministic tasks, plus 3 judged tasks when a judge is supplied.

**Hand-written and held out.** A public benchmark the model memorized measures recall, not this
harness. That means the numbers are not comparable to anyone else's — which is the correct trade.
The purpose of this suite is to detect regressions in *this* harness and to make its failure modes
visible, not to claim a position on a leaderboard.

**Graded on the workspace, not the agent's account of itself.** An agent reporting success it did
not achieve is the most common failure mode there is, and a grader that reads the final message
cannot tell the difference.

**Two refusal tasks**, where success means declining. Without these, a suite rewards eagerness and
an agent that confidently does the wrong thing looks competent.

## Known limitations, stated

- **`refuse-injected-instruction` cannot distinguish refusal from inaction.** It detects an agent
  that *obeys* the injection, which is what it is for; it does not verify the agent read the file
  and chose correctly. Pinned by `test_no_task_is_passable_by_doing_nothing`, which exempts exactly
  this task and no other.
- **13 deterministic tasks is a small suite.** Enough to catch regressions, not enough for a
  confident absolute claim. Growing it is ongoing.
- **Judged tasks depend on the judge's rubric**, which is a prompt in this repo and therefore
  another thing that can be wrong. `judge_agreement` is reported so a wobbly rubric is visible.

## Two bounds, and what neither tells you

A task must be **impossible to pass by doing nothing** and **possible to pass by doing it
right**. Both are enforced:

```bash
uv run pytest -k passable_by_doing_nothing   # no grader is too weak
uv run pytest tests/test_eval_oracles.py     # no grader is too strict
```

The second exists because a task nobody can pass looks like a *hard* task rather than a
broken one, and would sit in the suite depressing every score for as long as nobody
checked. It also verifies the arithmetic behind the expected answers.

**Neither bound tells you whether a task discriminates.** That is a property of the task
*and the model together*, and it only shows up in a real baseline. A task both bounds
accept can still be trivial for a capable model — the first suite scored 13/13 with zero
spread and passed every structural check.

### Local models validate plumbing, not difficulty

Running the suite against a small local model is free and worth doing, but read the
result carefully. `llama3.2:3b` passed 1 of the 11 tasks added at 30 — and inspecting the
tapes showed most failures were a single step with no tool call at all, because the model
emitted its tool call as *message text*:

```
step 0: tool_calls=[]
  text: '{"name":"run_command","parameters":{"command":"cut -f 1 -d ..."}}'
```

The runtime handled that correctly, treating text as text. But the run measured the
model's tool-use ability, not the tasks' difficulty. It confirms the suite executes end
to end; it says nothing about headroom.

## Guarding the graders

The suite is run against a **do-nothing model** in CI. Any task that passes is a task whose grader
tests nothing.

This is not hypothetical: `fix-the-bug` originally asserted `calc.py` still contained
`def average` — which the setup already guaranteed — so an agent doing absolutely nothing scored
1.0. It now executes the code and asserts `average([]) == 0`. The check that caught it is
`test_no_task_is_passable_by_doing_nothing`, and it runs every time.

`docs/evals/machinery-check.md` is that run's output. **It is not a baseline** and says so at the
top of the file.

## Regression policy

A baseline is committed with the model id that produced it. A change that moves the deterministic
mean by more than one spread is investigated before merging, not explained afterwards.
