# Resume a stopped run

Your run died at minute 200. You want the other 40 minutes, not all 240.

```bash
tapeloop resume tapes/run.jsonl --workspace workspace
```

## It does not rewind, and that is the point

`replay` and `fork` serve cached results for `write` tools, which makes them
**simulations** — fast, and disconnected from the world. `resume` serves **nothing**
from cache. Every step it takes is real.

So it does not restore a snapshot by default. When a long run dies, the workspace
already holds everything that run produced, and **that state is what you are resuming**.
Rewinding it would delete the work you are trying to continue.

```python
from pathlib import Path

from tapeloop.core.loop import Agent
from tapeloop.record.jsonl import JsonlStore
from tapeloop.replay.resume import plan_resume
from tapeloop.testing import ScriptedClient, calls, says
from tapeloop.tools import builtin

workspace, tapes = Path("workspace"), Path("tapes")
workspace.mkdir(exist_ok=True)
tapes.mkdir(exist_ok=True)

Agent(
    client=ScriptedClient([calls("write_file", path="a.txt", content="1"), says("stopped")]),
    registry=builtin.build(workspace),
    model="scripted-1",
    store=JsonlStore(tapes / "run.jsonl"),
).run("start work")

plan = plan_resume(tapes / "run.jsonl", workspace=workspace)
print(plan.report())
assert plan.restored_from is None  # nothing was rewound
assert (workspace / "a.txt").exists()  # the earlier work survives
assert plan.workspace_is_assumed  # and resume says it is trusting it
```

The report tells you where it stopped — cancelled, step ceiling, finished, or
incomplete (no `run_end`, meaning the process died before it could write one).

## Continuing

```python
from pathlib import Path

from tapeloop.core.loop import Agent
from tapeloop.record.jsonl import JsonlStore
from tapeloop.replay.resume import plan_resume
from tapeloop.testing import ScriptedClient, calls, says
from tapeloop.tools import builtin

workspace, tapes = Path("workspace"), Path("tapes")
workspace.mkdir(exist_ok=True)
tapes.mkdir(exist_ok=True)
Agent(
    client=ScriptedClient([calls("write_file", path="a.txt", content="1"), says("stopped")]),
    registry=builtin.build(workspace),
    model="scripted-1",
    store=JsonlStore(tapes / "run.jsonl"),
).run("start work")

plan = plan_resume(tapes / "run.jsonl", workspace=workspace)
result = Agent(
    client=ScriptedClient([says("finished the rest")]),
    registry=builtin.build(workspace),
    model="scripted-1",
    store=JsonlStore(tapes / "resumed.jsonl"),
).resume(plan.history, nudge="skip anything already done")

assert result.text == "finished the rest"
```

A resumed run gets **its own tape**, marked `resumed: true` with a `resumed_from`
record naming the parent. A tape carrying two `run_start` records is not one run.

## Rewinding deliberately

Different question: *"it went wrong around step 12, put the workspace back and let it
try again."* That needs snapshots, and it destroys work done after that step:

```bash
tapeloop resume tapes/run.jsonl --snapshots snapshots --restore-from 12
```

The report says so explicitly. See [replay is not resume](../explanation/replay-vs-resume.md).
