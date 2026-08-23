"""Content-addressed step keys (ADR-0004).

The key answers one question: would this call produce the same thing it produced
last time? So it hashes everything that could change the answer and nothing that
could not.

The prefix property falls out of this: change your system prompt and every step
from that point on misses, while every step before it hits. That is what makes
fork cheap, and it is the same property that governs server-side prompt caching,
so the two reinforce each other rather than fight.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from tapeloop.events import Message
from tapeloop.record.canonical import digest
from tapeloop.record.codec import encode_history
from tapeloop.tools.registry import ToolSpec


def step_key(
    *,
    provider: str,
    model: str,
    params: dict[str, Any],
    tools: Sequence[ToolSpec],
    messages: Sequence[Message],
) -> str:
    """The content address of the step that would follow ``messages``.

    Tools are sorted by name: a registry is a set, and the order two runs happen to
    build it in is not part of the request.
    """
    return digest(
        {
            "provider": provider,
            "model": model,
            "params": params,
            "tools": [
                {"name": t.name, "description": t.description, "parameters": t.parameters}
                for t in sorted(tools, key=lambda t: t.name)
            ],
            "events": encode_history(list(messages)),
        }
    )
