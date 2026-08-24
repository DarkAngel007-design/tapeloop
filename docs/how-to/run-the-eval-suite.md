# Run the eval suite

```bash
tapeloop eval --model <dated-model-id> --judge-model <dated-model-id> --repeats 5
```

Results land in `evals/latest/` — a `results.md` table and a `results.json` carrying
every judgment verbatim, alongside the workspace and tape of every attempt, so any row
can be opened rather than argued about.

**Use dated model ids.** `gpt-4o-mini` and `gpt-4o-mini-2024-07-18` are different
numbers, and a table that cannot say which is not a baseline.

## Read the output correctly

Two rules the report enforces, both easy to get wrong:

**Spread is the result, not decoration.** A single run is high-variance; one pass is an
anecdote you will end up quoting. Every task runs at *n* seeds and the table shows both
mean and disagreement between them.

**Judged and deterministic are never blended.** A reader who distrusts LLM judging must
be able to discount that half without recomputing anything. Judged rows also carry
`judge_agreement` — and a judge that disagrees with itself marks the row unreliable
rather than being averaged into silence.

That last one is not hypothetical: one task in this suite has scored 3/5, 5/5 and 4/5
across three runs on answers verified correct by hand. See the
[failure taxonomy](../evals/failure-taxonomy.md).

## Comparing against a baseline

Compare **shared tasks only**. Headline means across different task sets are not
comparable — a mistake documented in the [M7 delta](../evals/m7-delta.md).

A move greater than one spread is investigated before merging, not explained afterwards.

## Adding a task

Every new task must pass the null-model check:

```bash
uv run pytest -k passable_by_doing_nothing
```

That runs the whole suite against a model that does nothing at all. **Anything that
passes is a task whose grader tests nothing.** It caught a real one: a grader asserting
a file still contained text its own setup had written, so an agent doing absolutely
nothing scored 1.0.

Grade the workspace, not the agent's account of itself. Reporting success it did not
achieve is the commonest failure mode there is, and a grader reading the final message
cannot tell the difference.
