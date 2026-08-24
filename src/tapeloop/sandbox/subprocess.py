"""The M1 executor: a plain subprocess. No isolation worth the name.

Named honestly on purpose. ``isolation`` returns "subprocess (no isolation)" and
that string is written to the tape, so a run recorded today cannot later be
mistaken for one that was sandboxed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tapeloop.sandbox.base import ExecResult


class SubprocessExecutor:
    """Runs commands directly on the host. Accidents only — not adversaries."""

    @property
    def isolation(self) -> str:
        return "subprocess (no isolation)"

    def run(self, command: str, *, cwd: Path, timeout: float = 60.0) -> ExecResult:
        try:
            # The suppression below is deliberate and permanent for this backend.
            # shell=True on model-authored input is the whole hazard, which is why
            # `isolation` names it and why DockerExecutor exists. This remains the
            # DEFAULT: M5 added an alternative, it did not replace this (ADR-0007).
            proc = subprocess.run(  # noqa: S602
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            return ExecResult(
                exit_code=124,
                stdout=e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or ""),
                stderr=e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or ""),
                timed_out=True,
            )
        return ExecResult(exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
