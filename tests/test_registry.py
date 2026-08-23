"""M1 ship criterion: adding a tool is one decorated function, zero hand-written schema."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

import pytest

from tapeloop.tools.effects import Effect
from tapeloop.tools.registry import Registry, ToolDefinitionError, parse_docstring


def test_schema_is_generated_from_the_signature() -> None:
    reg = Registry()

    @reg.tool(effect=Effect.READ)
    def search(query: str, limit: int = 10) -> str:
        """Search the index.

        Args:
            query: What to look for.
            limit: How many results to return.
        """
        return ""

    spec = reg.get("search")
    assert spec is not None
    assert spec.description == "Search the index."
    assert spec.parameters["properties"]["query"] == {
        "type": "string",
        "description": "What to look for.",
    }
    # A parameter with a default becomes nullable, not absent -- the strictest form
    # both providers accept (divergence #7).
    assert spec.parameters["properties"]["limit"]["type"] == ["integer", "null"]


def test_schema_meets_openai_strict_mode() -> None:
    """Strict mode requires every property listed in `required`, and no extras."""
    reg = Registry()

    @reg.tool()
    def f(a: str, b: int = 1) -> str:
        """Doc."""
        return ""

    params = reg.specs()[0].parameters
    assert params["additionalProperties"] is False
    assert sorted(params["required"]) == ["a", "b"]


def test_rich_annotations() -> None:
    class Colour(StrEnum):
        RED = "red"
        BLUE = "blue"

    reg = Registry()

    @reg.tool()
    def f(mode: Literal["fast", "slow"], tags: list[str], colour: Colour, note: str | None) -> str:
        """Doc."""
        return ""

    props = reg.specs()[0].parameters["properties"]
    assert props["mode"] == {"type": "string", "enum": ["fast", "slow"]}
    assert props["tags"] == {"type": "array", "items": {"type": "string"}}
    assert props["colour"] == {"type": "string", "enum": ["red", "blue"]}
    assert props["note"]["type"] == ["string", "null"]


def test_unsupported_annotation_fails_at_decoration_not_at_runtime() -> None:
    """A schema that silently lies to the model is worse than refusing to start."""
    reg = Registry()

    with pytest.raises(ToolDefinitionError, match="unsupported annotation"):

        @reg.tool()
        def f(x: complex) -> str:
            """Doc."""
            return ""


def test_missing_annotation_is_rejected() -> None:
    reg = Registry()
    with pytest.raises(ToolDefinitionError, match="no type annotation"):

        @reg.tool()
        def f(x) -> str:  # type: ignore[no-untyped-def]
            """Doc."""
            return ""


def test_effect_defaults_to_write() -> None:
    """ADR-0005: forgetting to declare an effect must be safe, not silently unsound."""
    reg = Registry()

    @reg.tool()
    def f() -> str:
        """Doc."""
        return ""

    assert reg.specs()[0].effect is Effect.WRITE


def test_dispatch_returns_errors_as_data() -> None:
    reg = Registry()

    @reg.tool()
    def boom(x: str) -> str:
        """Doc."""
        raise RuntimeError("kaboom")

    assert reg.dispatch("boom", {"x": "1"}).startswith("ERROR: RuntimeError: kaboom")
    assert reg.dispatch("nope", {}).startswith("ERROR: no such tool")
    assert "missing required argument" in reg.dispatch("boom", {})
    assert "unexpected argument" in reg.dispatch("boom", {"x": "1", "y": "2"})


def test_docstring_parsing() -> None:
    body, params = parse_docstring(
        """Summary line.

        A second paragraph.

        Args:
            a: First thing.
            b: Second thing,
                continued on the next line.

        Returns:
            Ignored.
        """
    )
    assert body == "Summary line.\n\nA second paragraph."
    assert params == {"a": "First thing.", "b": "Second thing, continued on the next line."}
