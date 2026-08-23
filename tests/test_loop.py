"""The M1 loop, end to end, against a fake ModelClient. Zero API spend."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

from tapeloop.core.loop import Agent
from tapeloop.events import (
    Message,
    ModelResponse,
    Opaque,
    Role,
    StopReason,
    ToolCall,
    Usage,
)
from tapeloop.providers.stream import StreamEnd, StreamEvent, TextDelta
from tapeloop.record.base import InMemoryStore
from tapeloop.tools import builtin
from tapeloop.tools.registry import Registry, ToolSpec


class FakeClient:
    """A scripted ModelClient. Records the history it was handed at each call."""

    def __init__(self, script: list[ModelResponse]) -> None:
        self._script = script
        self.seen: list[list[Message]] = []

    @property
    def provider_id(self) -> str:
        return "fake"

    def complete(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        max_tokens: int = 4096,
    ) -> ModelResponse:
        self.seen.append(list(messages))
        return self._script.pop(0)

    def stream(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        max_tokens: int = 4096,
    ) -> Iterator[StreamEvent]:
        """Replay the scripted response as deltas, so streaming callers see the same run."""
        response = self.complete(model=model, messages=messages, tools=tools)
        if response.message.text:
            for word in response.message.text.split(" "):
                yield TextDelta(text=word + " ")
        yield StreamEnd(response=response)

    def count_tokens(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
    ) -> int:
        return 0


def _calls(*calls: ToolCall) -> ModelResponse:
    return ModelResponse(
        message=Message(role=Role.ASSISTANT, tool_calls=calls),
        stop_reason=StopReason.TOOL_USE,
        usage=Usage(input_tokens=10, output_tokens=5),
    )


def _done(text: str) -> ModelResponse:
    return ModelResponse(
        message=Message(role=Role.ASSISTANT, text=text),
        stop_reason=StopReason.END_TURN,
        usage=Usage(input_tokens=10, output_tokens=5),
    )


def test_two_tool_task_end_to_end(tmp_path: Path) -> None:
    (tmp_path / "seed.txt").write_text("hello", encoding="utf-8")
    client = FakeClient(
        [
            _calls(
                ToolCall(id="c1", name="read_file", arguments={"path": "seed.txt"}),
                ToolCall(
                    id="c2", name="write_file", arguments={"path": "out.txt", "content": "HI"}
                ),
            ),
            _done("Read seed.txt and wrote out.txt."),
        ]
    )
    store = InMemoryStore()
    agent = Agent(
        client=client,
        registry=builtin.build(tmp_path),
        model="fake-1",
        store=store,
    )
    result = agent.run("do the thing")

    assert result.stop_reason is StopReason.END_TURN
    assert result.text == "Read seed.txt and wrote out.txt."
    assert result.steps == 2
    assert result.usage.output_tokens == 10
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "HI"

    # Parallel results ride in ONE canonical message, as a set. Adapters lay it out.
    history = client.seen[1]
    result_msgs = [m for m in history if m.role is Role.TOOL_RESULTS]
    assert len(result_msgs) == 1
    assert len(result_msgs[0].tool_results) == 2
    assert [r.call_id for r in result_msgs[0].tool_results] == ["c1", "c2"]
    assert result_msgs[0].tool_results[0].content == "hello"


def test_effect_class_is_recorded_not_inferred(tmp_path: Path) -> None:
    """Replay policy depends on the effect class, so the tape records what it was."""
    client = FakeClient(
        [_calls(ToolCall(id="c1", name="read_file", arguments={"path": "x"})), _done("ok")]
    )
    store = InMemoryStore()
    Agent(client=client, registry=builtin.build(tmp_path), model="m", store=store).run("go")

    tool_events = [e for e in store.events() if e.kind == "tool_result"]
    assert tool_events[0].payload["effect"] == "read"
    assert tool_events[0].payload["is_error"] is True  # the file does not exist


def test_tool_failure_is_flagged_and_the_run_continues(tmp_path: Path) -> None:
    client = FakeClient(
        [
            _calls(ToolCall(id="c1", name="read_file", arguments={"path": "missing.txt"})),
            _done("That file is missing."),
        ]
    )
    agent = Agent(client=client, registry=builtin.build(tmp_path), model="m")
    result = agent.run("read it")

    assert result.text == "That file is missing."
    batch = next(m for m in client.seen[1] if m.role is Role.TOOL_RESULTS)
    sent = batch.tool_results[0]
    assert sent.is_error
    assert sent.content.startswith("ERROR: FileNotFoundError")


def test_max_steps_stops_the_run(tmp_path: Path) -> None:
    client = FakeClient(
        [_calls(ToolCall(id=f"c{i}", name="list_files", arguments={})) for i in range(5)]
    )
    agent = Agent(client=client, registry=builtin.build(tmp_path), model="m", max_steps=3)
    result = agent.run("loop forever")
    assert result.steps == 3
    assert result.stop_reason is StopReason.OTHER


def test_opaque_payloads_survive_the_round_trip(tmp_path: Path) -> None:
    """Contract 5: the runtime carries what it cannot interpret, untouched."""
    blob = {"encrypted": "abc123"}
    client = FakeClient(
        [
            ModelResponse(
                message=Message(
                    role=Role.ASSISTANT,
                    text="thought about it",
                    opaque=(Opaque(provider="fake", kind="reasoning", data=blob),),
                ),
                stop_reason=StopReason.END_TURN,
            )
        ]
    )
    agent = Agent(client=client, registry=Registry(), model="m")
    result = agent.run("think")
    carried = result.messages[-1].opaque[0]
    assert carried.provider == "fake"
    assert carried.data is blob, "opaque data must be the same object, never rebuilt"


def test_path_confinement_holds(tmp_path: Path) -> None:
    reg = builtin.build(tmp_path)
    out = reg.dispatch("write_file", {"path": "../escaped.txt", "content": "x"})
    assert out.startswith("ERROR: ValueError")
    assert not (tmp_path.parent / "escaped.txt").exists()
