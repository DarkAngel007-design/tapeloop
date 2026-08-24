"""M1 ship criterion: the four Protocols hold, and the unbuilt adapter type-checks."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tapeloop.eval.base import ExactMatch, Grader, Predicate
from tapeloop.events import Message, Role, StopReason, ToolCall, ToolResult, results, user
from tapeloop.providers.anthropic import AnthropicClient
from tapeloop.providers.base import ModelClient
from tapeloop.providers.openai import OpenAIClient, render_messages, render_tools
from tapeloop.record.base import Event, InMemoryStore, TranscriptStore
from tapeloop.sandbox.base import Executor
from tapeloop.sandbox.subprocess import SubprocessExecutor
from tapeloop.tools.effects import Effect
from tapeloop.tools.registry import Registry

# --------------------------------------------------------------------------
# The design check that justifies ADR-0001. This block never executes; pyright
# evaluates it. If ModelClient ever grows a parameter that only makes sense for
# OpenAI, the Anthropic line below stops type-checking -- which is the cheapest
# possible warning that the abstraction has become provider-shaped.
if TYPE_CHECKING:

    def _conforms(_: ModelClient) -> None: ...

    _conforms(AnthropicClient.__new__(AnthropicClient))
    _conforms(OpenAIClient.__new__(OpenAIClient))
# --------------------------------------------------------------------------


def test_anthropic_adapter_is_signatures_only() -> None:
    """It must not work. Its whole job is to be type-checked, not run."""
    with pytest.raises(NotImplementedError, match="signatures-only"):
        AnthropicClient()


def test_protocols_are_satisfied_at_runtime() -> None:
    assert isinstance(SubprocessExecutor(), Executor)
    assert isinstance(InMemoryStore(), TranscriptStore)
    assert isinstance(ExactMatch(), Grader)
    assert isinstance(Predicate(lambda a, b: a == b), Grader)


def test_executor_names_its_isolation_honestly() -> None:
    """A recorded run must say what protected it, not what the docs claim today."""
    assert SubprocessExecutor().isolation == "subprocess (no isolation)"


def test_executor_runs_and_times_out(tmp_path: Path) -> None:
    ex = SubprocessExecutor()
    ok = ex.run("echo hello", cwd=tmp_path)
    assert ok.exit_code == 0
    assert "hello" in ok.as_tool_output()

    slow = ex.run("sleep 5", cwd=tmp_path, timeout=0.2)
    assert slow.timed_out
    assert slow.as_tool_output().startswith("ERROR: timed out")


# ------------------------------------------------------------ divergence #2
def test_openai_renderer_expands_the_result_set() -> None:
    """The tape holds one TOOL_RESULTS message; OpenAI wants one message per result.

    Anthropic wants the exact opposite -- all results inside a single message. That
    contradiction is why the tape stores the set rather than either layout.
    """
    messages = [
        user("go"),
        Message(
            role=Role.ASSISTANT,
            tool_calls=(
                ToolCall(id="c1", name="read_file", arguments={"path": "a"}),
                ToolCall(id="c2", name="read_file", arguments={"path": "b"}),
            ),
        ),
        results(ToolResult(call_id="c1", content="A"), ToolResult(call_id="c2", content="B")),
    ]
    wire = render_messages(messages)

    assistant = wire[1]
    assert len(assistant["tool_calls"]) == 2
    # arguments are re-serialized as a JSON *string*, not left as an object
    assert assistant["tool_calls"][0]["function"]["arguments"] == '{"path": "a"}'

    tool_msgs = [m for m in wire if m["role"] == "tool"]
    assert len(tool_msgs) == 2, "one wire message per result"
    assert [m["tool_call_id"] for m in tool_msgs] == ["c1", "c2"]


def test_openai_tool_rendering_requests_strict_mode() -> None:
    reg = Registry()

    @reg.tool(effect=Effect.READ)
    def peek(path: str) -> str:
        """Look at something.

        Args:
            path: Where to look.
        """
        return ""

    rendered = render_tools(reg.specs())[0]
    assert rendered["function"]["strict"] is True
    assert rendered["function"]["parameters"]["additionalProperties"] is False
    assert rendered["function"]["description"] == "Look at something."


def test_stop_reason_vocabulary_is_normalized() -> None:
    """An unmapped provider value must degrade to OTHER, never look like a finished turn."""
    from tapeloop.providers.openai import _STOP  # pyright: ignore[reportPrivateUsage]

    assert _STOP["tool_calls"] is StopReason.TOOL_USE
    assert _STOP.get("some_future_reason", StopReason.OTHER) is StopReason.OTHER


def test_store_collects_events() -> None:
    store = InMemoryStore()
    store.append(Event(kind="a", step=0))
    store.append(Event(kind="b", step=1))
    assert [e.kind for e in store.events()] == ["a", "b"]


# ------------------------------------------------------- adapter streaming
def test_openai_adapter_streams_and_assembles(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise OpenAIClient.stream() itself against fabricated chunks, no network.

    This is the path the accumulator tests do not cover: chunk -> delta -> assembled
    ModelResponse, including usage arriving only on the final chunk.
    """
    from types import SimpleNamespace

    from tapeloop.providers.stream import StreamEnd, TextDelta, ToolCallDelta

    def _create(**_kw: object) -> object:
        return iter(chunks)

    def chunk(
        *,
        content: str | None = None,
        calls: list[object] | None = None,
        finish: str | None = None,
        usage: object | None = None,
    ) -> object:
        delta = SimpleNamespace(content=content, tool_calls=calls)
        choice = SimpleNamespace(delta=delta, finish_reason=finish)
        return SimpleNamespace(choices=[choice], usage=usage)

    def call(index: int, cid: str | None, name: str | None, args: str) -> object:
        return SimpleNamespace(
            index=index, id=cid, function=SimpleNamespace(name=name, arguments=args)
        )

    chunks = [
        chunk(content="Look"),
        chunk(content="ing..."),
        chunk(calls=[call(0, "c1", "read_file", '{"pa')]),
        chunk(calls=[call(0, None, None, 'th": "a.txt"}')]),
        chunk(finish="tool_calls"),
        # Usage arrives alone on the last chunk when stream_options.include_usage is set.
        chunk(usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7)),
    ]

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
    client = OpenAIClient(client=fake)  # pyright: ignore[reportArgumentType]

    events = list(client.stream(model="m", messages=[user("go")]))
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["Look", "ing..."]
    assert len([e for e in events if isinstance(e, ToolCallDelta)]) == 2

    end = events[-1]
    assert isinstance(end, StreamEnd), "a stream must always end with exactly one StreamEnd"
    assert end.response.stop_reason is StopReason.TOOL_USE
    assert end.response.message.text == "Looking..."
    assert end.response.message.tool_calls[0].arguments == {"path": "a.txt"}
    assert end.response.usage.output_tokens == 7, "usage from the final chunk must survive"


