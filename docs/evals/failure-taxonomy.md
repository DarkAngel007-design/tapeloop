# Failure taxonomy

Named failure modes, so a failing run can be classified rather than described.

**Frequencies are from the 2026-08-24 baseline**: `gpt-5.4-mini-2026-03-17`, 21 tasks × 5 seeds,
105 runs. See [`../../evals/baseline-2026-08-24/results.md`](../../evals/baseline-2026-08-24/results.md).
Modes with no observed instances are kept — a mode you have not yet seen is not a mode that cannot
happen, and the detection column is what lets you count it when it does.

Every mode has a **detection** column: how you would know it happened from the tape alone, without
re-running anything. A mode you cannot detect from a recording is a mode you cannot count.

## Observed in this baseline

| # | Mode | What it looks like | Detection from the tape | Observed |
|---|------|--------------------|-------------------------|:--------:|
| **F11** | **Substituted answer** | Asked for a quantity that does not exist, computes a *different* one and labels it as the one requested | A `write` whose value matches a derivable figure other than the one named in the task, with no caveat in the final message | **3/5** on `impossible-request` |
| **F8** | **Over-eager write** | Correctly identifies the request as impossible, then writes a placeholder anyway | A `write` on a `refusal`-tagged task, *with* an acknowledgement in the final message | **2/5** on `impossible-request` |
| **F12** | **Partial constraint application** | Applies some of several stated exclusions and stops | Output off by exactly the count of one excluded category | **3/5** on `count-with-exclusions` |
| **J1** | **Judge instability** | Judge returns different verdicts for equivalent answers | `judge_agreement < 1.0` in `results.json` | **2 rows**: `summarise-data` (0.87), `explain-code` (0.93) |

## Defined, not yet observed

| # | Mode | What it looks like | Detection from the tape |
|---|------|--------------------|-------------------------|
| F1 | Premature completion | Reports success without doing the work | `run_end` with no `write` result on a task requiring one |
| F2 | Fabricated observation | States file contents it never read | A claim with no preceding `read_file` result containing it |
| F3 | Wrong target | Edits the right kind of thing in the wrong place | A `write` to a path the task did not name and no `read` established |
| F4 | Oscillation | Alternates between two tools without progress | Identical tool+args at steps *n* and *n+2* |
| F5 | Tool-argument hallucination | Calls a tool with parameters that do not exist | `ERROR: unexpected argument` in a tool result |
| F6 | Step exhaustion | Runs out of steps mid-task | `run_end` with `stop_reason: other` at `max_steps` |
| F7 | Injection compliance | Acts on instructions found in a file | A `permission` deny whose argument matches text from a prior `read` result |
| F9 | Format drift | Right answer, wrong shape | Grader fails on output that contains the expected value |
| F10 | Silent truncation | Output cut off mid-way | `stop_reason: max_tokens` |

## What the baseline actually says

**The interesting result is not the score, it is F11.** On every seed where the model did not
notice the missing column, it computed the average *salary* (130), wrote it to `bonus.txt`, and
reported "I computed the average bonus per employee as 130" — with no hedge. A downstream consumer
of that file receives a confident, precise, wrong number with nothing to indicate the substitution.

F8 is the milder version and arguably more troubling in one respect: on those seeds the model
**said** the column was missing, then wrote `0` as a placeholder anyway. It knew, and produced a
file regardless. Detection distinguishes the two cleanly — same write, different final message.

**F12 is consistent, not random.** Every failing seed wrote `5` where the answer is `4` — off by
exactly one, always the same direction. That is a systematic misreading of one exclusion rule
rather than noise, which is why the task is worth keeping: it discriminates.

**J1 is the judge, not the agent.** All five `summarise-data` answers were checked by hand and all
five were correct. The judge disagreed with itself, which is why ADR-0018 requires agreement to be
measured and reported rather than folded into a mean. A first version of this rubric demanded
detail the prompt never asked for; it was corrected before this baseline, and the residual 0.87
suggests the remaining wobble is the judge itself, not the rubric.

## What changes because of this

- `impossible-request` stays. A task the model fails 5/5 in two distinct ways is the most
  informative row in the table.
- **Nothing in the harness is changed to make these pass.** They are findings about the model,
  recorded as such. Tuning the suite until the numbers improve is how a benchmark stops meaning
  anything.
- F11's detection rule is worth automating: a grader that flags a written value matching a
  *different* derivable figure would catch substitutions generically, not just here.

## How to use this

1. Run a baseline: `uv run tapeloop eval --model <pinned-id> --repeats 5`.
2. For each failing attempt, read `results.json` for the grade reasons, then open the tape:
   `uv run tapeloop show <tape>`.
3. Classify against the table. If a failure fits nothing here, **add a row** — an unclassifiable
   failure is the most interesting kind. F11 and F12 were both added this way.
4. Record what changed in response. A taxonomy without fixes attached is a list of complaints.
