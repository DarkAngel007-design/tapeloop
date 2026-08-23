"""M6 — the eval harness. Proven end to end against fakes, so it costs nothing here.

The real baseline needs real credits and is the author's to run. What these tests
establish is that the machinery is sound: seeds are independent, spread is computed
and reported, the judge is pinned and its agreement measured, and judged results are
never blended into the deterministic headline.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from helpers import ScriptedClient

from tapeloop.core.loop import Agent
from tapeloop.eval.graders import LlmJudge
from tapeloop.eval.report import headline, render_markdown, summarize
from tapeloop.eval.runner import run_suite
from tapeloop.eval.suite import build_suite
from tapeloop.eval.task import Suite, Task
from tapeloop.events import Message, ModelResponse, Role, StopReason
from tapeloop.record.jsonl import JsonlStore
from tapeloop.tools import builtin


class FakeJudgeClient:
    """Returns a scripted verdict sequence, so agreement can be exercised exactly."""

    def __init__(self, verdicts: list[str]) -> None:
        self._verdicts = list(verdicts)
        self.calls = 0
        self.models_seen: list[str] = []

    @property
    def provider_id(self) -> str:
        return "fake-judge"

    def complete(self, *, model: str, messages: Sequence[Message], **_kw: object) -> ModelResponse:
        self.calls += 1
        self.models_seen.append(model)
        verdict = self._verdicts[(self.calls - 1) % len(self._verdicts)]
        return ModelResponse(
            message=Message(role=Role.ASSISTANT, text=verdict), stop_reason=StopReason.END_TURN
        )

    def stream(self, **_kw: object) -> object:  # pragma: no cover
        raise NotImplementedError

    def count_tokens(self, **_kw: object) -> int:
        return 0


def _seed_file(name: str, body: str) -> Callable[[Path], None]:
    def setup(workspace: Path) -> None:
        (workspace / name).write_text(body, encoding="utf-8")

    return setup


def _answers(text: str) -> list[ModelResponse]:
    return [
        ModelResponse(
            message=Message(role=Role.ASSISTANT, text=text), stop_reason=StopReason.END_TURN
        )
    ]


def _factory(script_for: dict[str, list[ModelResponse]]):
    def make(workspace: Path, tape: Path) -> Agent:
        key = tape.stem.rsplit("-s", 1)[0]
        return Agent(
            client=ScriptedClient(list(script_for.get(key, _answers("nothing")))),  # pyright: ignore[reportArgumentType]
            registry=builtin.build(workspace),
            model="fake-1",
            store=JsonlStore(tape),
        )

    return make


# ================================================================== the suite
def test_the_suite_is_hand_written_and_covers_more_than_happy_paths() -> None:
    suite = build_suite()
    tags = {tag for task in suite.tasks for tag in task.tags}
    assert len(suite) >= 12
    assert {"refusal", "edit", "transform", "multi-step"} <= tags
    assert len({t.id for t in suite.tasks}) == len(suite), "task ids must be unique"


def test_refusal_tasks_grade_the_workspace_not_the_agents_account_of_itself() -> None:
    """An agent that reports success it did not achieve is the commonest failure mode."""
    suite = build_suite()
    refusal = next(t for t in suite.tasks if t.id == "refuse-injected-instruction")
    assert any(type(g).__name__ == "NoFileChanged" for g in refusal.graders)


def test_a_task_with_two_requirements_is_not_half_done(tmp_path: Path) -> None:
    from tapeloop.eval.graders import FileContains
    from tapeloop.eval.runner import run_task

    suite = Suite(name="t")
    suite.add(
        Task(
            id="both",
            prompt="write a and b",
            graders=[FileContains("a.txt", "A"), FileContains("b.txt", "B")],
            setup=_seed_file("a.txt", "A"),
        )
    )
    attempt = run_task(
        suite.tasks[0],
        factory=_factory({"both": _answers("done")}),
        root=tmp_path,
        seed=0,
    )
    assert not attempt.passed, "one grader failing must fail the task"
    assert [g.passed for g in attempt.grades] == [True, False]


# ================================================================== variance
def test_spread_is_reported_not_smoothed_away(tmp_path: Path) -> None:
    """A single run is not a result. The table must show disagreement between seeds."""
    from tapeloop.eval.graders import Contains

    suite = Suite(name="v")
    suite.add(Task(id="flaky", prompt="say yes", graders=[Contains()], expected="yes"))

    calls = {"n": 0}

    def factory(workspace: Path, tape: Path) -> Agent:
        calls["n"] += 1
        # Alternate pass/fail so the spread is non-zero and checkable.
        text = "yes" if calls["n"] % 2 else "no"
        return Agent(
            client=ScriptedClient(_answers(text)),  # pyright: ignore[reportArgumentType]
            registry=builtin.build(workspace),
            model="fake-1",
            store=JsonlStore(tape),
        )

    run = run_suite(suite, factory=factory, root=tmp_path, repeats=4, model="fake-1")
    result = summarize(run, suite)[0]
    assert result.attempts == 4
    assert result.passes == 2
    assert result.mean == 0.5
    assert result.stdev > 0, "four attempts with two outcomes must show spread"


def test_each_seed_gets_a_fresh_workspace(tmp_path: Path) -> None:
    """Otherwise seed 2 inherits seed 1's mess and the seeds are not independent."""
    from tapeloop.eval.graders import FileContains

    suite = Suite(name="w")
    suite.add(
        Task(
            id="isolated",
            prompt="check",
            graders=[FileContains("seed.txt", "start")],
            setup=_seed_file("seed.txt", "start"),
        )
    )
    run = run_suite(suite, factory=_factory({"isolated": _answers("ok")}), root=tmp_path, repeats=3)
    workspaces = sorted((tmp_path / "workspaces").iterdir())
    assert len(workspaces) == 3
    assert all(a.passed for a in run.attempts)


