"""The OpenAI-compatible adapter (ADR-0001, ADR-0012).

Targets Chat Completions, which is also what Groq, Together, OpenRouter, vLLM and
Ollama speak — so one adapter reaches all of them and anyone can run tapeloop
against a local model with no credits.

Everything provider-shaped lives here. The two renderers below are where
divergences #1, #2 and #3 are absorbed.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from openai import NOT_GIVEN, OpenAI
from openai.types.chat import ChatCompletion

from tapeloop.events import (
    Message,
    ModelResponse,
    Opaque,
    Role,
    StopReason,
    ToolCall,
    Usage,
)
from tapeloop.tools.registry import ToolSpec

PROVIDER_ID = "openai"

# Divergence #3: their vocabulary, ours. Anything unmapped becomes OTHER, which the
# loop treats as a stop -- an unknown future value must never look like a finished turn.
_STOP: dict[str, StopReason] = {
    "stop": StopReason.END_TURN,
    "tool_calls": StopReason.TOOL_USE,
    "function_call": StopReason.TOOL_USE,
    "length": StopReason.MAX_TOKENS,
    "content_filter": StopReason.FILTERED,
}


def render_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Canonical events -> Chat Completions wire format.

    Divergence #2 lives here: a TOOL_RESULTS message holds the whole set of results
    for one step, and this renderer expands it into one ``role="tool"`` message per
    result. The Anthropic renderer will collapse the same set into a single message.
    Neither layout exists on the tape.
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role is Role.TOOL_RESULTS:
            out.extend(
                {
                    "role": "tool",
                    "tool_call_id": r.call_id,
                    "content": r.content,
                }
                for r in msg.tool_results
            )
            continue

        wire: dict[str, Any] = {"role": msg.role.value}
        wire["content"] = msg.text
        if msg.tool_calls:
            # Divergence #1: tool calls ride on the assistant message, not as blocks.
            wire["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                }
                for c in msg.tool_calls
            ]
        out.append(wire)
    return out


def render_tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
                "strict": True,
            },
        }
        for t in tools
    ]


class OpenAIClient:
    """A ModelClient over any OpenAI-compatible Chat Completions endpoint."""

    def __init__(self, client: OpenAI | None = None, *, provider_id: str = PROVIDER_ID) -> None:
        self._client = client or OpenAI()
        self._provider_id = provider_id

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def complete(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        max_tokens: int = 4096,
    ) -> ModelResponse:
        raw: ChatCompletion = self._client.chat.completions.create(
            model=model,
            messages=render_messages(messages),  # pyright: ignore[reportArgumentType]
            tools=render_tools(tools) or NOT_GIVEN,  # pyright: ignore[reportArgumentType]
            max_completion_tokens=max_tokens,
        )
        return self._parse(raw)

    def _parse(self, raw: ChatCompletion) -> ModelResponse:
        choice = raw.choices[0]
        msg = choice.message

        calls: list[ToolCall] = []
        for tc in msg.tool_calls or []:
            if tc.type != "function":
                continue
            arguments: dict[str, Any]
            try:
                arguments = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                # Keep the malformed text rather than dropping the call. The loop
                # turns this into an is_error result the model can actually fix.
                arguments = {"__malformed__": tc.function.arguments}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=arguments))

        # Divergence #6 and Contract 5. Anything the SDK did not declare is a vendor
        # extension -- reasoning_content on DeepSeek and some vLLM builds, whatever
        # arrives next. Capture all of it verbatim rather than naming fields one by
        # one: the runtime is not supposed to understand these, only carry them.
        opaque = tuple(
            Opaque(provider=self._provider_id, kind=key, data=value)
            for key, value in (msg.model_extra or {}).items()
            if value is not None
        )

        usage = Usage()
        if raw.usage:
            cached = getattr(getattr(raw.usage, "prompt_tokens_details", None), "cached_tokens", 0)
            usage = Usage(
                input_tokens=raw.usage.prompt_tokens,
                output_tokens=raw.usage.completion_tokens,
                cached_input_tokens=cached or 0,
            )

        return ModelResponse(
            message=Message(
                role=Role.ASSISTANT,
                text=msg.content,
                tool_calls=tuple(calls),
                opaque=opaque,
            ),
            stop_reason=_STOP.get(choice.finish_reason or "", StopReason.OTHER),
            usage=usage,
        )

    def count_tokens(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
    ) -> int:
        """Divergence #4: OpenAI has no counting endpoint; this is a local estimate.

        Deliberately crude until M7, where context budgets start depending on it.
        Named as an estimate so nothing downstream mistakes it for authoritative.
        """
        blob = json.dumps(render_messages(messages)) + json.dumps(render_tools(tools))
        return len(blob) // 4
