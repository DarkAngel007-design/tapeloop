# pyright: basic
#
# Responses come off the wire as untyped JSON. Re-declaring their shape
# here would be asserting the schema against itself rather than against the server.
"""M8 ship criterion: the server speaks MCP to something that is not our client.

The weak version of this test connects our client to our server and proves they
agree with each other — which they would even if both were wrong. So the server is
driven here by **raw JSON-RPC over a real subprocess pipe**, with no tapeloop code on
the sending side. That is a conformance check rather than a round-trip.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from helpers import workspace_of

from tapeloop.mcp.client import StdioClient, import_tools
from tapeloop.mcp.protocol import PROTOCOL_VERSION, ProtocolError, parse_message
from tapeloop.mcp.server import McpServer
from tapeloop.tools import builtin
from tapeloop.tools.effects import Effect
from tapeloop.tools.registry import Registry


class RawPeer:
    """A JSON-RPC peer that knows nothing about tapeloop. Hand-rolled on purpose."""

    def __init__(self, cwd: Path) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "tapeloop.mcp.server"],
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._id = 0

    def send(self, method: str, params: dict[str, object] | None = None) -> dict[str, Any]:
        assert self.proc.stdin and self.proc.stdout
        self._id += 1
        self.proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})
            + "\n"
        )
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        assert line, f"server closed the pipe during {method}"
        return json.loads(line)

    def notify(self, method: str) -> None:
        assert self.proc.stdin
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.proc.stdin.flush()

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        self.proc.terminate()
        self.proc.wait(timeout=5)


@pytest.fixture
def peer(tmp_path: Path):
    ws = workspace_of(tmp_path)
    (ws / "hello.txt").write_text("world", encoding="utf-8")
    p = RawPeer(ws)
    yield p, ws
    p.close()


# ============================================================ SHIP CRITERION
def test_ship_criterion_the_server_speaks_mcp_to_a_foreign_peer(peer: tuple[RawPeer, Path]) -> None:
    raw, _ws = peer

    handshake = raw.send(
        "initialize",
        {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": "raw"}},
    )
    assert handshake["jsonrpc"] == "2.0"
    assert handshake["id"] == 1
    result = handshake["result"]
    assert isinstance(result, dict)
    assert result["protocolVersion"] == PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == "tapeloop"
    assert "tools" in result["capabilities"]

    raw.notify("notifications/initialized")

    listing = raw.send("tools/list")["result"]
    assert isinstance(listing, dict)
    names = {t["name"] for t in listing["tools"]}
    assert {"read_file", "write_file", "list_files", "run_command"} <= names
    for tool in listing["tools"]:
        assert tool["inputSchema"]["type"] == "object"
        assert tool["inputSchema"]["additionalProperties"] is False

    call = raw.send("tools/call", {"name": "read_file", "arguments": {"path": "hello.txt"}})[
        "result"
    ]
    assert isinstance(call, dict)
    assert call["isError"] is False
    assert call["content"][0]["text"] == "world"


def test_a_notification_is_never_answered(peer: tuple[RawPeer, Path]) -> None:
    """Replying to a notification is a protocol violation and desynchronises the pipe."""
    raw, _ = peer
    raw.send("initialize", {"protocolVersion": PROTOCOL_VERSION})
    raw.notify("notifications/initialized")
    # If the notification had been answered, this reply would carry the wrong id.
    assert raw.send("tools/list")["id"] == 2


def test_a_failing_tool_is_a_result_not_a_transport_error(peer: tuple[RawPeer, Path]) -> None:
    """MCP signals tool failure with isError — the same errors-are-data rule as the loop."""
    raw, _ = peer
    raw.send("initialize", {"protocolVersion": PROTOCOL_VERSION})
    reply = raw.send("tools/call", {"name": "read_file", "arguments": {"path": "nope.txt"}})
    assert "error" not in reply, "a missing file is not a JSON-RPC error"
    assert reply["result"]["isError"] is True
    assert "FileNotFoundError" in reply["result"]["content"][0]["text"]


def test_unknown_methods_and_tools_are_rejected(peer: tuple[RawPeer, Path]) -> None:
    raw, _ = peer
    raw.send("initialize", {"protocolVersion": PROTOCOL_VERSION})
    assert raw.send("resources/list")["error"]["code"] == -32601
    assert "unknown tool" in raw.send("tools/call", {"name": "nope"})["error"]["message"]


# ==================================================================== client
def test_the_client_imports_a_server_as_ordinary_tools(tmp_path: Path) -> None:
    """Nothing downstream should be able to tell a remote tool from a local one."""
    ws = workspace_of(tmp_path)
    (ws / "note.txt").write_text("remote content", encoding="utf-8")

    registry = Registry()
    with StdioClient(command=[sys.executable, "-m", "tapeloop.mcp.server"]) as client:
        # The server runs in the test's cwd; point it at the workspace instead.
        import os

        os.chdir(ws)
        added = import_tools(client, registry, prefix="mcp_")
        assert "mcp_read_file" in added
        assert len(registry) == len(added)
        spec = registry.get("mcp_read_file")
        assert spec is not None
        # ADR-0005: MCP carries no effect class, so everything arrives conservative.
        assert spec.effect is Effect.WRITE
        assert spec.parameters["type"] == "object"


# ================================================================== protocol
def test_malformed_messages_are_rejected_not_guessed_at() -> None:
    for bad in ("not json", '{"jsonrpc":"1.0","method":"x"}', '{"jsonrpc":"2.0"}', '"a string"'):
        with pytest.raises(ProtocolError):
            parse_message(bad)


def test_the_effect_class_is_carried_in_the_description() -> None:
    """MCP cannot express it structurally, so it goes in text rather than being lost."""
    server = McpServer(registry=builtin.build(Path.cwd()))
    described = {t["name"]: t["description"] for t in server.describe_tools()}
    assert described["run_command"].startswith("[effect: write]")
    assert described["read_file"].startswith("[effect: read]")
