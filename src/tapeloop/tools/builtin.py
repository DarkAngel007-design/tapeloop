"""The builtin tool pack — the same three tools M0 hand-wrote, now declared.

Compare with ``m0/loop.py``: the JSON Schema that took roughly sixty lines there is
gone entirely. The signature and the docstring are the source of truth, and each
tool now says what it does to the world.
"""

from __future__ import annotations

from pathlib import Path

from tapeloop.sandbox.base import Executor
from tapeloop.sandbox.subprocess import SubprocessExecutor
from tapeloop.tools.effects import Effect
from tapeloop.tools.registry import Registry


def build(workspace: Path, *, executor: Executor | None = None) -> Registry:
    """Create a registry of filesystem and shell tools bound to one workspace."""
    root = workspace.resolve()
    runner: Executor = executor or SubprocessExecutor()
    registry = Registry()

    def safe(rel: str) -> Path:
        """Confine every path to the workspace. Stands in for isolation until M5."""
        target = (root / rel).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"path escapes the workspace: {rel}")
        return target

    @registry.tool(effect=Effect.READ)
    def read_file(path: str) -> str:
        """Read a UTF-8 text file.

        Args:
            path: Path relative to the workspace root.
        """
        return safe(path).read_text(encoding="utf-8")

    @registry.tool(effect=Effect.WRITE)
    def write_file(path: str, content: str) -> str:
        """Write or overwrite a UTF-8 text file, creating parent directories.

        Args:
            path: Path relative to the workspace root.
            content: The full new contents of the file.
        """
        target = safe(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"wrote {len(content)} bytes to {path}"

    @registry.tool(effect=Effect.READ)
    def list_files(pattern: str = "*") -> str:
        """List files in the workspace matching a glob pattern.

        Args:
            pattern: A glob such as '*.py' or '**/*.md'. Defaults to everything.
        """
        found = sorted(p.relative_to(root).as_posix() for p in root.glob(pattern) if p.is_file())
        return "\n".join(found) if found else "(no matches)"

    @registry.tool(effect=Effect.WRITE)
    def run_command(command: str) -> str:
        """Run a shell command in the workspace and return its combined output.

        Args:
            command: The shell command to run.
        """
        return runner.run(command, cwd=root).as_tool_output()

    return registry
