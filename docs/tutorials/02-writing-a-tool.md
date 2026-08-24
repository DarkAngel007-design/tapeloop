# Writing a tool

A tool is a normal Python function. You do not write a JSON schema; the signature and
the docstring are the schema.

## One decorated function

```python
from tapeloop.tools.effects import Effect
from tapeloop.tools.registry import Registry

registry = Registry()


@registry.tool(effect=Effect.PURE)
def celsius_to_fahrenheit(celsius: float) -> str:
    """Convert a temperature from Celsius to Fahrenheit.

    Args:
        celsius: The temperature to convert.
    """
    return f"{celsius * 9 / 5 + 32:.1f}F"


spec = registry.get("celsius_to_fahrenheit")
assert spec is not None
print(spec.description)              # Convert a temperature from Celsius to Fahrenheit.
print(spec.parameters["properties"]) # {'celsius': {'type': 'number', 'description': ...}}
assert spec.parameters["properties"]["celsius"]["description"] == "The temperature to convert."
assert registry.dispatch("celsius_to_fahrenheit", {"celsius": 100.0}) == "212.0F"
```

The docstring's first paragraph becomes the tool description, and each `Args:` entry
becomes a parameter description. Those are the model's only guidance on how to call
your tool, so they are worth writing properly.

## Declare what it does to the world

Every tool declares an **effect class**, and the default is the conservative one:

```python
from tapeloop.tools.effects import Effect
from tapeloop.tools.registry import Registry

registry = Registry()


@registry.tool()  # no effect given
def delete_everything() -> str:
    """Do something drastic."""
    return "done"


# Undeclared means WRITE — forgetting is safe rather than silently unsound.
assert registry.specs()[0].effect is Effect.WRITE
```

This matters later: replaying a cached `read` is faithful, replaying a cached `write`
is a simulation. See [Effect classes](../reference/effect-classes.md).

## Errors are data

A tool that raises would kill the run. Return the problem instead — the model can read
an error and try something else:

```python
from tapeloop.tools.registry import Registry

registry = Registry()


@registry.tool()
def divide(a: float, b: float) -> str:
    """Divide two numbers.

    Args:
        a: The numerator.
        b: The denominator.
    """
    return str(a / b)


# The registry catches it for you and hands the model something readable.
out = registry.dispatch("divide", {"a": 1.0, "b": 0.0})
assert out.startswith("ERROR: ZeroDivisionError")
assert "missing required argument" in registry.dispatch("divide", {"a": 1.0})
```

## Unsupported types fail at import, not mid-run

```python
from tapeloop.tools.registry import Registry, ToolDefinitionError

registry = Registry()

try:

    @registry.tool()
    def bad(x: complex) -> str:
        """Doc."""
        return ""

except ToolDefinitionError as e:
    print(e)  # bad.x: unsupported annotation <class 'complex'>. Supported: ...
else:
    raise AssertionError("should have refused")
```

Supported: `str`, `int`, `float`, `bool`, `list[T]`, `dict`, `Literal[...]`, `Enum`,
`X | None`. Anything else raises when the module loads, rather than emitting a schema
that lies to the model.

## Next

[Recording and replaying](03-recording-and-replaying.md) — the part that makes
iteration cheap.
