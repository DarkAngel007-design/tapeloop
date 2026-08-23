"""Container-backed execution.

Slots in behind the ``Executor`` Protocol that has been in place since M1, which is
the whole reason the sandbox could land late without a rewrite (ADR-0007). Every
tool call already routes through the seam; this adds a backend.

What it addresses that a subprocess does not: an adversary. The workspace is the
only writable mount, the network is off by default, no credentials are passed in,
and the container is removed when the command ends.

What it does not address: a container escape. For that the escalation continues to
gVisor or a microVM, and ``isolation`` says which one you actually got — a recorded
run must never be able to claim protection it did not have.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from tapeloop.sandbox.base import ExecResult

Runner = "subprocess"


class DockerUnavailable(RuntimeError):
    """Docker is not installed or not running. Say so rather than silently degrading."""


@dataclass(slots=True)
class DockerExecutor:
    """Runs each command in a throwaway container."""

    image: str = "python:3.12-slim"
    network: str = "none"
    memory: str = "512m"
    cpus: str = "1"
    extra_args: Sequence[str] = field(default_factory=tuple[str, ...])
    binary: str = "docker"

    @property
    def isolation(self) -> str:
        net = "no network" if self.network == "none" else f"network={self.network}"
        return f"docker ({self.image}, {net})"

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def command_for(self, command: str, *, cwd: Path) -> list[str]:
        """Build the docker invocation. Separated so it can be asserted without Docker."""
        return [
            self.binary,
            "run",
            "--rm",
            "--interactive=false",
            f"--network={self.network}",
            f"--memory={self.memory}",
            f"--cpus={self.cpus}",
            # No new privileges, and every capability dropped. A tool needing more
            # than this should be a tool, not a shell command.
            "--security-opt=no-new-privileges",
            "--cap-drop=ALL",
            # The workspace is the only writable path. Everything else is read-only.
            f"--volume={cwd.resolve()}:/work",
            "--workdir=/work",
            "--read-only",
            # /tmp still has to work, but not as a place to stash an executable.
            "--tmpfs=/tmp:rw,noexec,nosuid,size=64m",
            *self.extra_args,
            self.image,
            "sh",
            "-c",
            command,
        ]

    def run(self, command: str, *, cwd: Path, timeout: float = 60.0) -> ExecResult:
        if not self.available():
            raise DockerUnavailable(
                f"{self.binary!r} not found on PATH. Install Docker, or pass "
                "SubprocessExecutor explicitly and accept that it provides no isolation."
            )
        try:
            proc = subprocess.run(  # noqa: S603 - argv list, no shell on the host side
                self.command_for(command, cwd=cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            return ExecResult(
                exit_code=124,
                stdout=_text(e.stdout),
                stderr=_text(e.stderr),
                timed_out=True,
            )
        return ExecResult(exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value
