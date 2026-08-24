# Forking to A/B a prompt

Changing a prompt normally means re-running everything: minutes, and money, per
experiment. Forking means re-running only the part after the change.

## The problem

You have a 15-step run. Step 12 went wrong. You want to try a different system prompt
and see whether step 12 goes differently.

Without a tape, that costs 15 steps. With one, it costs 3.

## Fork it

```python
from pathlib import Path

from tapeloop.core.loop import Agent
from tapeloop.record.jsonl import JsonlStore
from tapeloop.replay.fork import plan_fork
from tapeloop.testing import ScriptedClient, calls, says
from tapeloop.tools import builtin

workspace, tapes = Path("workspace"), Path("tapes")
workspace.mkdir(exist_ok=True)
tapes.mkdir(exist_ok=True)

# A run that surveys the directory a few times, then answers.
script = [calls("list_files", pattern="*") for _ in range(4)] + [says("Nothing here.")]
Agent(
    client=ScriptedClient(script),
    registry=builtin.build(workspace),
    model="scripted-1",
    store=JsonlStore(tapes / "original.jsonl"),
).run("survey the directory")

# Branch at step 3 with a different system prompt.
plan = plan_fork(tapes / "original.jsonl", at=3, system="Be terse. One line only.")

print(plan.report())
# fork original.jsonl @ step 3 — faithful
assert plan.at == 3
assert len(plan.history) > 0
```

`plan_fork` runs nothing. It builds the history, works out whether the fork is sound,
and hands you a report — so you can decide before spending anything.

## Faithful or simulated

A fork tells you whether it can be trusted, and it works this out from the effect
classes of the tools it replayed:

- **`faithful`** — nothing in the replayed prefix wrote anything. The workspace was
  never touched, so the fork is genuinely what would have happened.
- **`simulated`** — a `write` was replayed from cache. The workspace does **not** match
  the history the model has been told about, and the report names the specific tools.

```python
from pathlib import Path

from tapeloop.core.loop import Agent
from tapeloop.record.jsonl import JsonlStore
from tapeloop.replay.fork import Soundness, plan_fork
from tapeloop.testing import ScriptedClient, calls, says
from tapeloop.tools import builtin

workspace, tapes = Path("workspace"), Path("tapes")
workspace.mkdir(exist_ok=True)
tapes.mkdir(exist_ok=True)

Agent(
    client=ScriptedClient([calls("write_file", path="out.txt", content="x"), says("done")]),
    registry=builtin.build(workspace),
    model="scripted-1",
    store=JsonlStore(tapes / "wrote.jsonl"),
).run("write a file")

plan = plan_fork(tapes / "wrote.jsonl", at=1)
assert plan.soundness is Soundness.SIMULATED
assert "write_file" in plan.report()  # it names the tool, not just a warning
print(plan.report())
```

For evals, `require_faithful=True` turns a simulated fork into a refusal — a silently
simulated run poisons a results table, and a number you cannot trust is worse than no
number.

## Across providers

Because the tape stores canonical events rather than one vendor's wire format, a run
recorded on one model can be branched onto another with identical history:

```bash
tapeloop fork run.jsonl "..." --at 12 --model claude-opus-5
```

Payloads meaningful only to the original provider are dropped, and the report says so
rather than doing it quietly. That comparison — same history, different model, from the
exact step it went wrong — is normally impossible, because your history is locked
inside one vendor's message format.

## From the command line

```bash
tapeloop fork tapes/original.jsonl "survey the directory" --at 3 --system "Be terse." --dry-run
tapeloop diff tapes/original.jsonl tapes/fork-original-at3.jsonl
```

## Next

- [Resume a stopped run](../how-to/resume-a-stopped-run.md) — the *other* operation, and
  the difference matters
- [Replay is not resume](../explanation/replay-vs-resume.md) — why
