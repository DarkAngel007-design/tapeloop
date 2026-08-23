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
