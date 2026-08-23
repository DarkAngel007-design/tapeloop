# ADR-0013 — Hand-rolled schema generation instead of pydantic

**Status:** Accepted · 2026-08-23

## Context

The registry derives JSON Schema from a function's type hints. pydantic is the
obvious tool: it is the industry default, it generates JSON Schema, and it validates
arguments too.

Two things argue against it here.

First, ADR-0002 requires schemas at the **strictest common denominator** both target
providers accept — every property in `required`, `additionalProperties: false`,
optional parameters expressed as nullable rather than absent. pydantic emits its own
opinionated shape (`anyOf`, `$defs`, `default` keys), so we would post-process its
output into ours. Generating the shape we want directly is less code than rewriting
someone else's.

Second, "not dependency-maximal" is a stated feature of this project. The runtime's
dependency list is part of its argument.

## Decision

Hand-roll the mapping in `tools/registry.py`. Support a deliberately small set —
`str`, `int`, `float`, `bool`, `list[T]`, `dict`, `Literal[...]`, `Enum`, `X | None` —
and raise `ToolDefinitionError` at **decoration time** for anything else.

## Consequences

- Failing at decoration time means a badly-typed tool breaks at import, not halfway
  through a paid run.
- Raising on unsupported annotations rather than falling back to `{"type": "string"}`
  is the important half. A schema that silently lies to the model is worse than a
  runtime that refuses to start.
- Argument validation is shallow: presence and arity are checked, types are not
  coerced. Acceptable while `strict: true` makes the provider validate for us;
  revisit if a target provider lacks strict mode.
- Roughly 90 lines to own and test. That is the price, and it is paid in a file that
  is central enough to deserve the attention.
