"""Serving tapeloop's tools over MCP, so another host can use them.

A registry is already a set of named, JSON-Schema-described callables, which is what
MCP wants — so this is mostly translation. Run it with:

    python -m tapeloop.mcp.server

Effect classes do not cross the wire: MCP has no concept of them. A host consuming
these tools cannot know that `run_command` writes and `read_file` does not, so the
description carries the class in text. That is a real limitation of the protocol and
is stated rather than papered over.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO, cast

from tapeloop.mcp.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION,
    ProtocolError,
    error,
    parse_message,
    result,
)
from tapeloop.tools.registry import Registry

SERVER_NAME = "tapeloop"


def server_version() -> str:
    """Single-sourced. A handshake that reports the wrong version is a compatibility
    negotiation conducted on false information."""
    from tapeloop import __version__

    return __version__


@dataclass(slots=True)
class McpServer:
    """Exposes a Registry over MCP. Transport-agnostic; `serve_stdio` supplies one."""

    registry: Registry

    def describe_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                # The effect class is prepended because MCP cannot carry it
                # structurally, and a host that does not know a tool writes will
                # treat it like one that does not.
                "description": f"[effect: {spec.effect.value}] {spec.description}",
                "inputSchema": spec.parameters,
            }
            for spec in self.registry.specs()
        ]

    def handle(self, line: str) -> str | None:
        """Answer one message. Returns None for notifications, which take no reply."""
        try:
            request = parse_message(line)
        except ProtocolError as e:
            return error(None, INVALID_PARAMS, str(e))

        if request.method == "initialize":
            return result(
                request.id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": server_version()},
                },
            )
        if request.method in ("notifications/initialized", "initialized"):
            return None
        if request.method == "tools/list":
            return result(request.id, {"tools": self.describe_tools()})
        if request.method == "tools/call":
            return self._call(request.id, request.params)
        if request.is_notification:
            return None
        return error(request.id, METHOD_NOT_FOUND, f"unknown method: {request.method}")

    def _call(self, request_id: int | str | None, params: dict[str, Any]) -> str:
        name = params.get("name")
        if not isinstance(name, str):
            return error(request_id, INVALID_PARAMS, "missing tool name")
        supplied = params.get("arguments")
        if supplied is not None and not isinstance(supplied, dict):
            return error(request_id, INVALID_PARAMS, "arguments must be an object")
        arguments: dict[str, Any] = dict(cast(dict[str, Any], supplied)) if supplied else {}
        if name not in self.registry:
            return error(request_id, INVALID_PARAMS, f"unknown tool: {name}")
        try:
            output = self.registry.dispatch(name, arguments)
        except Exception as e:
            return error(request_id, INTERNAL_ERROR, f"{type(e).__name__}: {e}")
        # MCP signals tool failure with isError, not a JSON-RPC error: a failed tool
        # is a result the model should see, which is the same rule the loop follows.
        return result(
            request_id,
            {"content": [{"type": "text", "text": output}], "isError": output.startswith("ERROR:")},
        )


def serve_stdio(
    server: McpServer, *, stdin: TextIO | None = None, stdout: TextIO | None = None
) -> None:
    source: Iterator[str] = iter(stdin or sys.stdin)
    sink = stdout or sys.stdout
    for line in source:
        if not line.strip():
            continue
        reply = server.handle(line)
        if reply is not None:
            sink.write(reply + "\n")
            sink.flush()


def main() -> int:
    from tapeloop.tools import builtin

    serve_stdio(McpServer(registry=builtin.build(Path.cwd())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
