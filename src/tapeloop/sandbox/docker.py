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

import os
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
    run_as_host_user: bool = True
    """Run as the uid that owns the workspace, rather than as root in the container.

    Not cosmetic. `--cap-drop=ALL` removes CAP_DAC_OVERRIDE, which is the capability
    that lets root ignore permission bits -- so on Linux, root in the container is not
    the owner of a bind-mounted workspace and cannot write to it at all. The container
    is perfectly isolated and completely useless.

    This was invisible on macOS for exactly one reason: Docker Desktop's volume driver
    rewrites ownership so everything appears owned by the container user. CI on Linux
    caught it through the positive-control test, which exists because isolation that
    breaks the feature is a broken feature rather than security.

    Running unprivileged is also the better posture, so the fix and the hardening are
    the same change.
    """

    @property
    def isolation(self) -> str:
        net = "no network" if self.network == "none" else f"network={self.network}"
        who = "unprivileged" if self.run_as_host_user else "root in container"
        return f"docker ({self.image}, {net}, {who})"

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def _user_args(self) -> list[str]:
        """The host uid/gid, where the platform has them. Windows has neither."""
        if not self.run_as_host_user or not hasattr(os, "getuid"):
            return []
        return ["--user", f"{os.getuid()}:{os.getgid()}"]

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
            # An arbitrary uid has no passwd entry and therefore no home. Tools that
            # write dotfiles fail confusingly without this.
            "--env=HOME=/tmp",
            *self._user_args(),
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
