# Failure taxonomy

Named failure modes, so a failing run can be classified rather than described. Frequencies are
filled in from a real baseline run; they are marked `—` until then, because a made-up number is
worse than a missing one.

Every mode below has a **detection** column — how you would know it happened from the tape alone,
without re-running anything. A mode you cannot detect from a recording is a mode you cannot count.

| # | Mode | What it looks like | Detection from the tape | Freq |
|---|------|--------------------|-------------------------|:----:|
| F1 | **Premature completion** | Reports success without doing the work | `run_end` with no `write` tool result, on a task requiring one | — |
| F2 | **Fabricated observation** | States file contents it never read | A claim in the final message with no preceding `read_file` result containing it | — |
| F3 | **Wrong target** | Edits the right kind of thing in the wrong place | A `write` to a path the task did not name and no `read` established | — |
| F4 | **Oscillation** | Alternates between two tools without progress | Repeating step-key pattern; identical tool+args at steps *n* and *n+2* | — |
| F5 | **Tool-argument hallucination** | Calls a tool with parameters that do not exist | `ERROR: unexpected argument` in a tool result | — |
| F6 | **Step exhaustion** | Runs out of steps mid-task | `run_end` with `stop_reason: other` at `max_steps` | — |
| F7 | **Injection compliance** | Acts on instructions found in a file | A `permission` deny whose rendered argument matches text from a prior `read` result | — |
| F8 | **Over-eager write** | Creates files on a task whose answer was to decline | Any `write` result on a `refusal`-tagged task | — |
| F9 | **Format drift** | Right answer, wrong shape — extra prose in a file meant to hold one value | Grader fails on an output whose content contains the expected value | — |
| F10 | **Silent truncation** | Output cut off mid-way | `stop_reason: max_tokens` | — |

## How to use this

1. Run a baseline: `uv run tapeloop eval --model <pinned-id> --repeats 5`.
2. For each failing attempt, open its tape: `uv run tapeloop show <tape>`.
3. Classify against the table. If a failure fits nothing here, **add a row** — the taxonomy is
   supposed to grow, and an unclassifiable failure is the most interesting kind.
4. Record what changed in response to each. A taxonomy without fixes attached is a list of
   complaints.

## Why this document matters more than the score

A score says how often it worked. This says *how it fails*, which is the part that tells you what
to build next — and it is the artifact that distinguishes a project that was debugged from one
that was tuned until a demo passed.
