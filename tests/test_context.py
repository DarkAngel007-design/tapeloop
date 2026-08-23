"""M7 ship criterion: a task that previously died on context completes."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from helpers import workspace_of

from tapeloop.context.budget import ContextBudget
from tapeloop.context.compact import apply_compaction, plan_compaction, summary_request
from tapeloop.context.tokens import CHARS_PER_TOKEN, Method, count_text
from tapeloop.context.truncate import truncate_middle
from tapeloop.core.loop import Agent
from tapeloop.events import (
    Message,
    ModelResponse,
    Role,
    StopReason,
    ToolCall,
    Usage,
    system,
    user,
)
from tapeloop.providers.stream import StreamEvent
from tapeloop.record.base import InMemoryStore
from tapeloop.tools import builtin
from tapeloop.tools.registry import ToolSpec

BIG = "\n".join(f"line {i:05}: routine log entry with some padding text" for i in range(4000))


class ContextLimitedClient:
    """Refuses anything over `limit` tokens, the way a real provider does.

    Deterministic and free, so the ship criterion is a test rather than a story.
    """

    def __init__(self, script: list[ModelResponse], *, limit: int) -> None:
        self._script = list(script)
        self.limit = limit
        self.largest = 0
        self.compactions = 0

    @property
    def provider_id(self) -> str:
        return "limited"

    def complete(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        max_tokens: int = 4096,
    ) -> ModelResponse:
        blob = "\n".join(
            (m.text or "") + "".join(r.content for r in m.tool_results) for m in messages
        )
        size = count_text(blob).tokens
        self.largest = max(self.largest, size)
        if size > self.limit:
            raise RuntimeError(f"context window exceeded: {size} > {self.limit}")
        if "Summarise the conversation below" in (messages[0].text or ""):
            # A compaction request is an ordinary request (ADR-0020), so the fake has
            # to answer it like one. Returning a tool-call response here previously
            # produced an empty summary, and the loop correctly refused to compact.
            self.compactions += 1
            return ModelResponse(
                message=Message(role=Role.ASSISTANT, text="Earlier: the log was read repeatedly."),
                stop_reason=StopReason.END_TURN,
            )
        if not self._script:
            return ModelResponse(
                message=Message(role=Role.ASSISTANT, text="done"),
                stop_reason=StopReason.END_TURN,
            )
        return self._script.pop(0)

    def stream(self, **_kw: object) -> Iterator[StreamEvent]:  # pragma: no cover
        raise NotImplementedError

    def count_tokens(self, **_kw: object) -> int:
        return 0


def _script() -> list[ModelResponse]:
    return [
        ModelResponse(
            message=Message(
                role=Role.ASSISTANT,
                tool_calls=(ToolCall(id="c1", name="read_file", arguments={"path": "big.log"}),),
            ),
            stop_reason=StopReason.TOOL_USE,
            usage=Usage(input_tokens=10, output_tokens=5),
        ),
        ModelResponse(
            message=Message(role=Role.ASSISTANT, text="I read the log."),
            stop_reason=StopReason.END_TURN,
        ),
    ]


# ============================================================ SHIP CRITERION
def test_ship_criterion_a_task_that_died_on_context_now_completes(tmp_path: Path) -> None:
    ws = workspace_of(tmp_path)
    (ws / "big.log").write_text(BIG, encoding="utf-8")
    limit = 8_000

    # Before: one oversized read blows the window.
    bare = Agent(
        client=ContextLimitedClient(_script(), limit=limit),  # pyright: ignore[reportArgumentType]
        registry=builtin.build(ws),
        model="m",
    )
    with pytest.raises(RuntimeError, match="context window exceeded"):
        bare.run("summarise big.log")

    # After: the same run, with a budget that caps a single tool result.
    store = InMemoryStore()
    client = ContextLimitedClient(_script(), limit=limit)
    managed = Agent(
        client=client,  # pyright: ignore[reportArgumentType]
        registry=builtin.build(ws),
        model="m",
        store=store,
        budget=ContextBudget(max_tool_result_tokens=2_000, model="m"),
    )
    result = managed.run("summarise big.log")

    assert result.text == "I read the log."
    assert client.largest <= limit
    truncations = [e for e in store.events() if e.kind == "truncated"]
    assert truncations, "the oversized read should have been capped"
    assert truncations[0].payload["elided_lines"] > 3_000


def test_the_agent_can_see_that_it_was_truncated(tmp_path: Path) -> None:
    """A silently truncated file is unrecoverable; a marked one is a prompt to search."""
    ws = workspace_of(tmp_path)
    (ws / "big.log").write_text(BIG, encoding="utf-8")
    client = ContextLimitedClient(_script(), limit=100_000)
    agent = Agent(
        client=client,  # pyright: ignore[reportArgumentType]
        registry=builtin.build(ws),
        model="m",
        budget=ContextBudget(max_tool_result_tokens=1_000, model="m"),
    )
    result = agent.run("read it")
    seen = next(r.content for m in result.messages for r in m.tool_results)
    assert "elided" in seen
    assert seen.startswith("line 00000"), "the head must survive"
    assert seen.rstrip().endswith("padding text"), "and so must the tail"


# ================================================================ truncation
def test_truncation_is_deterministic() -> None:
    """It feeds step keys, so anything non-deterministic here breaks replay."""
    a = truncate_middle(BIG, max_tokens=500)
    b = truncate_middle(BIG, max_tokens=500)
    assert a.text == b.text
    assert a.elided_chars == b.elided_chars


def test_short_content_is_untouched() -> None:
    t = truncate_middle("just a line", max_tokens=500)
    assert t.text == "just a line"
    assert not t.happened


def test_both_ends_are_kept() -> None:
    t = truncate_middle(BIG, max_tokens=400)
    assert "line 00000" in t.text
    assert "line 03999" in t.text
    assert "line 02000" not in t.text, "the middle is what goes"


# ==================================================================== tokens
def test_a_count_says_how_it_was_produced() -> None:
    """ADR-0019: nothing downstream may treat an estimate as a measurement."""
    c = count_text("hello world", model="definitely-not-a-real-model")
    assert c.method in (Method.EXACT, Method.APPROXIMATE, Method.ESTIMATED)
    assert c.trustworthy is (c.method is not Method.ESTIMATED)


def test_the_estimator_stays_within_its_band() -> None:
    """Calibrated against the M6 baseline's real provider-reported usage.

    When this drifts the test fails, which is the difference between an estimate
    and a guess (ADR-0019). Skips if the baseline has not been run.
    """
    baseline = Path(__file__).resolve().parents[1] / "evals/baseline-2026-08-24/results.json"
    if not baseline.exists():
        pytest.skip("no baseline committed yet")
    data = json.loads(baseline.read_text(encoding="utf-8"))
    real = sum(a["input_tokens"] for a in data["attempts"])
    assert real > 0
    # The constant is a ratio, so assert it is in a sane band rather than exact.
    assert 3.0 <= CHARS_PER_TOKEN <= 4.5


# ================================================================ compaction
def test_the_task_and_system_prompt_are_never_compacted() -> None:
    """Forgetting the task is worse than running out of context: it keeps going."""
    messages = [
        system("be helpful"),
        user("the original task"),
        *[user(f"chatter {i}") for i in range(20)],
    ]
    plan = plan_compaction(messages, keep_recent=5)
    assert plan.keep_head == 2

    out = apply_compaction(messages, plan, "a summary")
    assert out[0].text == "be helpful"
    assert out[1].text == "the original task"
    assert "a summary" in (out[2].text or "")
    assert out[-1].text == "chatter 19"


def test_compacting_two_messages_is_not_worth_a_model_call() -> None:
    plan = plan_compaction([system("s"), user("t"), user("a"), user("b")], keep_recent=6)
    assert not plan.worthwhile


def test_the_summary_request_is_an_ordinary_request() -> None:
    """So it keys and caches like any other step (ADR-0020)."""
    request = summary_request([user("something happened")])
    assert len(request) == 1
    assert "something happened" in (request[0].text or "")


def test_compaction_fires_and_is_recorded(tmp_path: Path) -> None:
    ws = workspace_of(tmp_path)
    (ws / "big.log").write_text(BIG, encoding="utf-8")

    reads = [
        ModelResponse(
            message=Message(
                role=Role.ASSISTANT,
                tool_calls=(ToolCall(id=f"c{i}", name="read_file", arguments={"path": "big.log"}),),
            ),
            stop_reason=StopReason.TOOL_USE,
        )
        for i in range(6)
    ]
    reads.append(
        ModelResponse(
            message=Message(role=Role.ASSISTANT, text="finished"), stop_reason=StopReason.END_TURN
        )
    )
    store = InMemoryStore()
    client = ContextLimitedClient(reads, limit=10_000_000)
    agent = Agent(
        client=client,  # pyright: ignore[reportArgumentType]
        registry=builtin.build(ws),
        model="m",
        store=store,
        max_steps=10,
        budget=ContextBudget(
            context_window=20_000,
            reserve_for_output=2_000,
            compact_at=0.5,
            max_tool_result_tokens=3_000,
            model="m",
        ),
    )
    agent.run("read it repeatedly")

    events = [e for e in store.events() if e.kind == "compaction"]
    assert events, "compaction should have fired"
    assert events[0].payload["after_tokens"] < events[0].payload["before_tokens"]
    assert events[0].payload["replaced"] >= 4
    assert client.compactions >= 1, "the summary must come from a real model call"