def test_a_crashed_run_fails_the_attempt_not_the_suite(tmp_path: Path) -> None:
    from tapeloop.eval.graders import Contains

    suite = Suite(name="c")
    suite.add(Task(id="boom", prompt="x", graders=[Contains()], expected="x"))

    def exploding(workspace: Path, tape: Path) -> Agent:
        return Agent(
            client=ScriptedClient([]),  # empty script -> raises mid-run
            registry=builtin.build(workspace),
            model="fake-1",
            store=JsonlStore(tape),
        )

    run = run_suite(suite, factory=exploding, root=tmp_path, repeats=2)
    assert len(run.attempts) == 2
    assert all(a.error and not a.passed for a in run.attempts)
    assert summarize(run, suite)[0].errors == 2


# ===================================================================== judge
def test_the_judge_model_is_pinned_and_recorded(tmp_path: Path) -> None:
    """ADR-0018: a table that cannot name its judge is not a baseline."""
    client = FakeJudgeClient(["PASS - looks right"])
    judge = LlmJudge(client=client, model="judge-2026-01-01", k=1)  # pyright: ignore[reportArgumentType]

    suite = Suite(name="j")
    suite.add(Task(id="judged", prompt="explain", graders=[judge], expected="must explain"))
    run = run_suite(
        suite,
        factory=_factory({"judged": _answers("here is why")}),
        root=tmp_path,
        repeats=1,
        judge=judge,
        model="fake-1",
    )
    assert run.judge_model == "judge-2026-01-01"
    assert client.models_seen == ["judge-2026-01-01"]
    assert "judge-2026-01-01" in render_markdown(run, suite)


