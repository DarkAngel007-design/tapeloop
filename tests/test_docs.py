"""Every runnable example in docs/ actually runs.

Written before the documentation it checks, deliberately. The recurring failure in
this project has been prose that claims more than the code does — a security doc
describing protections that were off by default, an ADR describing a command that did
not exist, a README saying "no sandbox until M5" a milestone after M5. Examples are
the same hazard in a more embarrassing form, because a reader will paste them.

Convention:

    ```python      executed by this test — must run with no API key and no network
    ```py          shown, not executed: needs credentials, a daemon, or is a fragment
    ```bash        shown, not executed

So `python` is a promise and `py` is an illustration, and the fence itself says which.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"
BLOCK = re.compile(r"^```python\n(.*?)^```", re.MULTILINE | re.DOTALL)


def _pages() -> list[Path]:
    return sorted(p for p in DOCS.rglob("*.md"))


def _runnable_blocks(path: Path) -> list[tuple[int, str]]:
    text = path.read_text(encoding="utf-8")
    out: list[tuple[int, str]] = []
    for m in BLOCK.finditer(text):
        line = text[: m.start()].count("\n") + 1
        out.append((line, m.group(1)))
    return out


ALL = [(p, line, code) for p in _pages() for line, code in _runnable_blocks(p)]


@pytest.mark.skipif(not ALL, reason="no runnable examples yet")
@pytest.mark.parametrize(
    ("path", "line", "code"),
    ALL,
    ids=[f"{p.relative_to(DOCS)}:{line}" for p, line, _ in ALL],
)
def test_a_documented_example_runs(path: Path, line: int, code: str, tmp_path: Path) -> None:
    """Run it in a scratch directory, so an example that writes files cannot escape."""
    import os

    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        namespace: dict[str, object] = {"__name__": "__doc_example__"}
        exec(compile(code, f"{path.relative_to(DOCS)}:{line}", "exec"), namespace)
    finally:
        os.chdir(cwd)


def test_every_page_is_in_the_nav() -> None:
    """A page not in the nav is a page nobody finds. mkdocs --strict warns; this fails."""
    import re as _re

    config = (DOCS.parent / "mkdocs.yml").read_text(encoding="utf-8")
    listed = set(_re.findall(r"([\w./-]+\.md)", config))
    on_disk = {str(p.relative_to(DOCS)) for p in _pages()}
    # ADRs are indexed by their own README rather than the nav; listing 22 would bury it.
    on_disk = {p for p in on_disk if not p.startswith("adr/") or p.endswith("README.md")}
    missing = on_disk - listed
    assert not missing, f"pages absent from mkdocs.yml nav: {sorted(missing)}"


def test_no_internal_link_is_broken() -> None:
    """Relative links between docs pages must resolve on disk."""
    broken: list[str] = []
    for page in _pages():
        for target in re.findall(r"\]\((?!https?://|#)([^)]+)\)", page.read_text(encoding="utf-8")):
            clean = target.split("#")[0]
            if not clean:
                continue
            resolved = (page.parent / clean).resolve()
            if not resolved.exists():
                broken.append(f"{page.relative_to(DOCS)} -> {target}")
    assert not broken, "broken internal links:\n  " + "\n  ".join(broken)
