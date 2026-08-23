"""M2 ship criterion: survives a forced 429 and a mid-stream Ctrl-C without corrupting the tape."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from tapeloop.core.cancel import CancellationToken
from tapeloop.core.errors import (
    AuthenticationFailed,
    Cancelled,
    ProviderUnavailable,
    RateLimited,
    RequestInvalid,
)
from tapeloop.core.loop import Agent
from tapeloop.core.retry import RetryPolicy
from tapeloop.events import Message, ModelResponse, Role, StopReason, Usage
from tapeloop.providers.stream import StreamEnd, StreamEvent, TextDelta
from tapeloop.record.base import InMemoryStore
from tapeloop.tools import builtin
from tapeloop.tools.registry import ToolSpec

FAST = RetryPolicy(base_delay=0.001, max_delay=0.01, seed=1)


def _done(text: str) -> ModelResponse:
    return ModelResponse(
        message=Message(role=Role.ASSISTANT, text=text),
        stop_reason=StopReason.END_TURN,
        usage=Usage(input_tokens=1, output_tokens=1),
    )


class FlakyClient:
    """Raises a scripted sequence of errors, then succeeds."""

    def __init__(self, failures: list[Exception], *, deltas: list[str] | None = None) -> None:
        self.failures = failures
        self.deltas = deltas or []
        self.attempts = 0

    @property
    def provider_id(self) -> str:
        return "flaky"

    def complete(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        max_tokens: int = 4096,
    ) -> ModelResponse:
        self.attempts += 1
        if self.failures:
            raise self.failures.pop(0)
        return _done("recovered")

    def stream(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        max_tokens: int = 4096,
    ) -> Iterator[StreamEvent]:
        self.attempts += 1
        for text in self.deltas:
            yield TextDelta(text=text)
        if self.failures:
            raise self.failures.pop(0)
        yield StreamEnd(response=_done("recovered"))

    def count_tokens(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
    ) -> int:
        return 0


# ----------------------------------------------------------------- retries
def test_rate_limit_is_retried_and_the_run_completes(tmp_path: Path) -> None:
    client = FlakyClient([RateLimited("429"), RateLimited("429")])
    agent = Agent(client=client, registry=builtin.build(tmp_path), model="m", retry=FAST)
    result = agent.run("go")
    assert result.text == "recovered"
    assert client.attempts == 3


def test_non_retryable_errors_propagate_immediately(tmp_path: Path) -> None:
    """A bad request retried is a bad request twice."""
    for error in (RequestInvalid("400"), AuthenticationFailed("401")):
        client = FlakyClient([error] * 5)
        agent = Agent(client=client, registry=builtin.build(tmp_path), model="m", retry=FAST)
        with pytest.raises(type(error)):
            agent.run("go")
        assert client.attempts == 1, f"{type(error).__name__} must not be retried"


def test_retries_are_bounded(tmp_path: Path) -> None:
    client = FlakyClient([ProviderUnavailable("503")] * 10)
    agent = Agent(
        client=client,
        registry=builtin.build(tmp_path),
        model="m",
        retry=RetryPolicy(max_attempts=3, base_delay=0.001, seed=1),
    )
    with pytest.raises(ProviderUnavailable):
        agent.run("go")
    assert client.attempts == 3


def test_retry_after_beats_computed_backoff() -> None:
    """The server knows things we do not. Ignoring Retry-After gets you throttled harder."""
    policy = RetryPolicy(base_delay=0.5, max_delay=30.0, seed=1)
    assert policy.delay_for(1, retry_after=7.0) == 7.0
    assert policy.delay_for(1, retry_after=999.0) == 30.0, "still capped by max_delay"


def test_backoff_grows_and_is_deterministic() -> None:
    """Jitter is seeded: two identical processes back off identically (Contract 1)."""
    a = [RetryPolicy(seed=42).delay_for(i) for i in range(1, 5)]
    b = [RetryPolicy(seed=42).delay_for(i) for i in range(1, 5)]
    assert a == b, "same seed must give the same delays"
    assert a[0] < a[-1], "backoff must grow"
    assert all(d <= 30.0 for d in a)


# ------------------------------------------------------------ cancellation
def test_cancel_between_steps_records_it_and_stops(tmp_path: Path) -> None:
    client = FlakyClient([])
    token = CancellationToken()
    token.cancel("interrupted by user")
    store = InMemoryStore()
    agent = Agent(client=client, registry=builtin.build(tmp_path), model="m", store=store)

    result = agent.run("go", token=token)
    assert result.cancelled
    assert client.attempts == 0, "cancelled before any call was made"

    kinds = [e.kind for e in store.events()]
    assert "cancelled" in kinds
    assert kinds[-1] == "run_end"


def test_cancel_mid_stream_leaves_no_partial_turn(tmp_path: Path) -> None:
    """THE ship criterion. A half-written assistant message would replay as real speech."""
    token = CancellationToken()
    seen: list[str] = []

    class CancellingClient(FlakyClient):
        def stream(self, **kwargs: object) -> Iterator[StreamEvent]:
            yield TextDelta(text="I am thinking ")
            token.cancel("interrupted by user")  # Ctrl-C lands here
            yield TextDelta(text="and this never arrives")
            yield StreamEnd(response=_done("should not be recorded"))

    store = InMemoryStore()
    agent = Agent(
        client=CancellingClient([]), registry=builtin.build(tmp_path), model="m", store=store
    )
    result = agent.run("go", on_delta=lambda e: seen.append(getattr(e, "text", "")), token=token)

    assert result.cancelled
    assert result.text is None, "the partial turn must not be recorded"
    assert not [m for m in result.messages if m.role is Role.ASSISTANT]
    assert "cancelled" in [e.kind for e in store.events()]
    # The record ends cleanly: no model_response for the abandoned turn.
    assert "model_response" not in [e.kind for e in store.events()]


def test_the_ship_criterion(tmp_path: Path) -> None:
    """Forced 429 AND a mid-stream interrupt, in one run. Record stays consistent."""
    token = CancellationToken()

    class RateLimitedThenCancelled(FlakyClient):
        def stream(self, **kwargs: object) -> Iterator[StreamEvent]:
            self.attempts += 1
            if self.attempts <= 2:
                raise RateLimited("429")
                yield  # pragma: no cover - unreachable, makes this a generator
            yield TextDelta(text="starting ")
            token.cancel("interrupted by user")
            yield StreamEnd(response=_done("unreachable"))

    client = RateLimitedThenCancelled([])
    store = InMemoryStore()
    agent = Agent(
        client=client,
        registry=builtin.build(tmp_path),
        model="m",
        store=store,
        retry=FAST,
    )
    result = agent.run("go", on_delta=lambda _e: None, token=token)

    assert client.attempts == 3, "two 429s retried, third attempt reached the stream"
    assert result.cancelled
    assert result.text is None

    kinds = [e.kind for e in store.events()]
    assert kinds[0] == "run_start"
    assert kinds[-1] == "run_end"
    assert "cancelled" in kinds
    assert "model_response" not in kinds, "no turn was completed, so none is recorded"


def test_a_cancelled_backoff_wakes_immediately() -> None:
    """Ctrl-C during a 30-second backoff must be felt at once, not thirty seconds later."""
    token = CancellationToken()
    token.cancel("interrupted by user")
    policy = RetryPolicy(base_delay=30.0, max_attempts=3)

    calls = 0

    def always_429() -> str:
        nonlocal calls
        calls += 1
        raise RateLimited("429")

    with pytest.raises(Cancelled):
        policy.call(always_429, token=token)
    assert calls == 0, "the token was already set; no attempt should be made"
