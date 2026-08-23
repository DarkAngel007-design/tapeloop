"""Seam 4 — Grader.

Exists at M1 so that LLM-as-judge, when it arrives at M6, is just another Grader
rather than a special case carved into the eval runner.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class Grade:
    passed: bool
    score: float = 0.0
    reason: str = ""


@runtime_checkable
class Grader(Protocol):
    def grade(self, *, expected: str, actual: str) -> Grade: ...


class ExactMatch:
    def grade(self, *, expected: str, actual: str) -> Grade:
        ok = expected.strip() == actual.strip()
        return Grade(passed=ok, score=1.0 if ok else 0.0, reason="" if ok else "did not match")


class Predicate:
    """Wraps any function into a Grader. The escape hatch for one-off checks."""

    def __init__(self, fn: Callable[[str, str], bool], *, name: str = "predicate") -> None:
        self._fn = fn
        self._name = name

    def grade(self, *, expected: str, actual: str) -> Grade:
        ok = self._fn(expected, actual)
        return Grade(
            passed=ok, score=1.0 if ok else 0.0, reason="" if ok else f"{self._name} false"
        )
