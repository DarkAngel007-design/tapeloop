"""The tool registry: one decorated function in, a provider-ready schema out.

M0 hand-wrote every JSON Schema beside the Python signature that already said the
same thing. Every such pair is a chance for the two to disagree, and when they do
the model is told one thing while the code expects another. Here the signature is
the single source of truth and the schema is derived from it.

Schemas are emitted at the *strictest common denominator* both target providers
accept (divergence #7 in docs/explanation/provider-differences.md): every property
listed in ``required``, ``additionalProperties: false``, and optional parameters
expressed as a nullable type rather than an absent key. A schema that satisfies
OpenAI strict mode also satisfies Anthropic; the reverse is not true.

Hand-rolled rather than delegated to pydantic — see ADR-0013.
"""

from __future__ import annotations

import enum
import inspect
import types
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, get_args, get_origin

from tapeloop.tools.effects import Effect

_SECTIONS = frozenset(
    {
        "args",
        "arguments",
        "parameters",
        "returns",
        "raises",
        "yields",
        "example",
        "examples",
        "note",
        "notes",
    }
)

_PRIMITIVES: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


class ToolDefinitionError(Exception):
    """Raised at decoration time, so a bad tool fails at import rather than mid-run."""


# ----------------------------------------------------------------- schema
def json_schema_for(annotation: Any, *, where: str) -> dict[str, Any]:
    """Map a Python annotation to a JSON Schema fragment.

    Deliberately supports a small set and raises loudly outside it. Silently
    emitting ``{"type": "string"}`` for something unrecognized would produce a
    schema that lies to the model, which is worse than refusing to start.
    """
    if annotation in _PRIMITIVES:
        return {"type": _PRIMITIVES[annotation]}

    origin = get_origin(annotation)
    args = get_args(annotation)

    # X | None  /  Optional[X]  ->  nullable type
    if origin in (types.UnionType, typing.Union):
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) != 1 or len(non_none) == len(args):
            raise ToolDefinitionError(
                f"{where}: only `X | None` unions are supported, got {annotation!r}"
            )
        inner = json_schema_for(non_none[0], where=where)
        inner["type"] = [inner["type"], "null"]
        return inner

    if origin is Literal:
        kinds: set[type[Any]] = {type(a) for a in args}
        if len(kinds) != 1 or kinds.pop() not in _PRIMITIVES:
            raise ToolDefinitionError(f"{where}: Literal must be all one primitive type")
        return {"type": _PRIMITIVES[type(args[0])], "enum": list(args)}

    if origin in (list, tuple):
        if not args:
            raise ToolDefinitionError(f"{where}: list must be parameterized, e.g. list[str]")
        return {"type": "array", "items": json_schema_for(args[0], where=where)}

    if origin is dict:
        return {"type": "object", "additionalProperties": True}

    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        values = [m.value for m in annotation]
        kinds: set[type[Any]] = {type(v) for v in values}
        if len(kinds) != 1 or kinds.pop() not in _PRIMITIVES:
            raise ToolDefinitionError(f"{where}: enum values must be all one primitive type")
        return {"type": _PRIMITIVES[type(values[0])], "enum": values}

    raise ToolDefinitionError(
        f"{where}: unsupported annotation {annotation!r}. "
        "Supported: str, int, float, bool, list[T], dict, Literal[...], Enum, X | None."
    )


def parse_docstring(doc: str | None) -> tuple[str, dict[str, str]]:
    """Split a Google-style docstring into (description, {param: description}).

    Tool and parameter descriptions are the model's only guidance on how to call
    something, so they are worth extracting properly rather than shipping a bare
    function name.
    """
    if not doc:
        return "", {}
    lines = inspect.cleandoc(doc).splitlines()
    body: list[str] = []
    params: dict[str, str] = {}
    current: str | None = None
    section: str | None = None

    for line in lines:
        stripped = line.strip()
        header = stripped.rstrip(":").lower() if stripped.endswith(":") else None
        if header in _SECTIONS:
            # The description ends at the first section header and never resumes.
            # Previously a Returns: block fell through and read as part of the
            # tool's description, which is what the model would then have been told.
            section = header
            current = None
            continue

        if section is None:
            body.append(line)
        elif section in {"args", "arguments", "parameters"}:
            if ":" in stripped and not line.startswith((" " * 8, "\t\t")):
                name, _, text = stripped.partition(":")
                current = name.strip().split(" ")[0]
                params[current] = text.strip()
            elif current and stripped:
                params[current] = f"{params[current]} {stripped}".strip()

    return "\n".join(body).strip(), params


