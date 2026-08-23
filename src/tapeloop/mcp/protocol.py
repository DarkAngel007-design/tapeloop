"""The slice of MCP this project needs, spoken directly.

MCP is JSON-RPC 2.0 over a transport — stdio here. The official SDK is excellent and
also a dependency, and the parts used are small enough that speaking the protocol
directly keeps the install at two packages while making the wire format legible in
one file instead of hidden behind a client object.

Implemented: `initialize`, `tools/list`, `tools/call`. Not implemented: resources,
prompts, sampling, notifications beyond `initialized`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

PROTOCOL_VERSION = "2025-06-18"
JSONRPC = "2.0"


class ProtocolError(Exception):
    """The peer sent something that is not valid MCP."""


@dataclass(frozen=True, slots=True)
class Request:
    id: int | str | None
    method: str
    params: dict[str, Any]

    @property
    def is_notification(self) -> bool:
        """Notifications carry no id and must never be answered."""
        return self.id is None


def parse_message(line: str) -> Request:
    try:
        decoded: object = json.loads(line)
    except json.JSONDecodeError as e:
        raise ProtocolError(f"not JSON: {e}") from e
    if not isinstance(decoded, dict):
        raise ProtocolError("message must be a JSON object")

    raw = cast(dict[str, Any], decoded)
    if raw.get("jsonrpc") != JSONRPC:
        raise ProtocolError("missing or wrong jsonrpc version")
    method = raw.get("method")
    if not isinstance(method, str):
        raise ProtocolError("missing method")

    identifier = raw.get("id")
    if identifier is not None and not isinstance(identifier, int | str):
        raise ProtocolError("id must be a number, string, or absent")
    params = raw.get("params")
    return Request(
        id=identifier,
        method=method,
        params=cast(dict[str, Any], params) if isinstance(params, dict) else {},
    )


def result(request_id: int | str | None, payload: dict[str, Any]) -> str:
    return json.dumps({"jsonrpc": JSONRPC, "id": request_id, "result": payload})


def error(request_id: int | str | None, code: int, message: str) -> str:
    return json.dumps(
        {"jsonrpc": JSONRPC, "id": request_id, "error": {"code": code, "message": message}}
    )


METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
