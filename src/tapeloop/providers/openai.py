"""The OpenAI-compatible adapter (ADR-0001, ADR-0012).

Targets Chat Completions, which is also what Groq, Together, OpenRouter, vLLM and
Ollama speak — so one adapter reaches all of them and anyone can run tapeloop
against a local model with no credits.

Everything provider-shaped lives here. The two renderers below are where
divergences #1, #2 and #3 are absorbed.
"""

from __future__ import annotations

import json
from collections.abc import Generator, Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any, TypeVar, cast
from urllib.parse import urlparse

from openai import OpenAI, Stream, omit
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionChunk,
    ChatCompletionMessageParam,
    ChatCompletionToolUnionParam,
)

from tapeloop.core.errors import (
    AuthenticationFailed,
    ProviderError,
    ProviderUnavailable,
    RateLimited,
    RequestInvalid,
)
from tapeloop.events import (
    Message,
    ModelResponse,
    Opaque,
    Role,
    StopReason,
    ToolCall,
    Usage,
)
from tapeloop.providers.stream import (
    StreamEnd,
    StreamEvent,
    TextDelta,
    ToolCallAccumulator,
    ToolCallDelta,
)
from tapeloop.record.codec import order_results
from tapeloop.tools.registry import ToolSpec

T = TypeVar("T")

PROVIDER_ID = "openai"


OFFICIAL_HOSTS = frozenset({"api.openai.com"})


def provider_id_for(client: OpenAI) -> str:
    """Derive a provider id from where the client actually points.

    This matters more than it looks. `provider_id` goes into the step key (ADR-0004)
    precisely so that two backends cannot share a cache entry — but until this existed,
    setting OPENAI_BASE_URL to a local Ollama left the id as "openai", and a run against
    `llama3.2` on Ollama produced the *same key* as one against a model of that name at
    OpenAI. A false cache hit returns an answer that was never given.

    The trade: `localhost` and `127.0.0.1` for the same daemon yield different ids and
    therefore different keys. That is a spurious miss, which costs a call. The
    alternative is a false hit, which costs correctness — so the miss is the right side
    to err on.
    """
    base = str(getattr(client, "base_url", "") or "")
    host = urlparse(base).hostname or ""
    if not host or host in OFFICIAL_HOSTS:
        return PROVIDER_ID
    port = urlparse(base).port
    return f"openai-compatible:{host}{f':{port}' if port else ''}"


@contextmanager
def _translated() -> Generator[None]:
    """Turn SDK exceptions into the taxonomy the retry policy understands.

    This wrapper is why the taxonomy exists at all, and for two releases it was
    missing: `translate` was written at M2 and never called, so every SDK exception
    propagated straight past `RetryPolicy` -- which only catches `ProviderError`. The
    retry chain looked correct, was covered by tests, and had never once fired against
    a real provider, because the tests raised `ProviderError` directly.

    Found by pointing the runtime at a local Ollama and watching a raw
    `openai.InternalServerError` come out the top of the stack.
    """
    try:
        yield
    except ProviderError:
        raise
    except Exception as e:
        raise translate(e) from e


def _translated_iter(stream: Iterable[T]) -> Iterator[T]:
    """The same, for errors raised *while consuming* a stream rather than opening it."""
    iterator = iter(stream)
    while True:
        with _translated():
            try:
                item = next(iterator)
            except StopIteration:
                return
        yield item


def translate(exc: Exception) -> ProviderError:
    """Map an SDK exception onto the taxonomy the retry policy understands.

    The only question the caller has is *is this worth trying again*, so that is what
    the mapping answers. Anything unrecognized becomes non-retryable: retrying an
    error we do not understand is how a permanent misconfiguration burns a budget.
    """
    import openai

    if isinstance(exc, openai.RateLimitError):
        return RateLimited(str(exc), retry_after=_retry_after(exc))
    if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
        return AuthenticationFailed(str(exc))
    if isinstance(exc, openai.APIConnectionError | openai.APITimeoutError):
        return ProviderUnavailable(str(exc))
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code >= 500:
            return ProviderUnavailable(str(exc), retry_after=_retry_after(exc))
        if exc.status_code == 429:
            # The SDK normally raises RateLimitError, caught above. An
            # OpenAI-compatible server that returns a bare 429 must not be
            # misread as a bad request and given up on.
            return RateLimited(str(exc), retry_after=_retry_after(exc))
        if exc.status_code in (401, 403):
            return AuthenticationFailed(str(exc))
        return RequestInvalid(str(exc))
    return RequestInvalid(str(exc))