# ----------------------------------------------------------------- tool
@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A registered tool: everything a provider adapter needs, plus how to run it."""

    name: str
    description: str
    parameters: dict[str, Any]
    effect: Effect
    fn: Callable[..., Any]

    def call(self, arguments: dict[str, Any]) -> str:
        """Invoke the tool. Returns a string; never raises.

        Tool failures are *data*: the model can read an error and recover, but it
        cannot recover from a dead loop. This is the same rule M0 followed, now
        enforced in one place instead of per-tool.
        """
        try:
            missing = [k for k in self.parameters["properties"] if k not in arguments]
            if missing:
                return f"ERROR: missing required argument(s): {', '.join(missing)}"
            unexpected = [k for k in arguments if k not in self.parameters["properties"]]
            if unexpected:
                return f"ERROR: unexpected argument(s): {', '.join(unexpected)}"
            out = self.fn(**arguments)
            return out if isinstance(out, str) else repr(out)
        except Exception as e:  # deliberate: errors are data, not exceptions
            return f"ERROR: {type(e).__name__}: {e}"


def build_spec(
    fn: Callable[..., Any],
    *,
    effect: Effect,
    name: str | None = None,
    localns: dict[str, Any] | None = None,
) -> ToolSpec:
    """Derive a ToolSpec from a function's signature and docstring."""
    tool_name = name or fn.__name__
    signature = inspect.signature(fn)
    try:
        hints = typing.get_type_hints(fn, localns=localns)
    except Exception as e:
        raise ToolDefinitionError(f"{tool_name}: cannot resolve type hints: {e}") from e

    description, param_docs = parse_docstring(fn.__doc__)
    properties: dict[str, Any] = {}

    for param_name, param in signature.parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            raise ToolDefinitionError(
                f"{tool_name}: *args/**kwargs are not describable as a schema"
            )
        if param_name not in hints:
            raise ToolDefinitionError(
                f"{tool_name}: parameter '{param_name}' has no type annotation"
            )

        schema = json_schema_for(hints[param_name], where=f"{tool_name}.{param_name}")
        if param.default is not inspect.Parameter.empty and not isinstance(schema["type"], list):
            # Strictest common denominator: optional means nullable, not absent.
            schema["type"] = [schema["type"], "null"]
        if param_name in param_docs:
            schema["description"] = param_docs[param_name]
        properties[param_name] = schema

    return ToolSpec(
        name=tool_name,
        description=description,
        # Every property required + additionalProperties false == OpenAI strict mode.
        parameters={
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
        effect=effect,
        fn=fn,
    )


class Registry:
    """A named collection of tools. Adapters read it; the loop dispatches through it."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def tool(
        self, *, effect: Effect = Effect.WRITE, name: str | None = None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register a function as a tool.

        ``effect`` defaults to WRITE — the most conservative class — so forgetting
        to declare one is safe rather than silently unsound (ADR-0005).
        """

        # The frame calling .tool() is the scope the decorated function is being
        # defined in. Its locals are what the annotations may legitimately refer to --
        # without this, a type declared inside a tool-pack factory cannot resolve.
        caller = inspect.currentframe()
        localns = dict(caller.f_back.f_locals) if caller and caller.f_back else None

        def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
            spec = build_spec(fn, effect=effect, name=name, localns=localns)
            if spec.name in self._tools:
                raise ToolDefinitionError(f"duplicate tool name: {spec.name}")
            self._tools[spec.name] = spec
            return fn

        return decorate

    def register(self, spec: ToolSpec) -> ToolSpec:
        """Add a pre-built spec.

        The decorator is the normal path, because a signature is a better source of
        truth than a hand-written schema. This exists for tools whose schema arrives
        from somewhere else entirely -- an MCP server describes its tools over the
        wire, and there is no local signature to derive anything from.
        """
        if spec.name in self._tools:
            raise ToolDefinitionError(f"duplicate tool name: {spec.name}")
        self._tools[spec.name] = spec
        return spec

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._tools.values())

    def dispatch(self, name: str, arguments: dict[str, Any]) -> str:
        spec = self._tools.get(name)
        if spec is None:
            return f"ERROR: no such tool {name!r}. Available: {', '.join(self._tools)}"
        return spec.call(arguments)