def test_judge_disagreement_is_surfaced_not_averaged_into_silence(tmp_path: Path) -> None:
    client = FakeJudgeClient(["PASS - yes", "FAIL - no", "PASS - yes"])
    judge = LlmJudge(client=client, model="judge-1", k=3)  # pyright: ignore[reportArgumentType]

    suite = Suite(name="j")
    suite.add(Task(id="wobbly", prompt="explain", graders=[judge], expected="rubric"))
    run = run_suite(
        suite,
        factory=_factory({"wobbly": _answers("an answer")}),
        root=tmp_path,
        repeats=1,
        judge=judge,
    )
    result = summarize(run, suite)[0]
    assert result.judge_agreement is not None
    assert result.judge_agreement < 1.0, "2-1 is not agreement"
    assert not result.reliable, "a self-disagreeing judge makes the row unreliable"
    assert "wobbly" in headline([result])["unreliable_rows"]


def test_an_unparseable_judgment_is_a_fail_never_a_silent_pass(tmp_path: Path) -> None:
    client = FakeJudgeClient(["I'm not sure, it depends"])
    judge = LlmJudge(client=client, model="judge-1", k=1)  # pyright: ignore[reportArgumentType]
    grade = judge.grade(expected="rubric", actual="something")
    assert not grade.passed


# ==================================================================== report
def test_judged_and_deterministic_scores_are_never_blended(tmp_path: Path) -> None:
    """ADR-0018: a reader who distrusts LLM judging must be able to discount that half."""
    from tapeloop.eval.graders import Contains

    client = FakeJudgeClient(["FAIL - no"])
    judge = LlmJudge(client=client, model="judge-1", k=1)  # pyright: ignore[reportArgumentType]

    suite = Suite(name="mixed")
    suite.add(Task(id="det", prompt="say yes", graders=[Contains()], expected="yes"))
    suite.add(Task(id="jud", prompt="explain", graders=[judge], expected="rubric"))

    run = run_suite(
        suite,
        factory=_factory({"det": _answers("yes"), "jud": _answers("waffle")}),
        root=tmp_path,
        repeats=2,
        judge=judge,
    )
    head = headline(summarize(run, suite))
    assert head["deterministic"]["tasks"] == 1
    assert head["judged"]["tasks"] == 1
    assert head["deterministic"]["mean"] == 1.0
    assert head["judged"]["mean"] == 0.0
    assert "mean" not in head, "there must be no single blended number"


def test_the_report_states_seeds_and_model(tmp_path: Path) -> None:
    from tapeloop.eval.graders import Contains

    suite = Suite(name="r")
    suite.add(Task(id="t", prompt="say yes", graders=[Contains()], expected="yes"))
    run = run_suite(
        suite,
        factory=_factory({"t": _answers("yes")}),
        root=tmp_path,
        repeats=3,
        model="pinned-model-1",
        provider="fake",
    )
    report = render_markdown(run, suite)
    assert "seeds per task: 3" in report
    assert "pinned-model-1" in report
    assert "± " in report, "spread must appear in the table"


def test_no_task_is_passable_by_doing_nothing(tmp_path: Path) -> None:
    """A grader a do-nothing model can pass is a grader that tests nothing.

    This caught a real one: `fix-the-bug` originally asserted that calc.py still
    contained "def average", which the setup already guaranteed, so an agent that
    did absolutely nothing scored 1.0. It now runs the code instead of grepping it.

    The single exemption is the injection task, where declining IS the correct
    behaviour — so a do-nothing model legitimately passes. That is a known limit of
    that task, documented in docs/evals/methodology.md: it detects an agent that
    obeys the injection, not one that never read the file.
    """
    from tapeloop.eval.report import summarize

    suite = build_suite()
    run = run_suite(
        suite,
        factory=_factory({}),  # every task gets "nothing", and no tool is called
        root=tmp_path,
        repeats=1,
    )
    exempt = {"refuse-injected-instruction"}
    passing = {r.task_id for r in summarize(run, suite) if r.mean > 0}
    weak = sorted(passing - exempt)
    assert passing == exempt, f"passable without doing any work: {weak}"
