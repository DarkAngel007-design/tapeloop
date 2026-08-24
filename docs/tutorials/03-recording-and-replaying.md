# Recording and replaying

This is the part the project is named for. Every run writes a **tape**, and a tape
turns a re-run into a lookup.

## Record

Give the agent a `JsonlStore` and it records as it goes:

```python
from pathlib import Path

from tapeloop.core.loop import Agent
from tapeloop.record.jsonl import JsonlStore
from tapeloop.testing import ScriptedClient, calls, says
from tapeloop.tools import builtin

workspace = Path("workspace")
workspace.mkdir(exist_ok=True)
(workspace / "data.txt").write_text("one\ntwo\n", encoding="utf-8")

# Tapes live OUTSIDE the workspace. A tape the agent can see becomes something the
# agent observes, and the second run stops matching the first.
tapes = Path("tapes")
tapes.mkdir(exist_ok=True)

client = ScriptedClient([calls("read_file", path="data.txt"), says("Two lines.")])
agent = Agent(
    client=client,
    registry=builtin.build(workspace),
    model="scripted-1",
    store=JsonlStore(tapes / "run.jsonl"),
)
agent.run("count the lines")

print((tapes / "run.jsonl").read_text(encoding="utf-8").splitlines()[0])
# {"kind":"header","tapeloop":"...","v":1}
assert (tapes / "run.jsonl").exists()
```

The tape is newline-delimited JSON. `head` and `jq` work on it, and reading one never
requires importing tapeloop — that is deliberate, because the moment you most need to
read a recording is the moment you least want to install something.

## Replay

A `StepCache` turns the tape into an index from step key to response. Re-running the
same agent hits it every time:

```python
from pathlib import Path

from tapeloop.core.loop import Agent
from tapeloop.record.cache import StepCache
from tapeloop.record.jsonl import JsonlStore
from tapeloop.testing import ScriptedClient, calls, says
from tapeloop.tools import builtin

workspace, tapes = Path("workspace"), Path("tapes")
workspace.mkdir(exist_ok=True)
tapes.mkdir(exist_ok=True)
(workspace / "data.txt").write_text("one\ntwo\n", encoding="utf-8")

script = [calls("read_file", path="data.txt"), says("Two lines.")]
Agent(
    client=ScriptedClient(script),
    registry=builtin.build(workspace),
    model="scripted-1",
    store=JsonlStore(tapes / "first.jsonl"),
).run("count the lines")

# An empty script: if the provider is called at all, this raises.
cache = StepCache.from_tape(tapes / "first.jsonl")
replayed = Agent(
    client=ScriptedClient([]),
    registry=builtin.build(workspace),
    model="scripted-1",
    store=JsonlStore(tapes / "second.jsonl"),
    cache=cache,
).run("count the lines")

print(f"{cache.stats.hits}/{cache.stats.total} hits")  # 2/2 hits
assert cache.stats.hit_rate == 1.0
assert replayed.text == "Two lines."

# And the two tapes are byte-identical.
assert (tapes / "first.jsonl").read_bytes() == (tapes / "second.jsonl").read_bytes()
```

Nothing was sent anywhere. That is the whole feature.

## Why the tapes are byte-identical

Because a tape contains no timestamps, no run ids, and no machine identity. Time comes
from the filesystem instead. If a wall-clock value were recorded, two identical runs
would produce two different files and no comparison would mean anything.

## Look at it

```bash
tapeloop show tapes/run.jsonl     # step by step
tapeloop view tapes/run.jsonl     # one self-contained HTML page
```

## Next

[Forking to A/B a prompt](04-forking-to-ab-a-prompt.md) — what replay is *for*.
