# M0 — the bare loop

One file, no abstractions. It exists so the agent protocol is visible before anything hides it.

```bash
uv run python m0/loop.py "count the python files here and write the number to count.txt"
```

## What is deliberately bad here

| In `loop.py` | Replaced by |
|--------------|-------------|
| Tool schemas written as literal dicts, duplicating the Python signatures | M1 — registry generates them from type hints |
| `dispatch()` is an if/elif chain | M1 — registry dispatch |
| No effect classes; every tool is equally trusted | M1 — `pure` / `read` / `write` |
| Nothing is recorded; the run vanishes on exit | M3 — the tape |
| `subprocess` with `shell=True` on the host | M5 — the `Executor` seam and a Docker backend |
| One blocking request per step, no streaming, no retry | M2 |

**Do not refactor this file.** When M1 replaces it, the diff is the lesson.

## The two things it gets right

Both are load-bearing, and both are what the tests in `tests/test_m0.py` actually check:

1. **The assistant message is appended verbatim.** Rebuilding it by hand is how you silently lose
   `tool_calls`, refusals, and provider-specific fields.
2. **One `role:"tool"` message per tool call, each carrying its `tool_call_id`.** Merging or
   reordering them breaks the pairing the model relies on. (Anthropic requires the exact opposite
   layout — see `docs/explanation/provider-differences.md`. That contradiction is why the tape is
   provider-neutral.)

## Safety

M0 has **no sandbox**. `run_command` shells out on the host and asks for confirmation each time;
`TAPELOOP_YOLO=1` skips the prompt. File paths are confined to `TAPELOOP_WORKSPACE`, enforced by
a test. Do not point M0 at untrusted input — that is what M5 is for.
