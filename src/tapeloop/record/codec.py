"""Encoding canonical events to and from the tape's JSON shape.

Written out by hand rather than derived from the dataclasses. The format is a
compatibility promise (ADR-0010), so it must not shift silently because someone
added a field or reordered a class. If the wire shape changes, this file changes,
and that shows up in review.

The omission rule matters more than it looks: an empty collection and a null text
are *omitted*, never written as ``[]`` or ``null``. Two spellings of the same value
would break byte-identity.
"""

from __future__ import annotations

from typing import Any

from tapeloop.events import (
    Message,
    ModelResponse,
    Opaque,
    Role,
    StopReason,
    ToolCall,
    ToolResult,
    Usage,
)

FORMAT_VERSION = 1


class UnsupportedFormat(Exception):
    """A tape written by a version we do not understand.

    Never best-effort parsed. A partially-understood tape that appears to work is
    worse than one that refuses to open.
    """


def encode_call(call: ToolCall) -> dict[str, Any]:
    return {"id": call.id, "name": call.name, "arguments": call.arguments}


def decode_call(raw: dict[str, Any]) -> ToolCall:
    return ToolCall(id=raw["id"], name=raw["name"], arguments=raw.get("arguments", {}))


def encode_result(result: ToolResult) -> dict[str, Any]:
    out: dict[str, Any] = {"call_id": result.call_id, "content": result.content}
    if result.is_error:
        out["is_error"] = True
    return out


def decode_result(raw: dict[str, Any]) -> ToolResult:
    return ToolResult(
        call_id=raw["call_id"], content=raw["content"], is_error=raw.get("is_error", False)
    )


def encode_opaque(opaque: Opaque) -> dict[str, Any]:
    return {"provider": opaque.provider, "kind": opaque.kind, "data": opaque.data}


def decode_opaque(raw: dict[str, Any]) -> Opaque:
    return Opaque(provider=raw["provider"], kind=raw["kind"], data=raw.get("data"))


def order_results(
    results: tuple[ToolResult, ...], calls: tuple[ToolCall, ...]
) -> tuple[ToolResult, ...]:
    """Put results in the order of their calls (ADR-0014).

    Execution order is free; recorded order is not. Sorting against the model's own
    call sequence keeps the tape stable no matter how tools were scheduled.

    A result matching no call is a corrupt tape, not something to tolerate quietly —
    silently dropping it would produce a hash for a run that never happened.
    """
    if not calls:
        return results
    position = {call.id: index for index, call in enumerate(calls)}
    unknown = [r.call_id for r in results if r.call_id not in position]
    if unknown:
        raise ValueError(f"tool results reference unknown call ids: {unknown}")
    return tuple(sorted(results, key=lambda r: position[r.call_id]))


def encode_message(message: Message, *, calls: tuple[ToolCall, ...] = ()) -> dict[str, Any]:
    """Encode one message. ``calls`` supplies the ordering for a TOOL_RESULTS message."""
    out: dict[str, Any] = {"role": message.role.value}
    if message.text is not None:
        out["text"] = message.text
    if message.tool_calls:
        out["tool_calls"] = [encode_call(c) for c in message.tool_calls]
    if message.tool_results:
        out["tool_results"] = [encode_result(r) for r in order_results(message.tool_results, calls)]
    if message.opaque:
        out["opaque"] = [encode_opaque(o) for o in message.opaque]
    return out


def decode_message(raw: dict[str, Any]) -> Message:
    return Message(
        role=Role(raw["role"]),
        text=raw.get("text"),
        tool_calls=tuple(decode_call(c) for c in raw.get("tool_calls", [])),
        tool_results=tuple(decode_result(r) for r in raw.get("tool_results", [])),
        opaque=tuple(decode_opaque(o) for o in raw.get("opaque", [])),
    )


def encode_usage(usage: Usage) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if usage.input_tokens:
        out["input_tokens"] = usage.input_tokens
    if usage.output_tokens:
        out["output_tokens"] = usage.output_tokens
    if usage.cached_input_tokens:
        out["cached_input_tokens"] = usage.cached_input_tokens
    return out


def decode_usage(raw: dict[str, Any]) -> Usage:
    return Usage(
        input_tokens=raw.get("input_tokens", 0),
        output_tokens=raw.get("output_tokens", 0),
        cached_input_tokens=raw.get("cached_input_tokens", 0),
    )


def encode_response(response: ModelResponse) -> dict[str, Any]:
    out: dict[str, Any] = {
        "message": encode_message(response.message),
        "stop_reason": response.stop_reason.value,
    }
    usage = encode_usage(response.usage)
    if usage:
        out["usage"] = usage
    return out


def decode_response(raw: dict[str, Any]) -> ModelResponse:
    return ModelResponse(
        message=decode_message(raw["message"]),
        stop_reason=StopReason(raw["stop_reason"]),
        usage=decode_usage(raw.get("usage", {})),
    )


def encode_history(messages: list[Message]) -> list[dict[str, Any]]:
    """Encode a message list, threading each assistant's calls into the results after it.

    This is the only place that knows results are ordered against the preceding
    assistant message, so it is the only place that has to get ADR-0014 right.
    """
    encoded: list[dict[str, Any]] = []
    pending: tuple[ToolCall, ...] = ()
    for message in messages:
        encoded.append(encode_message(message, calls=pending))
        pending = message.tool_calls or ()
    return encoded
