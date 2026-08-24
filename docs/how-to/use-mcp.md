# Use tools over MCP

tapeloop speaks [MCP](https://modelcontextprotocol.io) on both ends: it can consume
another server's tools, and expose its own to another host.

## Consume a server

A remote tool lands in a `Registry` beside local ones and is dispatched, permission-
gated and recorded identically. Nothing downstream can tell the difference:

```py
from tapeloop.mcp.client import StdioClient, import_tools
from tapeloop.tools import builtin

registry = builtin.build(Path("workspace"))
with StdioClient(command=["python", "-m", "some_mcp_server"]) as client:
    added = import_tools(client, registry, prefix="mcp_")
    print(added)   # ['mcp_search', 'mcp_fetch', ...]
```

!!! warning "Effect classes do not cross the wire"
    MCP carries no notion of them, so **every imported tool is registered as `write`** —
    the conservative default. A remote `read_file` will ask for permission it does not
    need, which is the right way round: the alternative is a remote tool that mutates
    being treated as safe.

## Expose your tools

```bash
python -m tapeloop.mcp.server
```

It serves whatever `builtin.build(cwd)` produces, over stdio JSON-RPC. Point any MCP
host at that command.

Since MCP cannot express effect classes structurally, they are carried in the
description text instead — a host that does not know `run_command` writes would treat
it like one that does not:

```python
from pathlib import Path

from tapeloop.mcp.server import McpServer
from tapeloop.tools import builtin

server = McpServer(registry=builtin.build(Path(".")))
described = {t["name"]: t["description"] for t in server.describe_tools()}
assert described["run_command"].startswith("[effect: write]")
assert described["read_file"].startswith("[effect: read]")
```

## What is implemented

`initialize`, `tools/list`, `tools/call`. Not implemented: resources, prompts,
sampling, notifications beyond `initialized`.

The protocol is spoken directly rather than through an SDK — the slice needed is small
enough that implementing it keeps the default install at two packages and puts the wire
format in one readable file.
