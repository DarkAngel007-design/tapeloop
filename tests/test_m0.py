# pyright: basic
#
# The fakes below are SimpleNamespace stand-ins for SDK response objects. Typing
# them strictly would mean re-declaring the SDK's own types, which tests nothing.
"""Tests for the M0 spike.

These run entirely against a fake client, so they cost nothing and prove the two
protocol details that M0 exists to demonstrate:

  1. the assistant message is appended verbatim, tool_calls intact
  2. every tool call gets its own ``role="tool"`` message carrying its tool_call_id
"""

from __future__ import annotations

import ast
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
M0 = ROOT / "m0" / "loop.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("m0_loop", M0)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------- ship criterion
def test_m0_stays_small() -> None:
    """M0's ship criterion: under 150 lines of code, comments and docstrings excluded.

    This is executable rather than aspirational on purpose. If M0 grows past this,
    it has started becoming M1 and belongs in src/.
    """
    src = M0.read_text().splitlines(keepends=True)
    tree = ast.parse("".join(src))
    docstring_lines: set[int] = set()
    for node in ast.walk(tree):
        kinds = (ast.Module, ast.FunctionDef, ast.ClassDef)
        if isinstance(node, kinds) and ast.get_docstring(node):
            first = node.body[0]
            docstring_lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))

    count = sum(
        1
        for i, line in enumerate(src, 1)
        if line.strip() and not line.strip().startswith("#") and i not in docstring_lines
    )
    assert count < 150, f"M0 is {count} code lines; the ship criterion is <150"


# --------------------------------------------------------------- fake transport
class _FakeCompletions:
    def __init__(self, scripted: list[Any]) -> None:
        self._scripted = scripted
        self.seen: list[list[Any]] = []

    def create(self, **kwargs: Any) -> Any:
        # Record the exact history the loop sent us; this is what we assert on.
        self.seen.append([dict(m) for m in kwargs["messages"]])
        return self._scripted.pop(0)


def _response(*, content: str | None, tool_calls: list[Any] | None, finish: str) -> Any:
    message = SimpleNamespace(
        content=content,
        tool_calls=tool_calls,
        model_dump=lambda exclude_none=False: {
            "role": "assistant",
            "content": content,
            **(
                {
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ]
                }
                if tool_calls
                else {}
            ),
        },
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish)],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )


def _call(id_: str, name: str, args: str) -> Any:
    return SimpleNamespace(id=id_, function=SimpleNamespace(name=name, arguments=args))


# --------------------------------------------------------------- protocol tests
@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("TAPELOOP_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("TAPELOOP_YOLO", "1")  # no interactive confirm in tests
    return tmp_path


def test_two_tool_task_completes(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The M0 ship criterion: completes a task using two different tools."""
    (workspace / "seed.txt").write_text("hello", encoding="utf-8")

    scripted = [
        _response(
            content=None,
            tool_calls=[
                _call("c1", "read_file", '{"path": "seed.txt"}'),
                _call("c2", "write_file", '{"path": "out.txt", "content": "HELLO"}'),
            ],
            finish="tool_calls",
        ),
        _response(content="Read seed.txt and wrote out.txt.", tool_calls=None, finish="stop"),
    ]
    fake = _FakeCompletions(scripted)
    mod = _load()
    monkeypatch.setattr(
        mod, "OpenAI", lambda *a, **k: SimpleNamespace(chat=SimpleNamespace(completions=fake))
    )
    monkeypatch.setattr(mod, "WORKSPACE", workspace)
    monkeypatch.setattr(sys, "argv", ["loop.py", "do the thing"])

    assert mod.main() == 0
    assert (workspace / "out.txt").read_text(encoding="utf-8") == "HELLO"

    # The history the loop sent on its SECOND call is the thing under test.
    history = fake.seen[1]
    assistant = history[2]
    assert assistant["role"] == "assistant"
    assert len(assistant["tool_calls"]) == 2, "assistant message must keep tool_calls verbatim"

    tool_msgs = [m for m in history if m["role"] == "tool"]
    assert len(tool_msgs) == 2, "one tool message per tool call, never merged"
    assert [m["tool_call_id"] for m in tool_msgs] == ["c1", "c2"], "ids must pair, in order"
    assert tool_msgs[0]["content"] == "hello"


def test_tool_errors_come_back_as_content(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing tool must return a readable error, not raise into the loop."""
    scripted = [
        _response(
            content=None,
            tool_calls=[_call("c1", "read_file", '{"path": "does-not-exist.txt"}')],
            finish="tool_calls",
        ),
        _response(content="That file is missing.", tool_calls=None, finish="stop"),
    ]
    fake = _FakeCompletions(scripted)
    mod = _load()
    monkeypatch.setattr(
        mod, "OpenAI", lambda *a, **k: SimpleNamespace(chat=SimpleNamespace(completions=fake))
    )
    monkeypatch.setattr(mod, "WORKSPACE", workspace)
    monkeypatch.setattr(sys, "argv", ["loop.py", "read a missing file"])

    assert mod.main() == 0
    tool_msg = next(m for m in fake.seen[1] if m["role"] == "tool")
    assert tool_msg["content"].startswith("ERROR: FileNotFoundError")


def test_path_traversal_is_refused(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M0 has no sandbox, so workspace confinement is the only guard. It must hold."""
    mod = _load()
    monkeypatch.setattr(mod, "WORKSPACE", workspace)
    out = mod.dispatch("write_file", {"path": "../escaped.txt", "content": "x"}, confirm=False)
    assert out.startswith("ERROR: ValueError")
    assert not (workspace.parent / "escaped.txt").exists()


def test_dotenv_is_actually_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: M0 shipped telling people to create .env, but never loaded it.

    The docs said 'copy .env.example to .env' while the code only read os.environ,
    so the file sat there doing nothing and the run died on a missing key.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("TAPELOOP_YOLO", "1")
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=from-dotenv-file\n", encoding="utf-8")

    fake = _FakeCompletions([_response(content="done", tool_calls=None, finish="stop")])
    mod = _load()
    monkeypatch.setattr(
        mod, "OpenAI", lambda *a, **k: SimpleNamespace(chat=SimpleNamespace(completions=fake))
    )
    monkeypatch.setattr(mod, "WORKSPACE", tmp_path)
    monkeypatch.setattr(sys, "argv", ["loop.py", "say done"])

    assert mod.main() == 0, "main() exited early -- .env was not loaded"

    # Compare into a bool first. Asserting on the value directly makes pytest print
    # it on failure, which is how a real key ends up in a CI log.
    came_from_tmp_env = os.environ.get("OPENAI_API_KEY") == "from-dotenv-file"
    assert came_from_tmp_env, "OPENAI_API_KEY did not come from the temporary .env"
