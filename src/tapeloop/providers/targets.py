"""Conformance targets for the adapters that ship with tapeloop.

The Anthropic target is registered *now*, while the adapter is still signatures-only.
It fails every check today, loudly and by name. That is the point: the day someone
implements the adapter, the suite already knows what it has to satisfy, and nobody
gets to shape the contract around whatever the implementation happened to do.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from tapeloop.events import Message, ModelResponse, StopReason
from tapeloop.providers.conformance import ConformanceTarget, WireResponse
from tapeloop.tools.registry import ToolSpec


# ------------------------------------------------------------------ OpenAI
def _openai_wire(spec: WireResponse) -> Any:
    """Build a genuine SDK ChatCompletion.

    Constructed from the SDK's own models rather than a look-alike, so the parser is
    tested against what it will actually receive. A hand-rolled stand-in would pass
    even if the SDK's shape changed under us.
    """
    from openai.types import CompletionUsage
    from openai.types.chat import ChatCompletion, ChatCompletionMessage
    from openai.types.chat.chat_completion import Choice
    from openai.types.chat.chat_completion_message_tool_call import (
        ChatCompletionMessageToolCall,
        Function,
    )
    from openai.types.completion_usage import PromptTokensDetails

    calls = [
        ChatCompletionMessageToolCall(
            id=cid, type="function", function=Function(name=name, arguments=args)
        )
        for cid, name, args in spec.tool_calls
    ]
    message = ChatCompletionMessage.model_construct(
        role="assistant",
        content=spec.text,
        tool_calls=calls or None,
        # Vendor fields the SDK does not model land in model_extra, which is exactly
        # where the adapter looks for opaque payloads.
        **spec.extras,
    )
    usage = (
        CompletionUsage.model_construct(
            prompt_tokens=spec.input_tokens,
            completion_tokens=spec.output_tokens,
            total_tokens=spec.input_tokens + spec.output_tokens,
            prompt_tokens_details=PromptTokensDetails(cached_tokens=spec.cached_tokens)
            if spec.cached_tokens
            else None,
        )
        if (spec.input_tokens or spec.output_tokens)
        else None
    )
    # model_construct skips validation on purpose. `finish_reason` is a pydantic
    # Literal, so an unknown value is rejected by the SDK before our own fallback can
    # run -- and the fallback is exactly what C12 needs to exercise. Worth knowing
    # separately: this means a *new* finish_reason from the provider breaks at the SDK
    # boundary, not at ours. That fragility is the SDK's and we cannot defend it here.
    choice = Choice.model_construct(finish_reason=spec.stop, index=0, message=message)
    return ChatCompletion.model_construct(
        id="conformance",
        created=0,
        model="conformance-model",
        object="chat.completion",
        choices=[choice],
        usage=usage,
    )


def openai_target() -> ConformanceTarget:
    from tapeloop.providers.openai import (
        PROVIDER_ID,
        OpenAIClient,
        render_messages,
        render_tools,
    )

    client = OpenAIClient.__new__(OpenAIClient)
    client._provider_id = PROVIDER_ID  # pyright: ignore[reportPrivateUsage]  # no network needed

    def parse(raw: Any) -> ModelResponse:
        return client._parse(raw)  # pyright: ignore[reportPrivateUsage]

    def count(messages: Sequence[Message]) -> int:
        return client.count_tokens(model="conformance-model", messages=messages)

    return ConformanceTarget(
        name="openai (chat completions)",
        provider_id=PROVIDER_ID,
        render_messages=render_messages,
        render_tools=render_tools,
        parse=parse,
        build_wire=_openai_wire,
        # The provider's documented vocabulary, not ours.
        stop_reasons={
            "stop": StopReason.END_TURN,
            "tool_calls": StopReason.TOOL_USE,
            "function_call": StopReason.TOOL_USE,
            "length": StopReason.MAX_TOKENS,
            "content_filter": StopReason.FILTERED,
        },
        count_tokens=count,
    )


# --------------------------------------------------------------- Anthropic
def anthropic_target() -> ConformanceTarget:
    """Registered while unimplemented, and failing by name.

    `pause_turn` is in the vocabulary below and has no OpenAI equivalent at all. It is
    the single value most likely to reveal that `StopReason` was transcribed from one
    provider rather than designed — which is exactly what this target exists to find out.
    """
    from tapeloop.providers.anthropic import (
        PROVIDER_ID,
        AnthropicClient,
        render_messages,
        render_tools,
    )

    def parse(raw: Any) -> ModelResponse:
        client = AnthropicClient.__new__(AnthropicClient)
        return client.complete(model="x", messages=[], tools=(), max_tokens=1)

    def build(spec: WireResponse) -> Any:
        raise NotImplementedError("no wire builder: the Anthropic adapter is signatures-only")

    def render_msgs(messages: Sequence[Message]) -> list[Any]:
        return render_messages(messages)

    def render_tls(tools: Sequence[ToolSpec]) -> list[Any]:
        return render_tools(tools)

    return ConformanceTarget(
        name="anthropic (messages) — NOT IMPLEMENTED",
        provider_id=PROVIDER_ID,
        render_messages=render_msgs,
        render_tools=render_tls,
        parse=parse,
        build_wire=build,
        stop_reasons={
            "end_turn": StopReason.END_TURN,
            "tool_use": StopReason.TOOL_USE,
            "max_tokens": StopReason.MAX_TOKENS,
            "refusal": StopReason.REFUSAL,
            "pause_turn": StopReason.OTHER,
        },
        count_tokens=None,
    )


def ollama_target() -> ConformanceTarget:
    """Ollama speaks the OpenAI wire format, so it shares the renderer and parser.

    Registering it anyway is not ceremony: it asserts that an adapter reaching the same
    code by a different route still satisfies the contract, and that its identity is
    distinct — which is exactly the property whose absence caused a step-key collision.
    """
    from tapeloop.providers.ollama import PROVIDER_ID, OllamaClient
    from tapeloop.providers.openai import render_messages, render_tools

    client = OllamaClient.__new__(OllamaClient)
    client._provider_id = PROVIDER_ID  # pyright: ignore[reportPrivateUsage]  # no daemon needed

    base = openai_target()
    return ConformanceTarget(
        name="ollama (openai-compatible)",
        provider_id=PROVIDER_ID,
        render_messages=render_messages,
        render_tools=render_tools,
        parse=lambda raw: client._parse(raw),  # pyright: ignore[reportPrivateUsage]
        build_wire=base.build_wire,
        # Same vocabulary: it is the same wire format.
        stop_reasons=base.stop_reasons,
        count_tokens=lambda messages: client.count_tokens(
            model="conformance-model", messages=messages
        ),
    )


BUILTIN_TARGETS = {
    "openai": openai_target,
    "ollama": ollama_target,
    "anthropic": anthropic_target,
}
