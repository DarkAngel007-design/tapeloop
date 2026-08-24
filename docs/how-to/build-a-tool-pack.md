# Build a tool pack

A tool pack is a factory that returns a `Registry` bound to something — a workspace, a
database handle, an API client. The builtin pack is one.

```python
from pathlib import Path

from tapeloop.tools.effects import Effect
from tapeloop.tools.registry import Registry


def build(root: Path) -> Registry:
    """A pack bound to one directory."""
    root = root.resolve()
    registry = Registry()

    def safe(rel: str) -> Path:
        target = (root / rel).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"path escapes the pack root: {rel}")
        return target

    @registry.tool(effect=Effect.READ)
    def word_count(path: str) -> str:
        """Count the words in a text file.

        Args:
            path: Path relative to the pack root.
        """
        return str(len(safe(path).read_text(encoding="utf-8").split()))

    return registry


here = Path(".")
(here / "sample.txt").write_text("one two three", encoding="utf-8")
pack = build(here)
assert pack.dispatch("word_count", {"path": "sample.txt"}) == "3"
assert pack.dispatch("word_count", {"path": "../escape"}).startswith("ERROR:")
```

Two things worth copying from that:

**Confine paths inside the closure.** The check lives next to the thing it protects,
and every tool in the pack gets it.

**Declare effects honestly.** Never widen a class to make a test pass — replay
soundness depends on them being true, and an undeclared tool is treated as `write`.

## Types a tool may take

`str`, `int`, `float`, `bool`, `list[T]`, `dict`, `Literal[...]`, `Enum`, `X | None`.
Anything else raises at decoration time rather than emitting a schema that lies to the
model.

## Adding a pre-built spec

Rare, but needed when the schema comes from somewhere other than a signature — an MCP
server describing its tools over the wire, for instance:

```python
from tapeloop.tools.effects import Effect
from tapeloop.tools.registry import Registry, ToolSpec

registry = Registry()
registry.register(
    ToolSpec(
        name="remote_thing",
        description="Described by a server, not by a signature.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        effect=Effect.WRITE,
        fn=lambda: "ok",
    )
)
assert "remote_thing" in registry
```
