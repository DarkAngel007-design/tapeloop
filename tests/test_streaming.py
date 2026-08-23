"""M2 — streaming, partial-JSON accumulation, retries, cancellation. Zero API spend."""

from __future__ import annotations

import json

from tapeloop.providers.stream import ToolCallAccumulator, ToolCallDelta


def test_fragmented_tool_arguments_reassemble() -> None:
    """The core streaming problem: arguments arrive split at arbitrary points.

    Nothing here is valid JSON until the last fragment lands.
    """
    acc = ToolCallAccumulator()
    for delta in [
        ToolCallDelta(index=0, id="call_a", name="write_file", arguments_fragment='{"pa'),
        ToolCallDelta(index=0, arguments_fragment='th": "out'),
        ToolCallDelta(index=0, arguments_fragment='.txt", "content": "hi"}'),
    ]:
        acc.add(delta)

    calls = acc.finish()
    assert len(calls) == 1
    assert calls[0].id == "call_a"
    assert calls[0].name == "write_file"
    assert calls[0].arguments == {"path": "out.txt", "content": "hi"}


def test_interleaved_calls_stay_separate() -> None:
    """Two calls stream at once, interleaved by index. They must not merge."""
    acc = ToolCallAccumulator()
    for delta in [
        ToolCallDelta(index=0, id="a", name="read_file", arguments_fragment='{"path"'),
        ToolCallDelta(index=1, id="b", name="write_file", arguments_fragment='{"path": "x",'),
        ToolCallDelta(index=0, arguments_fragment=': "in.txt"}'),
        ToolCallDelta(index=1, arguments_fragment=' "content": "y"}'),
    ]:
        acc.add(delta)

    calls = acc.finish()
    assert [c.id for c in calls] == ["a", "b"], "ordered by stream index"
    assert calls[0].arguments == {"path": "in.txt"}
    assert calls[1].arguments == {"path": "x", "content": "y"}


def test_malformed_arguments_are_preserved_not_dropped() -> None:
    """A call the model made is a call the model made, even if its JSON never closed.

    Keeping the raw text lets the loop hand back a readable error the model can fix.
    """
    acc = ToolCallAccumulator()
    acc.add(ToolCallDelta(index=0, id="a", name="f", arguments_fragment='{"path": '))
    calls = acc.finish()
    assert calls[0].arguments == {"__malformed__": '{"path": '}


def test_incomplete_call_without_a_name_is_skipped() -> None:
    acc = ToolCallAccumulator()
    acc.add(ToolCallDelta(index=0, arguments_fragment="{}"))
    assert acc.finish() == ()


def test_render_partial_repairs_for_display() -> None:
    """Display-only repair. Its output is a picture, never parsed back into arguments."""
    acc = ToolCallAccumulator()
    cases = {
        '{"path": "out': '{"path": "out"}',
        '{"a": {"b": 1': '{"a": {"b": 1}}',
        '{"items": ["x", "y': '{"items": ["x", "y"]}',
        '{"done": true}': '{"done": true}',
    }
    for i, (fragment, expected) in enumerate(cases.items()):
        acc.add(ToolCallDelta(index=i, id=str(i), name="f", arguments_fragment=fragment))
        rendered = acc.render_partial(i)
        assert rendered == expected, f"{fragment!r} -> {rendered!r}"
        json.loads(rendered)  # the repair must at least be parseable


def test_render_partial_handles_a_dangling_escape() -> None:
    """A fragment can split mid-escape-sequence. Closing the string would corrupt it."""
    acc = ToolCallAccumulator()
    acc.add(ToolCallDelta(index=0, id="a", name="f", arguments_fragment='{"s": "a\\'))
    assert acc.render_partial(0) == '{"s": "a"}'
