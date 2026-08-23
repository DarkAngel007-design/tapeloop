"""Canonical serialization. Everything downstream is built on these guarantees."""

from __future__ import annotations

import json

import pytest

from tapeloop.events import Message, Role, ToolCall, ToolResult, Usage
from tapeloop.record.canonical import NonCanonical, canonical_json, digest
from tapeloop.record.codec import decode_message, encode_history, encode_message, order_results


def test_key_order_and_whitespace_are_normalized() -> None:
    a = canonical_json({"b": 1, "a": 2})
    b = canonical_json({"a": 2, "b": 1})
    assert a == b == '{"a":2,"b":1}'


def test_unicode_forms_that_look_identical_hash_identically() -> None:
    """`é` is one code point or two. Same string to a human, different bytes to sha256.

    Without NFC a model that emits one form and a tape that stored the other never
    agree, and the cache misses forever with nothing to point at.
    """
    composed = "café"  # é
    decomposed = "café"  # e + combining acute
    assert composed != decomposed
    assert digest({"t": composed}) == digest({"t": decomposed})


def test_nan_and_infinity_are_rejected() -> None:
    """Python emits these by default, producing a file no other JSON parser reads."""
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(NonCanonical):
            canonical_json({"x": bad})


def test_unserializable_types_are_rejected_loudly() -> None:
    with pytest.raises(NonCanonical, match="not JSON-serializable"):
        canonical_json({"x": {1, 2}})
    with pytest.raises(NonCanonical, match="keys must be strings"):
        canonical_json({1: "x"})


def test_non_ascii_stays_literal_so_tapes_are_greppable() -> None:
    assert canonical_json({"t": "日本語"}) == '{"t":"日本語"}'


def test_encoding_omits_empty_values() -> None:
    """One representation per value, or byte-identity fails."""
    encoded = encode_message(Message(role=Role.USER, text="hi"))
    assert encoded == {"role": "user", "text": "hi"}
    assert "tool_calls" not in encoded and "opaque" not in encoded


def test_message_round_trips() -> None:
    original = Message(
        role=Role.ASSISTANT,
        text="thinking",
        tool_calls=(ToolCall(id="c1", name="f", arguments={"a": 1}),),
    )
    assert decode_message(json.loads(canonical_json(encode_message(original)))) == original


# ------------------------------------------------------------- ADR-0014
def test_results_are_ordered_by_their_calls_not_by_arrival() -> None:
    calls = (
        ToolCall(id="c1", name="slow", arguments={}),
        ToolCall(id="c2", name="fast", arguments={}),
    )
    # `fast` finished first. The tape must not care.
    arrived = (ToolResult(call_id="c2", content="B"), ToolResult(call_id="c1", content="A"))
    assert [r.call_id for r in order_results(arrived, calls)] == ["c1", "c2"]


def test_a_result_for_an_unknown_call_is_a_corrupt_tape() -> None:
    """Silently dropping it would produce a hash for a run that never happened."""
    calls = (ToolCall(id="c1", name="f", arguments={}),)
    with pytest.raises(ValueError, match="unknown call ids"):
        order_results((ToolResult(call_id="ghost", content="?"),), calls)


def test_scheduling_does_not_change_the_encoded_history() -> None:
    """The property that makes concurrent tool execution safe to add later."""
    calls = (
        ToolCall(id="c1", name="a", arguments={}),
        ToolCall(id="c2", name="b", arguments={}),
    )
    assistant = Message(role=Role.ASSISTANT, tool_calls=calls)
    r1 = ToolResult(call_id="c1", content="A")
    r2 = ToolResult(call_id="c2", content="B")

    one = [assistant, Message(role=Role.TOOL_RESULTS, tool_results=(r1, r2))]
    other = [assistant, Message(role=Role.TOOL_RESULTS, tool_results=(r2, r1))]
    assert canonical_json(encode_history(one)) == canonical_json(encode_history(other))


def test_usage_is_omitted_when_empty() -> None:
    from tapeloop.record.codec import encode_usage

    assert encode_usage(Usage()) == {}
    assert encode_usage(Usage(input_tokens=3)) == {"input_tokens": 3}
