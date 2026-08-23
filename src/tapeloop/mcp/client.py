"""Consuming a third-party MCP server: its tools become ordinary tools here.

The point of the client is that nothing downstream knows the difference. A remote
tool lands in a `Registry` beside local ones, gets dispatched the same way, is gated
by the same permission rules, and appears on the tape the same way.

One thing does not survive the wire: **effect class**. MCP carries no notion of it,
so every imported tool is registered as `write` — the conservative default from
ADR-0005. A remote `read_file` will ask for permission it does not need, which is the
right way round: the alternative is a remote tool that mutates being treated as safe.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from tapeloop.mcp.protocol import JSONRPC, PROTOCOL_VERSION, ProtocolError
from tapeloop.tools.effects import Effect
from tapeloop.tools.registry import Registry, ToolSpec


@dataclass(frozen=True, slots=True)
class RemoteTool:
    name: str
    description: str
    schema: dict[str, Any]


@dataclass(slots=True)
class StdioClient:
    """Speaks MCP to a server subprocess over stdin/stdout."""

    command: Sequence[str]
    process: subprocess.Popen[str] | None = field(default=None, init=False)
    _next_id: int = field(default=1, init=False)

    def __enter__(self) -> StdioClient:
        self.process = subprocess.Popen(  # noqa: S603 - argv list, no shell
            list(self.command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self.initialize()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self.process is not None:
            if self.process.stdin:
                self.process.stdin.close()
            self.process.terminate()
            self.process.wait(timeout=5)
            self.process = None

    def _send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.process is None or self.process.stdin is None or self.process.stdout is None:
            raise ProtocolError("client is not connected")
        request_id = self._next_id
        self._next_id += 1
        message = {"jsonrpc": JSONRPC, "id": request_id, "method": method, "params": params or {}}
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

        line = self.process.stdout.readline()
        if not line:
            raise ProtocolError(f"server closed the connection during {method}")
        decoded: object = json.loads(line)
        if not isinstance(decoded, dict):
            raise ProtocolError("response must be a JSON object")
        reply = cast(dict[str, Any], decoded)
        if "error" in reply:
            raise ProtocolError(f"{method}: {reply['error']}")
        payload = reply.get("result")
        return cast(dict[str, Any], payload) if isinstance(payload, dict) else {}

    def _notify(self, method: str) -> None:
        if self.process is None or self.process.stdin is None:
            return
        self.process.stdin.write(json.dumps({"jsonrpc": JSONRPC, "method": method}) + "\n")
        self.process.stdin.flush()

    def initialize(self) -> dict[str, Any]:
        info = self._send(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "tapeloop", "version": "0.0.0"},
            },
        )
        self._notify("notifications/initialized")
        return info

    def list_tools(self) -> list[RemoteTool]:
        payload = self._send("tools/list")
        tools = payload.get("tools")
        out: list[RemoteTool] = []
        for entry in cast(list[dict[str, Any]], tools if isinstance(tools, list) else []):
            out.append(
                RemoteTool(
                    name=str(entry.get("name", "")),
                    description=str(entry.get("description", "")),
                    schema=cast(dict[str, Any], entry.get("inputSchema") or {}),
                )
            )
        return out

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        payload = self._send("tools/call", {"name": name, "arguments": arguments})
        blocks = payload.get("content")
        parts = [
            str(block.get("text", ""))
            for block in cast(list[dict[str, Any]], blocks if isinstance(blocks, list) else [])
            if block.get("type") == "text"
        ]
        text = "\n".join(parts)
        return text if not payload.get("isError") else (text or "ERROR: remote tool failed")


def import_tools(client: StdioClient, registry: Registry, *, prefix: str = "") -> list[str]:
    """Register a server's tools into a local Registry. Returns the names added."""
    added: list[str] = []
    for remote in client.list_tools():
        name = f"{prefix}{remote.name}"

        def invoke(_name: str = remote.name, **kwargs: Any) -> str:
            return client.call_tool(_name, kwargs)

        registry.register(
            ToolSpec(
                name=name,
                description=remote.description,
                parameters=remote.schema or {"type": "object", "properties": {}, "required": []},
                # MCP carries no effect class. Conservative default (ADR-0005): a
                # remote tool that mutates must never be mistaken for one that does not.
                effect=Effect.WRITE,
                fn=invoke,
            )
        )
        added.append(name)
    return added
