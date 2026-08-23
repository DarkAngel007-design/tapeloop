"""Seam 2 — Executor.

The sandbox itself is M5. This seam exists at M1 for one reason: every tool call
must already route through it, so M5 adds a *backend* rather than rewriting call
sites. That is the whole mitigation for landing isolation late (ADR-0007).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    def as_tool_output(self, *, limit: int = 4000) -> str:
        combined = (self.stdout + self.stderr).strip()
        if self.timed_out:
            return f"ERROR: timed out\n{combined[:limit]}"
        if not combined:
            return f"exit={self.exit_code} (no output)"
        return f"exit={self.exit_code}\n{combined[:limit]}"


@runtime_checkable
class Executor(Protocol):
    """Runs a command somewhere. How isolated 'somewhere' is depends on the backend."""

    @property
    def isolation(self) -> str:
        """Human-readable isolation level, e.g. 'subprocess (none)' or 'docker'.

        Surfaced in the UI and written to the tape, so a recorded run says what it
        was actually protected by rather than what the docs claim today.
        """
        ...

    def run(self, command: str, *, cwd: Path, timeout: float = 60.0) -> ExecResult: ...
