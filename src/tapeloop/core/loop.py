"""The agent loop: seams, streaming, retries, and clean cancellation.

M1 replaced every concrete dependency with a Protocol. M2 makes the loop survive
contact with a real network: output arrives token by token, transient failures are
retried, and a Ctrl-C stops it without leaving a half-written turn on the record.

The invariant that shapes the cancellation logic: **a partial turn is never recorded.**
A half-written assistant message would replay as something the model actually said.
When a run is cancelled the loop discards the in-flight turn and records the
cancellation as a fact about the run instead of a gap in it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from tapeloop.core.cancel import CancellationToken
from tapeloop.core.errors import Cancelled, ProviderError
from tapeloop.core.retry import RetryPolicy
from tapeloop.events import (
    Message,
    ModelResponse,
    Role,
    StopReason,
    ToolResult,
    Usage,
    results,
    system,
    user,
)
from tapeloop.providers.base import ModelClient
from tapeloop.providers.stream import StreamEnd, StreamEvent, TextDelta
from tapeloop.record.base import Event, InMemoryStore, TranscriptStore
from tapeloop.tools.registry import Registry

DEFAULT_SYSTEM = (
    "You are a careful engineering assistant working inside a single directory. "
    "Use the tools to inspect and change files. Do the smallest thing that "
    "satisfies the request, then stop and say what you did."
)

OnDelta = Callable[[StreamEvent], None]


@dataclass(slots=True)
class RunResult:
    messages: list[Message]
    stop_reason: StopReason
    steps: int
    usage: Usage
    text: str | None = None
    cancelled: bool = False
    """Transport-level, deliberately separate from ``stop_reason``.

    stop_reason is what the *provider* said. Cancellation is something that happened
    to us. Folding one into the other would make a recorded run unable to distinguish
    "the model finished" from "we stopped it".
    """


@dataclass(slots=True)
class Agent:
    """Wires a client, a registry, and a store into a runnable loop."""

    client: ModelClient
    registry: Registry
    model: str
    store: TranscriptStore = field(default_factory=InMemoryStore)
    system_prompt: str = DEFAULT_SYSTEM
    max_steps: int = 12
    max_tokens: int = 4096
    retry: RetryPolicy = field(default_factory=RetryPolicy)

    def run(
        self,
        task: str,
        *,
        history: Sequence[Message] | None = None,
        on_delta: OnDelta | None = None,
        token: CancellationToken | None = None,
    ) -> RunResult:
        """Run to completion, cancellation, or the step ceiling.

        Passing ``on_delta`` switches to streaming; the callback sees every delta and
        the assembled response still comes back the same way.
        """
        messages: list[Message] = list(history) if history else [system(self.system_prompt)]
        messages.append(user(task))

        totals = Usage()
        stop = StopReason.OTHER
        step = 0
        cancelled = False

        self.store.append(
            Event(
                kind="run_start",
                step=0,
                payload={
                    "model": self.model,
                    "provider": self.client.provider_id,
                    "tools": [t.name for t in self.registry.specs()],
                    "streaming": on_delta is not None,
                },
            )
        )

        for step in range(self.max_steps):
            if token and token.cancelled:
                cancelled = True
                break
            try:
                response = self.retry.call(
                    lambda: self._one_turn(messages, on_delta=on_delta, token=token),
                    token=token,
                )
            except Cancelled:
                # Nothing is appended: the in-flight turn is discarded whole.
                cancelled = True
                break

            totals = Usage(
                input_tokens=totals.input_tokens + response.usage.input_tokens,
                output_tokens=totals.output_tokens + response.usage.output_tokens,
                cached_input_tokens=totals.cached_input_tokens + response.usage.cached_input_tokens,
            )
            messages.append(response.message)
            stop = response.stop_reason

            self.store.append(
                Event(
                    kind="model_response",
                    step=step,
                    payload={
                        "stop_reason": stop.value,
                        "tool_calls": [c.name for c in response.message.tool_calls],
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                    },
                )
            )

            if stop is not StopReason.TOOL_USE or not response.message.tool_calls:
                break

            batch: list[ToolResult] = []
            for call in response.message.tool_calls:
                spec = self.registry.get(call.name)
                content = self.registry.dispatch(call.name, call.arguments)
                batch.append(
                    ToolResult(
                        call_id=call.id, content=content, is_error=content.startswith("ERROR:")
                    )
                )
                self.store.append(
                    Event(
                        kind="tool_result",
                        step=step,
                        payload={
                            "tool": call.name,
                            "effect": spec.effect.value if spec else "unknown",
                            "is_error": batch[-1].is_error,
                        },
                    )
                )
            messages.append(results(*batch))
        else:
            stop = StopReason.OTHER

        if cancelled:
            self.store.append(
                Event(
                    kind="cancelled",
                    step=step,
                    payload={"reason": token.reason if token else "cancelled"},
                )
            )
        self.store.append(
            Event(
                kind="run_end",
                step=step,
                payload={"stop_reason": stop.value, "cancelled": cancelled},
            )
        )

        text = next(
            (m.text for m in reversed(messages) if m.role is Role.ASSISTANT and m.text), None
        )
        return RunResult(
            messages=messages,
            stop_reason=stop,
            steps=step + 1,
            usage=totals,
            text=text,
            cancelled=cancelled,
        )

    def _one_turn(
        self,
        messages: Sequence[Message],
        *,
        on_delta: OnDelta | None,
        token: CancellationToken | None,
    ) -> ModelResponse:
        if on_delta is None:
            return self.client.complete(
                model=self.model,
                messages=messages,
                tools=self.registry.specs(),
                max_tokens=self.max_tokens,
            )
        return self._stream_turn(messages, on_delta=on_delta, token=token)

    def _stream_turn(
        self,
        messages: Sequence[Message],
        *,
        on_delta: OnDelta,
        token: CancellationToken | None,
    ) -> ModelResponse:
        """Consume a stream, checking for cancellation between chunks.

        Retry has a subtlety here. Once any delta has reached the caller, the failure
        is no longer safely retryable: restarting the stream would re-emit text the
        user has already seen. So a mid-stream failure is re-raised as non-retryable,
        while a failure before the first delta stays retryable and behaves exactly
        like a failed non-streaming call.
        """
        emitted = False
        final: ModelResponse | None = None
        try:
            for event in self.client.stream(
                model=self.model,
                messages=messages,
                tools=self.registry.specs(),
                max_tokens=self.max_tokens,
            ):
                if token and token.cancelled:
                    raise Cancelled(token.reason)
                if isinstance(event, StreamEnd):
                    final = event.response
                    break
                emitted = emitted or isinstance(event, TextDelta)
                on_delta(event)
        except ProviderError as e:
            if emitted and e.retryable:
                raise _NotRetryableMidStream(str(e)) from e
            raise

        if final is None:
            raise _NotRetryableMidStream("stream ended without a StreamEnd event")
        return final


class _NotRetryableMidStream(ProviderError):
    """A transient error that stopped being safe to retry once output was shown."""

    retryable = False
