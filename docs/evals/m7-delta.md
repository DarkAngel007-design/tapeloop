# M7 delta — what context management changed

Comparing [`evals/baseline-2026-08-24/`](../../evals/baseline-2026-08-24/) (M6, no context
management) against [`evals/m7-2026-08-24/`](../../evals/m7-2026-08-24/) (M7, budget enabled).
Same model, same seeds, same suite plus one new task.

## The claim

**Cost, not correctness.** On this model M7 changes almost nothing about *what* the agent gets
right, and a great deal about what it costs to get there.

| | M6 | M7 |
|---|---|---|
| deterministic, 18 shared tasks | 0.911 ± 0.268 | **0.911 ± 0.268** |
| `needle-in-a-big-file`, input tokens per run | 289,056 | **12,615** |

Identical accuracy on every shared task. A 95.6% reduction in tokens on the task that creates
context pressure.

## Why the headline numbers are not the comparison

The published headline moved from 18 to 19 deterministic tasks between runs, so comparing the two
headline means directly would be comparing different things. The row above is the **18 tasks
present in both**, and on those the pass counts are identical task-for-task — `count-with-exclusions`
2/5, `impossible-request` 0/5, everything else 5/5, in both runs.

## The judged score improved, and it means nothing

| Task | M6 | M7 | judge agreement |
|---|---|---|---|
| `explain-code` | 5/5 | 5/5 | 0.93 → 1.00 |
| `propose-refactor` | 5/5 | 5/5 | 1.00 → 1.00 |
| `summarise-data` | **3/5** | **5/5** | **0.87 → 0.87** |

The judged headline moved 0.867 → 1.000, entirely on `summarise-data`. **This is not an
improvement.** The rubric did not change, the answers were equivalent, and the judge's agreement
with itself is unchanged at 0.87 — it simply landed on a different majority verdict the second
time. The row is flagged unreliable in both runs.

Reporting this as an M7 win would have been the easiest sentence in the project to write, and
false. That the harness makes it visible rather than plausible is the entire argument for
measuring judge agreement (ADR-0018).

## Where the saving comes from

`needle-in-a-big-file` puts a 558 KB log (~155k tokens) in the workspace with the answer in the
middle.

Without a budget the model read the whole file — it did not fail, because this model's window is
large enough to absorb it. It answered correctly and spent **289,056 input tokens** doing so.

With a budget the read is capped at 4,000 tokens, the middle is elided with a visible marker, and
the agent searches instead. Same correct answer, one extra step, **12,615 tokens**.

That is the honest shape of the result on a large-window model: context management is not what
makes the task possible, it is what makes it affordable. On a smaller window it *is* what makes it
possible — proven separately and deterministically by
`test_ship_criterion_a_task_that_died_on_context_now_completes`, which uses a client with a hard
limit and needs no credits.

## What did not change

No task regressed. Truncation is a pure function of its input, so it cannot introduce variance;
compaction never fired in this suite because no task ran long enough to reach 75% of the window.
Compaction's correctness is covered by tests, not by this run — a fact worth stating rather than
letting the passing table imply coverage it does not have.