def _retry_after(exc: Exception) -> float | None:
    """Honour the server's own advice when it gives any. It knows things we do not."""
    response = getattr(exc, "response", None)
    header = getattr(response, "headers", {}) or {}
    raw = header.get("retry-after") if hasattr(header, "get") else None
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


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
    pending_calls: tuple[ToolCall, ...] = ()
    for msg in messages:
        if msg.role is Role.TOOL_RESULTS:
            # Ordered against the preceding assistant's calls (ADR-0014), defensively.
            # The codec already does this when writing the tape, but a Message built in
            # memory never passes through the codec -- and the conformance suite is
            # right that an adapter must not depend on someone else having tidied up.
            ordered = order_results(msg.tool_results, pending_calls)
            out.extend(
                {"role": "tool", "tool_call_id": r.call_id, "content": r.content} for r in ordered
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
        pending_calls = msg.tool_calls or ()
    return out


def wire_messages(messages: Sequence[Message]) -> list[ChatCompletionMessageParam]:
    """Cast at the boundary, once.

    render_messages builds plain dicts because that is what the wire format is. The
    SDK wants its own TypedDicts. Casting here keeps every call site clean and puts
    the one unavoidable unsafe step in a single, named place.
    """
    return cast(list[ChatCompletionMessageParam], render_messages(messages))


def wire_tools(tools: Sequence[ToolSpec]) -> list[ChatCompletionToolUnionParam]:
    return cast(list[ChatCompletionToolUnionParam], render_tools(tools))


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

    def __init__(self, client: OpenAI | None = None, *, provider_id: str | None = None) -> None:
        self._client = client or OpenAI()
        self._provider_id = provider_id or provider_id_for(self._client)

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
        with _translated():
            raw: ChatCompletion = self._client.chat.completions.create(
                model=model,
                messages=wire_messages(messages),
                tools=wire_tools(tools) or omit,
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

    def stream(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        max_tokens: int = 4096,
    ) -> Iterator[StreamEvent]:
        """Stream deltas, then yield one StreamEnd with the assembled response."""
        accumulator = ToolCallAccumulator()
        text_parts: list[str] = []
        finish: str | None = None
        usage = Usage()

        with _translated():
            raw_stream: Stream[ChatCompletionChunk] = self._client.chat.completions.create(
                model=model,
                messages=wire_messages(messages),
                tools=wire_tools(tools) or omit,
                max_completion_tokens=max_tokens,
                stream=True,
                # Without this the final chunk carries no usage and every streamed
                # run reports zero tokens -- silently breaking cost accounting at M9.
                stream_options={"include_usage": True},
            )

        for chunk in _translated_iter(raw_stream):
            if chunk.usage:
                cached = getattr(
                    getattr(chunk.usage, "prompt_tokens_details", None), "cached_tokens", 0
                )
                usage = Usage(
                    input_tokens=chunk.usage.prompt_tokens,
                    output_tokens=chunk.usage.completion_tokens,
                    cached_input_tokens=cached or 0,
                )
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            finish = choice.finish_reason or finish
            delta = choice.delta

            if delta.content:
                text_parts.append(delta.content)
                yield TextDelta(text=delta.content)

            for call in delta.tool_calls or []:
                event = ToolCallDelta(
                    index=call.index,
                    id=call.id,
                    name=call.function.name if call.function else None,
                    arguments_fragment=(call.function.arguments if call.function else None) or "",
                )
                accumulator.add(event)
                yield event

        yield StreamEnd(
            response=ModelResponse(
                message=Message(
                    role=Role.ASSISTANT,
                    text="".join(text_parts) or None,
                    tool_calls=accumulator.finish(),
                ),
                stop_reason=_STOP.get(finish or "", StopReason.OTHER),
                usage=usage,
            )
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
