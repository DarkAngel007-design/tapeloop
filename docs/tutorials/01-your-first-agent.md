# Your first agent

Fifteen minutes, no API key. You will build a working agent, watch it use a tool, and
see the recording it leaves behind.

## Install

```bash
pip install tapeloop
```

## An agent that needs no credentials

Every example on this page runs offline. `ScriptedClient` answers from a fixed list
instead of calling a model, which is how tapeloop's own test suite runs without
spending anything — and how yours should too.

```python
from pathlib import Path

from tapeloop.core.loop import Agent
from tapeloop.testing import ScriptedClient, calls, says
from tapeloop.tools import builtin

workspace = Path("workspace")
workspace.mkdir(exist_ok=True)
(workspace / "notes.md").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

client = ScriptedClient([
    calls("read_file", path="notes.md"),
    says("notes.md has three lines."),
])

agent = Agent(client=client, registry=builtin.build(workspace), model="scripted-1")
result = agent.run("how many lines are in notes.md?")

print(result.text)      # notes.md has three lines.
print(result.steps)     # 2
assert result.text == "notes.md has three lines."
assert result.steps == 2
```

Two steps: the model asked to read a file, tapeloop ran the tool and handed back the
result, and the model answered. That loop is the whole runtime.

## What the agent could do

`builtin.build(workspace)` gives it four tools, and confines every path to the
directory you passed:

```python
from pathlib import Path

from tapeloop.tools import builtin

registry = builtin.build(Path("."))
print(sorted(t.name for t in registry.specs()))
assert sorted(t.name for t in registry.specs()) == [
    "list_files", "read_file", "run_command", "write_file",
]

# Confinement is enforced, not documented.
refused = registry.dispatch("read_file", {"path": "/etc/passwd"})
assert refused.startswith("ERROR:")
```

## Against a real model

Same code, one line different. Put your key in `.env` and swap the client:

```py
from tapeloop.providers.openai import OpenAIClient

agent = Agent(
    client=OpenAIClient(),
    registry=builtin.build(workspace),
    model="gpt-4o-mini",     # or any OpenAI-compatible endpoint
)
```

Or from the command line:

```bash
tapeloop run "how many lines are in notes.md?" --workspace workspace
```

!!! warning "Before you point it at anything you care about"
    The defaults protect you from accidents, not from adversaries. A bare `Agent(...)`
    runs model-authored shell commands on your host with no permission gate and no
    isolation. See [Sandbox an agent](../how-to/sandbox-an-agent.md).

## Next

[Writing a tool](02-writing-a-tool.md) — teach it to do something only you can.
