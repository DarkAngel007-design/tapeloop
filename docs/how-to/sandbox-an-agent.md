# Sandbox an agent

**The defaults protect you from accidents, not from adversaries.** A bare `Agent(...)`
has `policy=None` and uses `SubprocessExecutor`, so model-authored shell commands run
on your host with no permission gate and no isolation.

That is deliberate — a container that silently failed to start would be worse than one
you knowingly did not use — but it is opt-in safety. For anything untrusted you need
both halves: a policy decides *what may run*, an executor decides *what running can
reach*. Neither alone is enough.

## 1. A permission policy

Rules are per tool **and per argument**. Being allowed to run `git status` is not being
allowed to run anything.

```python
from tapeloop.sandbox.permissions import PermissionPolicy, Rule, Verdict
from tapeloop.tools.effects import Effect

policy = PermissionPolicy(rules=[
    Rule("run_command", "git status*", Verdict.ALLOW),
    Rule("run_command", "*", Verdict.DENY),
])

assert policy.decide("run_command", {"command": "git status"}, Effect.WRITE).allowed
assert not policy.decide("run_command", {"command": "rm -rf /"}, Effect.WRITE).allowed

# No rule? The effect class decides: reading is allowed, writing asks.
assert policy.decide("read_file", {"path": "a.txt"}, Effect.READ).allowed
```

Put them in `.tapeloop/permissions.toml` and commit the file — a permission set is a
property of a codebase, not of a person, so it should be reviewed like any other change:

```toml
deny  = ["run_command:curl *", "run_command:* | sh", "run_command:rm -rf *"]
allow = ["run_command:git status*", "run_command:pytest*"]
```

Deny beats allow regardless of order in the file.

### Unattended runs refuse

With no prompter attached — CI, cron — anything that would need a human is **denied**,
not assumed:

```python
from tapeloop.sandbox.permissions import PermissionPolicy
from tapeloop.tools.effects import Effect

decision = PermissionPolicy().decide("write_file", {"path": "a"}, Effect.WRITE)
assert not decision.allowed
assert "no prompter" in decision.rule
```

Assuming yes is how a cron job does something nobody agreed to.

## 2. A container

```py
from pathlib import Path

from tapeloop.core.loop import Agent
from tapeloop.sandbox.docker import DockerExecutor
from tapeloop.tools import builtin

executor = DockerExecutor()          # no network, all capabilities dropped,
workspace = Path("workspace")        # read-only root, unprivileged
agent = Agent(
    client=...,
    registry=builtin.build(workspace, executor=executor),
    model="gpt-4o-mini",
    policy=PermissionPolicy.load(Path(".tapeloop/permissions.toml")),
)
```

`DockerExecutor` raises if Docker is missing rather than degrading quietly, and reports
what you actually got:

```python
from tapeloop.sandbox.docker import DockerExecutor
from tapeloop.sandbox.subprocess import SubprocessExecutor

print(SubprocessExecutor().isolation)   # subprocess (no isolation)
print(DockerExecutor().isolation)       # docker (python:3.12-slim, no network, unprivileged)
assert "no isolation" in SubprocessExecutor().isolation
```

That string is recorded on the tape, so a run can never claim protection it did not have.

## On prompt injection

tapeloop does **not** try to detect it, and any harness claiming to reliably detect it
is overselling. A hostile instruction is just text.

The defence is that being persuaded does not grant capability: the model can be
completely taken in and still gain nothing, because the dangerous action needs a rule
that permits it. That is what the ship-criterion test asserts — the model dutifully
attempts an injected `curl … | sh`, and it does not run.

See the [threat model](../explanation/threat-model.md) for what is *not* claimed.
