"""The tape: append-only JSONL, one canonical event per line.

Behind the ``TranscriptStore`` seam that M1 put in, so the loop does not change —
which was the whole reason for defining the seam before there was anything to put
in it.

Chosen over a database because a tape must survive the library that wrote it
(ADR-0003). If reading a run requires importing tapeloop, the tape is a lock-in
format and a debugging dead end at exactly the moment you need it most. ``head``
and ``jq`` are the fallback, and they should always work.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from tapeloop.record.base import Event
from tapeloop.record.canonical import canonical_json
from tapeloop.record.codec import FORMAT_VERSION, UnsupportedFormat


def _writer_version() -> str:
    """Single-sourced from the package. A second copy would let a tape claim a
    writer version that never wrote it."""
    from tapeloop import __version__

    return __version__


def header_line() -> str:
    """The first line of every tape. Fully deterministic — no time, no ids (ADR-0015)."""
    return canonical_json({"kind": "header", "v": FORMAT_VERSION, "tapeloop": _writer_version()})


class JsonlStore:
    """Writes a tape. Opened lazily so constructing one never creates a file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: io.TextIOWrapper | None = None
        self._seq = 0

    def _open(self) -> io.TextIOWrapper:
        if self._handle is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fresh = not self.path.exists() or self.path.stat().st_size == 0
            self._handle = self.path.open("a", encoding="utf-8", newline="\n")
            if fresh:
                self._handle.write(header_line() + "\n")
        return self._handle

    def append(self, event: Event) -> None:
        record: dict[str, Any] = {"kind": event.kind, "seq": self._seq, "step": event.step}
        # `key` is promoted to a top-level field so the cache can index a tape
        # without decoding every payload.
        payload = dict(event.payload)
        if "key" in payload:
            record["key"] = payload.pop("key")
        if payload:
            record["data"] = payload
        handle = self._open()
        handle.write(canonical_json(record) + "\n")
        handle.flush()  # a crash must not cost the steps already paid for
        self._seq += 1

    def events(self) -> Iterator[Event]:
        yield from read_events(self.path)

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


def read_records(path: Path) -> Iterator[dict[str, Any]]:
    """Yield every record after the header, validating the format version first."""
    import json

    with path.open(encoding="utf-8") as handle:
        first = handle.readline()
        if not first.strip():
            return
        head = json.loads(first)
        if head.get("kind") != "header":
            raise UnsupportedFormat(f"{path}: first line is not a header")
        version = head.get("v")
        if version != FORMAT_VERSION:
            # Never a best-effort parse: a partially-understood tape that appears
            # to work is worse than one that refuses to open (ADR-0010).
            raise UnsupportedFormat(
                f"{path}: format version {version!r}, this build reads {FORMAT_VERSION}"
            )
        for line in handle:
            if line.strip():
                yield json.loads(line)


def read_events(path: Path) -> Iterator[Event]:
    for record in read_records(path):
        payload = dict(record.get("data", {}))
        if "key" in record:
            payload["key"] = record["key"]
        yield Event(kind=record["kind"], step=record.get("step", 0), payload=payload)
