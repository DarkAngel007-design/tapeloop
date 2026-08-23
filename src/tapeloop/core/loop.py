"""The agent loop, now assembled from seams instead of hard-wired.

Structurally identical to M0 — call, dispatch, append, repeat. Every concrete
dependency has been replaced by one of the four Protocols, which is the whole
point of the milestone: M3 swaps the store, M5 swaps the executor, and the
Anthropic adapter swaps the client, none of them touching this file.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from tapeloop.events import (
    Message,
    Role,
    StopReason,
    ToolResult,
    Usage,
    results,
    system,
    user,
)
from tapeloop.providers.base import ModelClient
from tapeloop.record.base import Event, InMemoryStore, TranscriptStore
from tapeloop.tools.registry import Registry

DEFAULT_SYSTEM = (
    "You are a careful engineering assistant working inside a single directory. "
    "Use the tools to inspect and change files. Do the smallest thing that "
    "satisfies the request, then stop and say what you did."
)


@dataclass(slots=True)
class RunResult:
    messages: list[Message]
    stop_reason: StopReason
    steps: int
    usage: Usage
    text: str | None = None


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

    def run(self, task: str, *, history: Sequence[Message] | None = None) -> RunResult:
        messages: list[Message] = list(history) if history else [system(self.system_prompt)]
        messages.append(user(task))

        totals = Usage()
        stop = StopReason.OTHER
        step = 0

        self.store.append(
            Event(
                kind="run_start",
                step=0,
                payload={
                    "model": self.model,
                    "provider": self.client.provider_id,
                    "tools": [t.name for t in self.registry.specs()],
                },
            )
        )

        for step in range(self.max_steps):
            response = self.client.complete(
                model=self.model,
                messages=messages,
                tools=self.registry.specs(),
                max_tokens=self.max_tokens,
            )
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
                        call_id=call.id,
                        content=content,
                        is_error=content.startswith("ERROR:"),
                    )
                )
                self.store.append(
                    Event(
                        kind="tool_result",
                        step=step,
                        payload={
                            "tool": call.name,
                            # The effect class is recorded, not inferred later: replay
                            # policy depends on it, and it may change between versions.
                            "effect": spec.effect.value if spec else "unknown",
                            "is_error": batch[-1].is_error,
                        },
                    )
                )
            # One message, the whole set. Each adapter lays it out its own way.
            messages.append(results(*batch))
        else:
            stop = StopReason.OTHER

        text = next(
            (m.text for m in reversed(messages) if m.role is Role.ASSISTANT and m.text), None
        )
        self.store.append(Event(kind="run_end", step=step, payload={"stop_reason": stop.value}))
        return RunResult(
            messages=messages, stop_reason=stop, steps=step + 1, usage=totals, text=text
        )
