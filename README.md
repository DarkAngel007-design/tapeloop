# tapeloop

**An agent runtime that records every step, so any run can be replayed, forked, and diffed.**

> **Status: pre-alpha, M9 of M9 — the roadmap is complete.** `run`, `show`, `fork`, `diff`,
> `eval` and `view` all work, with a sandbox, permissions, context management, subagents, MCP on
> both ends, and a committed eval baseline. There is still **no stable API**: nothing is versioned
> above `0.0.0` and anything may move.

---

## The problem

Building an agent today means iterating like this:

> change one line of the system prompt → re-run the whole task → wait four minutes →
> spend eighty cents → squint at the output → repeat

The feedback loop is measured in minutes and dollars, so most people run the experiment they
can afford rather than the one they need. Every other part of software solved this with a
debugger — breakpoints, stepping, replay. Agents don't have one.

## The idea

tapeloop writes every step of a run to an append-only **tape**, and keys each step by its
content. Re-running unchanged is served entirely from the tape. Change something and only the
steps *after* the change have new keys — everything before still hits.

```bash
tapeloop run  "refactor the auth module"     # records a tape
tapeloop show .tapeloop/run-001.jsonl        # what happened, step by step
tapeloop fork .tapeloop/run-001.jsonl "refactor the auth module"          --at 12 --system "Be terse."        # branch at step 12, new prompt
tapeloop diff run-001.jsonl fork-run-001-at12.jsonl
```

`fork` replays steps 0–11 from the tape in milliseconds. Only step 12 onward costs anything.

```
$ tapeloop show .tapeloop/run-001.jsonl
run-001.jsonl: openai/gpt-4o-mini  4 steps
  tools: read_file, write_file, list_files, run_command
    0  b88630a51f94  list_files
    1  1c1ab81d7901  read_file
    2  43a5790c1259  write_file
    3  36e533199f1e  Renamed the handler and updated its two callers.
  1 write(s) — forking past them yields a simulated run
```

### Fork tells you whether it can be trusted

Replaying a cached *write* means the workspace is not in the state the history claims. So a fork
classifies itself from the effect classes it replayed, and says which case it is in:

```
$ tapeloop fork run-001.jsonl "..." --at 3
fork run-001.jsonl @ step 3 — simulated
  1 write(s) replayed from cache; the workspace does not match this history.
    step 2: write_file
  Live steps will run against the real workspace. See ADR-0006.
```

A read-only prefix reports `faithful` and proceeds silently. `--require-faithful` turns
`simulated` into a refusal — evals use it, because a silently simulated run poisons a results
table.

### Fork across providers

Because the tape stores canonical events rather than one vendor's wire format, a run recorded on
one model can be branched onto another with identical history — the comparison you actually want
when choosing a model, and normally impossible.

```bash
tapeloop fork run-001.jsonl "..." --at 12 --model claude-opus-5
```

Payloads meaningful only to the original provider are dropped, and the fork says so rather than
doing it quietly.

## Results

A baseline exists, with variance, from a suite written by hand and held out.

| | Tasks | Mean | Spread |
|---|---:|---:|---:|
| deterministic | 18 | **0.911** | ± 0.268 |
| judged | 3 | 0.867 | ± 0.231 |

`gpt-5.4-mini-2026-03-17`, 5 seeds per task, 105 runs. Judged rows are reported separately and
never blended into the headline; two were flagged unreliable because the judge disagreed with
itself. Full table and the auditable per-judgment record:
[`evals/baseline-2026-08-24/`](evals/baseline-2026-08-24/).

The score is the least interesting part. The
[failure taxonomy](docs/evals/failure-taxonomy.md) is where the work is — for instance, asked to
compute an average from a column that does not exist, the model computed the average *salary*
instead, wrote it to the requested file, and reported success with no hedge. Three times in five.

## Seeing a run

```bash
tapeloop view .tapeloop/run-001.jsonl        # writes run-001.html beside the tape
```

One self-contained file — no server, no collector, no external request. Per-step tokens and cost,
permission decisions, truncations and compactions, and subagent runs rendered as a tree. Costs come
from a `prices.toml` you supply; a model with no entry shows `—` rather than a confidently wrong
zero.

## Design

Five contracts hold the whole thing up:

1. **Determinism up to first divergence** — same tape + same code reproduces the run exactly,
   until something changes, then runs live from there.
2. **Content-addressed step keys** — a step is keyed by provider, model, params, tool schemas
   and the canonical event prefix. Change anything, and only that step onward misses.
3. **Tools declare their effects** — `pure` / `read` / `write`. Undeclared defaults to `write`,
   the most conservative class.
4. **Replay is not resume** — replay is a cached *simulation*; resume restores a workspace
   snapshot and re-executes for real. Two commands, two guarantees.
5. **The tape is provider-neutral** — canonical events, with anything the runtime can't
   interpret stored as an opaque payload and handed back verbatim.

Full reasoning lives in [`docs/adr/`](docs/adr/).

## Non-goals

Not an agent framework — no chains, no retriever abstractions, no prompt-template DSL. Not a
hosted service. Not a prompt-management product. A short dependency list is a stated feature.

## Install and run

```bash
uv sync
cp .env.example .env      # add your key
git config core.hooksPath .githooks   # enables the secret guard; git will not do this for you
uv run tapeloop run "count the python files here and write the number to count.txt"
```

Works against any OpenAI-compatible endpoint — OpenAI, Groq, Together, OpenRouter, vLLM, or a
local Ollama. Set `OPENAI_BASE_URL` to point elsewhere.

**Tapes must live outside the workspace the agent can see.** A tape inside it becomes something
the agent observes, so a directory listing differs on the second run and replay misses for no
visible reason. The default `--tapes .tapeloop` is fine as long as the agent has no reason to
list it.

### Read this before pointing it at anything you care about

**The defaults protect you from accidents, not from adversaries.** A bare `Agent(...)` has
`policy=None` and uses `SubprocessExecutor`, which means model-authored shell commands run on your
host with no permission gate and no isolation. That is deliberate — a container that silently
failed to start would be worse than one you knowingly did not use (ADR-0007) — but it is opt-in
safety, not opt-out.

For anything untrusted, attach both:

```python
Agent(..., policy=PermissionPolicy.load(Path(".tapeloop/permissions.toml")))
# and pass DockerExecutor() to your tool pack
```

See [SECURITY.md](SECURITY.md) and [the threat model](docs/explanation/threat-model.md), which
state what is *not* claimed as carefully as what is.

### M0, the teaching spike

`m0/loop.py` is the original single-file version, kept deliberately unabstracted so the protocol
is visible before anything hides it. `m0/README.md` lists exactly which parts are bad on purpose
and which milestone replaced each one.

## License

Apache-2.0.
