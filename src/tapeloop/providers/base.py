"""Seam 1 — ModelClient.

A Protocol says which methods exist. It cannot say that OpenAI wants one message
per tool result while Anthropic wants all of them in one. That part is behavioural,
so the real definition of a ModelClient is the conformance suite (ADR-0002), and
this Protocol is only its signature.

Adapters own the wire format entirely. Nothing outside this package may import a
provider SDK's types.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from tapeloop.events import Message, ModelResponse
from tapeloop.tools.registry import ToolSpec


@runtime_checkable
class ModelClient(Protocol):
    """Renders canonical events out to an API, and parses responses back in."""

    @property
    def provider_id(self) -> str:
        """Stable identifier. Goes into the step key, so it must never drift."""
        ...

    def complete(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        max_tokens: int = 4096,
    ) -> ModelResponse: ...

    def count_tokens(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
    ) -> int:
        """Divergence #4: OpenAI counts locally, Anthropic counts server-side.

        Callers must treat this as potentially costly and potentially networked.
        """
        ...
