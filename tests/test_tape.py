"""M3 ship criterion: re-running an unchanged agent is a 100% cache hit, byte-identical."""

from __future__ import annotations

import ast
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from tapeloop.core.loop import Agent
from tapeloop.events import Message, ModelResponse, Role, StopReason, ToolCall, Usage
from tapeloop.providers.stream import StreamEvent
from tapeloop.record.cache import StepCache
from tapeloop.record.codec import UnsupportedFormat
from tapeloop.record.jsonl import JsonlStore, read_records
from tapeloop.record.keys import step_key
from tapeloop.tools import builtin
from tapeloop.tools.registry import Registry, ToolSpec


class ScriptedClient:
    """Replays a fixed script. Counts calls so cache hits are observable."""

    def __init__(self, script: list[ModelResponse]) -> None:
        self._script = list(script)
        self.calls = 0

    @property
    def provider_id(self) -> str:
        return "scripted"

    def complete(
        self,
        *,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        max_tokens: int = 4096,
    ) -> ModelResponse:
        self.calls += 1
        return self._script.pop(0)

    def stream(self, **_kw: object) -> Iterator[StreamEvent]:  # pragma: no cover
        raise NotImplementedError

    def count_tokens(self, **_kw: object) -> int:
        return 0


class ExplodingClient(ScriptedClient):
    """Fails if called at all. Proves a run was served entirely from the tape."""

    def complete(self, **_kw: object) -> ModelResponse:
        raise AssertionError("the provider was called; this should have been a cache hit")


def _script() -> list[ModelResponse]:
    return [
        ModelResponse(
            message=Message(
                role=Role.ASSISTANT,
                tool_calls=(
                    ToolCall(id="c1", name="read_file", arguments={"path": "seed.txt"}),
                    ToolCall(id="c2", name="list_files", arguments={"pattern": "*"}),
                ),
            ),
            stop_reason=StopReason.TOOL_USE,
            usage=Usage(input_tokens=10, output_tokens=5),
        ),
        ModelResponse(
            message=Message(role=Role.ASSISTANT, text="Done — one file."),
            stop_reason=StopReason.END_TURN,
            usage=Usage(input_tokens=20, output_tokens=6),
        ),
    ]


def _workspace(tmp_path: Path) -> Path:
    """The directory the agent can see. Tapes go elsewhere -- see the observer-effect test."""
    ws = tmp_path / "workspace"
    ws.mkdir(exist_ok=True)
    return ws


def _agent(tmp_path: Path, tape: Path, client: ScriptedClient, **kw: object) -> Agent:
    return Agent(
        client=client,  # pyright: ignore[reportArgumentType]
        registry=builtin.build(_workspace(tmp_path)),
        model="scripted-1",
        store=JsonlStore(tape),
        **kw,  # pyright: ignore[reportArgumentType]
    )


# ============================================================ SHIP CRITERION
def test_ship_criterion_replay_is_a_total_cache_hit_and_byte_identical(tmp_path: Path) -> None:
    (_workspace(tmp_path) / "seed.txt").write_text("hello", encoding="utf-8")
    tapes = tmp_path / "tapes"
    tapes.mkdir()
    first, second = tapes / "run1.jsonl", tapes / "run2.jsonl"

    live = ScriptedClient(_script())
    original = _agent(tmp_path, first, live).run("count the files")
    assert live.calls == 2

    cache = StepCache.from_tape(first)
    replayed = _agent(tmp_path, second, ExplodingClient([]), cache=cache).run("count the files")

    assert cache.stats.hit_rate == 1.0, f"{cache.stats.hits} hits / {cache.stats.total}"
    assert replayed.text == original.text
    assert replayed.steps == original.steps
    assert first.read_bytes() == second.read_bytes(), "tapes must be byte-identical"


def test_the_tape_is_readable_without_the_library(tmp_path: Path) -> None:
    """ADR-0003: if reading a run needs tapeloop, the tape is a debugging dead end."""
    import json

    tape = tmp_path / "tapes" / "run.jsonl"
    _agent(tmp_path, tape, ScriptedClient(_script())).run("go")
    lines = [json.loads(line) for line in tape.read_text(encoding="utf-8").splitlines()]

    assert lines[0] == {"kind": "header", "tapeloop": "0.0.0", "v": 1}
    assert [r["seq"] for r in lines[1:]] == list(range(len(lines) - 1)), "gapless, in write order"
    assert next(r["kind"] for r in lines[1:]) == "run_start"
    assert lines[-1]["kind"] == "run_end"