def test_sdk_exceptions_map_to_the_taxonomy() -> None:
    """Only the retryable/not-retryable answer matters at the call site."""
    # openai 3.x vendors its HTTP layer as `httpx2`, not `httpx`. Reaching for the
    # SDK's own dependency keeps this test honest -- it constructs the exact exception
    # type the SDK would raise, rather than a look-alike.
    httpx2 = pytest.importorskip(
        "httpx2",
        reason="openai>=3 vendors its HTTP layer as httpx2; the runtime floor is 2.0",
    )
    import openai

    from tapeloop.core.errors import (
        AuthenticationFailed,
        ProviderUnavailable,
        RateLimited,
        RequestInvalid,
    )
    from tapeloop.providers.openai import translate

    def status(code: int) -> openai.APIStatusError:
        response = httpx2.Response(code, request=httpx2.Request("POST", "https://x"))
        return openai.APIStatusError("boom", response=response, body=None)

    assert isinstance(translate(status(503)), ProviderUnavailable)
    assert isinstance(translate(status(400)), RequestInvalid)
    assert isinstance(
        translate(openai.APIConnectionError(request=httpx2.Request("POST", "https://x"))),
        ProviderUnavailable,
    )
    # Anything unrecognized is NOT retryable: retrying an error we do not understand
    # is how a permanent misconfiguration burns a budget.
    assert translate(ValueError("who knows")).retryable is False
    assert RateLimited("x").retryable is True
    assert AuthenticationFailed("x").retryable is False


def test_sdk_exceptions_reach_the_retry_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """`translate` was written at M2 and never called, for two releases.

    Every retry test raised `ProviderError` directly, so the taxonomy, the backoff and
    the Retry-After handling were all exercised on a path real code never took: an SDK
    exception propagated straight past `RetryPolicy`, which only catches `ProviderError`.
    Found by pointing the runtime at a local Ollama and watching a raw
    `openai.InternalServerError` come out the top of the stack.
    """
    import openai

    # openai>=3 vendors its HTTP layer as httpx2; the declared floor is 2.0, and the
    # dependency-floor CI job runs the suite pinned there. This exact import was
    # caught once already in another test.
    httpx2 = pytest.importorskip("httpx2", reason="needs openai>=3")

    from tapeloop.core.errors import ProviderUnavailable, RateLimited
    from tapeloop.providers.openai import OpenAIClient

    def raiser(status: int) -> object:
        response = httpx2.Response(status, request=httpx2.Request("POST", "https://x"))

        class Boom:
            class chat:
                class completions:
                    @staticmethod
                    def create(**_kw: object) -> object:
                        raise openai.APIStatusError("boom", response=response, body=None)

        return Boom()

    for status, expected in ((500, ProviderUnavailable), (503, ProviderUnavailable)):
        client = OpenAIClient(client=raiser(status), provider_id="test")  # pyright: ignore[reportArgumentType]
        with pytest.raises(expected):
            client.complete(model="m", messages=[user("hi")])

    # A bare 429 from an OpenAI-compatible server, not the SDK's RateLimitError
    # subclass, must still be recognised — otherwise it reads as a bad request and
    # the run gives up on something that would have succeeded.
    rate = OpenAIClient(client=raiser(429), provider_id="test")  # pyright: ignore[reportArgumentType]
    with pytest.raises(RateLimited) as caught:
        rate.complete(model="m", messages=[user("hi")])
    assert caught.value.retryable, "a 429 must be retryable or the whole policy is inert"
