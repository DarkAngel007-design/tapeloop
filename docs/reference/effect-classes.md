# Effect classes

Every tool declares how it interacts with the world. Replay soundness depends entirely
on these being true.

| Class | Meaning | On replay |
|---|---|---|
| `pure` | Same input, same output. No observation, no mutation. | Always served from cache |
| `read` | Observes external state, mutates nothing. | Cached by default; `--fresh` re-executes |
| `write` | Mutates filesystem, network, or database. | Policy: `cache` · `reexecute` · `halt` |

```python
from tapeloop.tools.effects import Effect
from tapeloop.tools.registry import Registry

registry = Registry()


@registry.tool(effect=Effect.READ)
def peek(path: str) -> str:
    """Look at something.

    Args:
        path: Where to look.
    """
    return ""


@registry.tool()
def unspecified() -> str:
    """No effect declared."""
    return ""


assert registry.get("peek").effect is Effect.READ
# Undeclared defaults to the most conservative class.
assert registry.get("unspecified").effect is Effect.WRITE
```

## Why three

Collapsing `pure` and `read` would lose the ability to re-run an observation against a
changed world, which is the single most useful thing during debugging. Finer
distinctions — idempotent-write, append-only — did not change any replay decision, so
they do not exist.

## Why undeclared means `write`

Misdeclaring a tool is the one way to silently corrupt a replay. The conservative
default means forgetting is safe rather than unsound.

**Never widen a tool's class to make a test pass.** That is written into `AGENTS.md`,
and it is a code-review property rather than a technical control — the runtime trusts
what a tool says about itself.

## Where they are used

- **Permissions** — the default verdict comes from the class: `pure` and `read` are
  allowed, `write` asks. No rule is needed for the common case.
- **Fork soundness** — a fork whose replayed prefix contains a `write` is `simulated`,
  not `faithful`, and the report names the specific tools.
- **The tape** — recorded per tool result, so replay policy reads what the class *was*
  rather than inferring what it is now.
- **MCP** — cannot cross the wire, so imported tools default to `write` and exported
  ones carry the class in their description text.
