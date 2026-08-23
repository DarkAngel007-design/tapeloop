"""The Anthropic adapter — signatures only, no implementation. Deliberately.

ADR-0001: an abstraction designed against a single provider ends up shaped like
that provider, and you find out much too late. This file is the cheap early check.
It has no dependency on the Anthropic SDK and costs nothing to run, but it must
satisfy the ModelClient Protocol under pyright strict. If ModelClient ever grows a
parameter that only makes sense for OpenAI, this file stops type-checking.

The comments below are the design notes for the real implementation. They are the
seven divergences from docs/explanation/provider-differences.md, written down at
the point where each one will actually have to be handled.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

from tapeloop.events import Message, ModelResponse
from tapeloop.providers.stream import StreamEvent
from tapeloop.tools.registry import ToolSpec

PROVIDER_ID = "anthropic"

_NOT_BUILT = (
    "The Anthropic adapter is signatures-only. It exists so the ModelClient "
    "Protocol is checked against a second, differently-shaped provider before "
    "that provider is implemented. See ADR-0001."
)


def render_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Canonical events -> Messages API format.

    Divergence #1: tool calls become ``tool_use`` content *blocks*, not a field.
    Divergence #2: a TOOL_RESULTS set collapses into ONE ``user`` message holding
      every ``tool_result`` block. Splitting them silently teaches the model to
      stop calling tools in parallel, and nothing errors. This is the exact
      opposite of the OpenAI renderer, and the reason the tape stores the set.
    Divergence #6: ``thinking`` blocks must be replayed verbatim -- they arrive
      here as Opaque payloads tagged "anthropic" and are passed straight through.
    """
    raise NotImplementedError(_NOT_BUILT)


def render_tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    """Divergence #7: Anthropic accepts looser schemas than OpenAI strict mode.

    Nothing to do here: the registry already emits the strictest common denominator,
    so a schema that satisfied OpenAI satisfies this too.
    """
    raise NotImplementedError(_NOT_BUILT)


class AnthropicClient:
    """Not implemented. Present so the Protocol is checked against a second shape."""

    def __init__(self) -> None:
        raise NotImplementedError(_NOT_BUILT)

    @property
    def provider_id(self) -> str:
        return PROVIDER_ID

    def complete(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        max_tokens: int = 4096,
    ) -> ModelResponse:
        """Divergence #3: stop_reason vocabulary is end_turn / tool_use / max_tokens
        / refusal / pause_turn. Note ``pause_turn`` has no OpenAI equivalent at all --
        it is the one that will prove whether StopReason was designed or transcribed.
        Divergence #5: cache_control breakpoints are set here, not inferred.
        """
        raise NotImplementedError(_NOT_BUILT)

    def stream(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        max_tokens: int = 4096,
    ) -> Iterator[StreamEvent]:
        """The Messages API streams *content blocks*, not a flat delta channel.

        Events arrive as content_block_start / content_block_delta / content_block_stop
        around an indexed block, and a tool call's arguments come through as
        ``input_json_delta`` fragments. Different envelope, identical problem: nothing
        is valid JSON until the block closes, so ToolCallAccumulator applies unchanged.

        That it applies unchanged is the useful signal — the accumulator was designed,
        not transcribed from OpenAI's shape.
        """
        raise NotImplementedError(_NOT_BUILT)

    def count_tokens(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
    ) -> int:
        """Divergence #4: this one is a network call, unlike OpenAI's local estimate."""
        raise NotImplementedError(_NOT_BUILT)
