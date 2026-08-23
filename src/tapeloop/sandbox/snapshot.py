"""Workspace snapshots — what separates `resume` from `replay`.

ADR-0006 draws the line: replay is a cached simulation and touches nothing, while
resume restores the world and re-executes for real. Resume needs a copy of the
workspace as it stood at a step, and that is all this is.

It also settles ADR-0016's open end. A fork whose prefix replayed a `write` is
`simulated` because the workspace disagrees with the history; restore the matching
snapshot first and the same fork becomes `faithful`. The tier changes, the
interface does not.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Snapshot:
    step: int
    path: Path

    def size_bytes(self) -> int:
        return sum(f.stat().st_size for f in self.path.rglob("*") if f.is_file())


class SnapshotStore:
    """Copies of a workspace, one per step, kept beside the tape.

    A plain recursive copy. Content-addressed storage or hardlink trees would be
    cheaper and are the obvious optimization, but neither changes the interface, so
    neither is worth doing before there is a measurement saying it hurts.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def _dir(self, step: int) -> Path:
        return self.root / f"step-{step:04}"

    def take(self, workspace: Path, *, step: int) -> Snapshot:
        target = self._dir(step)
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        # dirs_exist_ok=False on a freshly removed target: a silent merge into a
        # stale snapshot would produce a workspace that never existed.
        shutil.copytree(workspace, target, symlinks=True)
        return Snapshot(step=step, path=target)

    def restore(self, workspace: Path, *, step: int) -> Snapshot:
        source = self._dir(step)
        if not source.exists():
            raise FileNotFoundError(f"no snapshot for step {step} in {self.root}")
        if workspace.exists():
            shutil.rmtree(workspace)
        shutil.copytree(source, workspace, symlinks=True)
        return Snapshot(step=step, path=source)

    def steps(self) -> list[int]:
        if not self.root.exists():
            return []
        return sorted(
            int(p.name.removeprefix("step-"))
            for p in self.root.iterdir()
            if p.is_dir() and p.name.startswith("step-")
        )

    def latest_before(self, step: int) -> int | None:
        """The most recent snapshot at or before ``step``, if any."""
        candidates = [s for s in self.steps() if s <= step]
        return max(candidates) if candidates else None