def test_no_timestamps_anywhere(tmp_path: Path) -> None:
    """ADR-0015. A single wall-clock value would make byte-identity meaningless."""
    tape = tmp_path / "tapes" / "run.jsonl"
    _agent(tmp_path, tape, ScriptedClient(_script())).run("go")
    text = tape.read_text(encoding="utf-8").lower()
    for banned in ("timestamp", "created_at", "elapsed", "duration", "2026-"):
        assert banned not in text, f"found {banned!r} in the tape"


def test_recording_into_the_workspace_changes_the_run(tmp_path: Path) -> None:
    """The observer effect, pinned deliberately rather than left as a surprise.

    A tape written inside the directory the agent can see becomes part of what the
    agent observes. `list_files` then returns something different on the second run,
    the tool result differs, the step key diverges, and replay misses -- with nothing
    obviously wrong to look at. Tapes belong outside the workspace.
    """
    ws = _workspace(tmp_path)
    (ws / "seed.txt").write_text("hello", encoding="utf-8")

    inside = ws / "run1.jsonl"  # deliberately wrong
    _agent(tmp_path, inside, ScriptedClient(_script())).run("go")

    cache = StepCache.from_tape(inside)
    _agent(tmp_path, ws / "run2.jsonl", ScriptedClient(_script()), cache=cache).run("go")

    assert cache.stats.hit_rate < 1.0, (
        "if this ever passes at 1.0 the observer effect is gone, and this test plus "
        "the warning in docs/reference/transcript-format.md can go with it"
    )


def test_an_unknown_format_version_refuses_to_open(tmp_path: Path) -> None:
    tape = tmp_path / "future.jsonl"
    tape.write_text('{"kind":"header","tapeloop":"9.9.9","v":99}\n', encoding="utf-8")
    with pytest.raises(UnsupportedFormat, match="99"):
        list(read_records(tape))


# ================================================================ step keys
def _key(messages: list[Message], **over: object) -> str:
    base: dict[str, object] = {
        "provider": "openai",
        "model": "m",
        "params": {"max_tokens": 100},
        "tools": (),
        "messages": messages,
    }
    base.update(over)
    return step_key(**base)  # pyright: ignore[reportArgumentType]


def test_the_prefix_property(tmp_path: Path) -> None:
    """The whole reason fork is cheap: a late change leaves early keys untouched."""
    history = [Message(role=Role.SYSTEM, text="be helpful"), Message(role=Role.USER, text="hi")]
    edited = [Message(role=Role.SYSTEM, text="be helpful"), Message(role=Role.USER, text="hello")]

    assert _key(history[:1]) == _key(edited[:1]), "the shared prefix must still hit"
    assert _key(history) != _key(edited), "and everything after the change must miss"


def test_provider_and_model_are_inside_the_key() -> None:
    """Cross-provider replay is a miss by definition — a different model is a different run."""
    history = [Message(role=Role.USER, text="hi")]
    assert _key(history) != _key(history, provider="anthropic")
    assert _key(history) != _key(history, model="other")


def test_registry_build_order_does_not_change_the_key() -> None:
    """A registry is a set. The order two runs happened to build it in is not a request."""

    def build(order: list[str]) -> Registry:
        reg = Registry()
        for name in order:

            def make(_n: str = name) -> None:
                @reg.tool(name=_n)
                def _f(x: str) -> str:
                    """Doc.

                    Args:
                        x: A thing.
                    """
                    return ""

            make()
        return reg

    history = [Message(role=Role.USER, text="hi")]
    a = _key(history, tools=build(["alpha", "beta"]).specs())
    b = _key(history, tools=build(["beta", "alpha"]).specs())
    assert a == b


# ======================================================== determinism lint
BANNED = {
    ("time", "time"),
    ("time", "monotonic"),
    ("datetime", "now"),
    ("datetime", "utcnow"),
    ("datetime", "today"),
    ("uuid", "uuid1"),
    ("uuid", "uuid4"),
    ("random", "random"),
    ("random", "uniform"),
    ("random", "choice"),
    ("random", "shuffle"),
    ("random", "randint"),
}


def test_determinism_lint() -> None:
    """Contract 1, enforced by CI rather than by discipline (CLAUDE.md).

    A wall-clock read or an unseeded random inside src/ breaks replay silently.
    `random.Random(seed)` is fine — it is an instance, not the global stream — and
    `time.sleep` is fine because it reads no clock.
    """
    root = Path(__file__).resolve().parents[1] / "src"
    offences: list[str] = []

    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
                continue
            if (func.value.id, func.attr) in BANNED:
                offences.append(
                    f"{path.relative_to(root)}:{node.lineno} {func.value.id}.{func.attr}()"
                )

    assert not offences, "non-deterministic calls in src/:\n  " + "\n  ".join(offences)
