# CLI

```bash
tapeloop <command> [options]
```

Every command mirrors the library exactly: anything the CLI does, a caller can do.

## `run`

Run a task, recording a tape.

```bash
tapeloop run "count the python files" --workspace . --tapes .tapeloop
```

| Option | Default | |
|---|---|---|
| `--model` | `$TAPELOOP_MODEL` or `gpt-4o-mini` | |
| `--workspace` | `.` | What the agent can see |
| `--tapes` | `.tapeloop` | Where tapes go — keep it outside the workspace |
| `--tape` | | An explicit path instead |
| `--system` | | Override the system prompt |
| `--quiet` | | No streaming output |

## `show`

Summarize a tape: model, steps, keys, tools, and how many writes happened.

```bash
tapeloop show .tapeloop/run-001.jsonl
```

## `fork`

Branch a tape at a step and continue live. Replays the prefix from cache.

```bash
tapeloop fork run.jsonl "the task" --at 12 --system "Be terse." --dry-run
```

| Option | |
|---|---|
| `--at` | **Required.** Step to branch at |
| `--model` | Fork onto a different model |
| `--system` | The thing you are usually changing |
| `--require-faithful` | Refuse if the prefix contains a write |
| `--dry-run` | Report soundness, run nothing |

## `resume`

Continue a stopped run. **Nothing is served from cache** — every step is real.

```bash
tapeloop resume run.jsonl --workspace workspace --nudge "skip what is done"
```

| Option | |
|---|---|
| `--restore-from STEP` | Rewind the workspace first. **Destroys work after that step** |
| `--snapshots DIR` | Required by `--restore-from` |
| `--nudge` | One message to add before continuing |
| `--dry-run` | Report and run nothing |

## `diff`

Compare two tapes step by step, anchored on step keys. Exit 1 if they differ.

```bash
tapeloop diff a.jsonl b.jsonl
```

## `view`

Render a tape as one self-contained HTML page — no server, no collector, no external
request. Subagent runs render as a tree.

```bash
tapeloop view run.jsonl --prices prices.toml --otel
```

## `eval`

Run the task suite and write a results table.

```bash
tapeloop eval --repeats 5 --judge-model <dated-id>
```

| Option | Default | |
|---|---|---|
| `--repeats` | 5 | Seeds per task. 1 is not a result |
| `--judge-k` | 3 | Judgments per grade, to measure agreement |
| `--no-judge` | | Deterministic tasks only |
| `--no-budget` | | Disable context management, to measure its delta |
| `--only` | | One task by id |

## `conformance`

Check a `ModelClient` adapter against the contract. Exit 1 on failure.

```bash
tapeloop conformance --target openai
```

## Environment

| Variable | |
|---|---|
| `OPENAI_API_KEY` | Read from `.env` if present |
| `OPENAI_BASE_URL` | Point at Ollama, vLLM, Groq, Together, OpenRouter |
| `TAPELOOP_MODEL` | Default for `--model` |
