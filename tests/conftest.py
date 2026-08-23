"""Test isolation.

``load_dotenv()`` mutates the real process environment. Without this fixture every
test would pick up the developer's actual ``.env`` — including their real API key —
which is how secrets end up in CI logs and how a test passes for the wrong reason.

Each test runs in a scratch working directory with the relevant variables scrubbed,
so a test can only see configuration it set itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_VARS = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "TAPELOOP_MODEL",
    "TAPELOOP_WORKSPACE",
    "TAPELOOP_YOLO",
)


@pytest.fixture(autouse=True)
def _isolate_environment(  # pyright: ignore[reportUnusedFunction]
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in _VARS:
        monkeypatch.delenv(name, raising=False)
