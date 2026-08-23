"""Turning attempts into a table you could defend.

Two rules, both from ADR-0018. Spread is reported, never smoothed away. And judged
tasks are reported separately from deterministic ones, so a reader who distrusts
LLM judging can discount that half without recomputing anything.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from tapeloop.eval.runner import Attempt, SuiteRun
from tapeloop.eval.task import Suite


@dataclass(frozen=True, slots=True)
class TaskResult:
    task_id: str
    judged: bool
    attempts: int
    passes: int
    mean: float
    stdev: float
    mean_steps: float
    errors: int
    judge_agreement: float | None

    @property
    def reliable(self) -> bool:
        """A judge that disagrees with itself makes the row unreliable, not just noisy."""
        return self.judge_agreement is None or self.judge_agreement >= 0.99


def summarize(run: SuiteRun, suite: Suite) -> list[TaskResult]:
    judged = {t.id: t.is_judged for t in suite.tasks}
    by_task: dict[str, list[Attempt]] = {}
    for attempt in run.attempts:
        by_task.setdefault(attempt.task_id, []).append(attempt)

    results: list[TaskResult] = []
    for task_id, attempts in by_task.items():
        scores = [a.score for a in attempts]
        agreements = [a.judge_agreement for a in attempts if a.judge_agreement is not None]
        results.append(
            TaskResult(
                task_id=task_id,
                judged=judged.get(task_id, False),
                attempts=len(attempts),
                passes=sum(1 for a in attempts if a.passed),
                mean=statistics.fmean(scores),
                stdev=statistics.stdev(scores) if len(scores) > 1 else 0.0,
                mean_steps=statistics.fmean([a.steps for a in attempts]),
                errors=sum(1 for a in attempts if a.error),
                judge_agreement=statistics.fmean(agreements) if agreements else None,
            )
        )
    return sorted(results, key=lambda r: r.task_id)


def headline(results: list[TaskResult]) -> dict[str, Any]:
    """Deterministic and judged reported apart. Never one blended number."""

    def block(rows: list[TaskResult]) -> dict[str, Any]:
        if not rows:
            return {"tasks": 0}
        means = [r.mean for r in rows]
        return {
            "tasks": len(rows),
            "mean": round(statistics.fmean(means), 4),
            "spread": round(statistics.stdev(means), 4) if len(means) > 1 else 0.0,
        }

    deterministic = [r for r in results if not r.judged]
    judged = [r for r in results if r.judged]
    return {
        "deterministic": block(deterministic),
        "judged": block(judged),
        "unreliable_rows": [r.task_id for r in results if not r.reliable],
    }


def render_markdown(run: SuiteRun, suite: Suite) -> str:
    results = summarize(run, suite)
    head = headline(results)
    lines = [
        f"# Results — {run.suite}",
        "",
        f"- model: `{run.model}`  provider: `{run.provider}`",
    ]
    if run.judge_model:
        lines.append(f"- judge: `{run.judge_model}` (prompt v{run.judge_prompt_version})")
    else:
        lines.append("- judge: none — every task graded deterministically")
    seeds = max((r.attempts for r in results), default=0)
    lines += [
        f"- seeds per task: {seeds}",
        "",
        "## Headline",
        "",
        "Deterministic and judged are reported separately on purpose (ADR-0018).",
        "",
        "| Kind | Tasks | Mean | Spread |",
        "| --- | ---: | ---: | ---: |",
    ]
    for kind in ("deterministic", "judged"):
        block = head[kind]
        if block["tasks"]:
            lines.append(
                f"| {kind} | {block['tasks']} | {block['mean']:.3f} | ± {block['spread']:.3f} |"
            )
    if head["unreliable_rows"]:
        lines += [
            "",
            f"**Unreliable rows** (judge disagreed with itself): "
            f"{', '.join(head['unreliable_rows'])}",
        ]
    lines += [
        "",
        "## Per task",
        "",
        "| Task | Judged | Pass | Mean | ± | Steps | Errors | Judge agr. |",
        "| --- | :-: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in results:
        agr = f"{r.judge_agreement:.2f}" if r.judge_agreement is not None else "—"
        lines.append(
            f"| `{r.task_id}` | {'yes' if r.judged else 'no'} | {r.passes}/{r.attempts} | "
            f"{r.mean:.2f} | ± {r.stdev:.2f} | {r.mean_steps:.1f} | {r.errors} | {agr} |"
        )
    return "\n".join(lines) + "\n"
