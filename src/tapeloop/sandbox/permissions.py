"""Permissions: which tool calls are allowed, and who decided.

Per tool *and* per argument (ADR-0017). `run_command(git status)` and
`run_command(*)` are different questions, and a model that is allowed to run
`git status` has not thereby been allowed to run anything.

Defaults come from effect classes, which already carry the information: reading is
allowed, writing asks. Nothing new has to be declared for the common case.
"""

from __future__ import annotations

import fnmatch
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from tapeloop.tools.effects import Effect


class Verdict(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class Rule:
    """One line of policy: a tool, an argument glob, and an answer."""

    tool: str
    pattern: str = "*"
    verdict: Verdict = Verdict.ALLOW

    def matches(self, tool: str, rendered: str) -> bool:
        return fnmatch.fnmatch(tool, self.tool) and fnmatch.fnmatch(rendered, self.pattern)

    def as_text(self) -> str:
        return f"{self.tool}({self.pattern})"


@dataclass(frozen=True, slots=True)
class Decision:
    verdict: Verdict
    tool: str
    rendered: str
    rule: str
    """Which rule decided, or how the default was reached. Goes on the tape verbatim."""

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW


def render_arguments(arguments: dict[str, Any]) -> str:
    """Flatten arguments to the string that patterns match against.

    Documented rather than incidental, because a rule's meaning depends on it: values
    in declaration order, space-joined. `{"command": "git status"}` renders to
    `git status`, so `run_command(git status*)` reads the way someone would expect.
    """
    return " ".join(str(v) for v in arguments.values())


Prompter = Callable[[Decision], bool]
"""Asks a human. Returns True to allow. Never called during replay."""


@dataclass(slots=True)
class PermissionPolicy:
    """Rules plus whatever the human said this session."""

    rules: list[Rule] = field(default_factory=list[Rule])
    prompter: Prompter | None = None
    session_grants: set[tuple[str, str]] = field(default_factory=set[tuple[str, str]])
    denied_by_default: bool = False
    """When True, an unmatched `write` is denied rather than asked. Used by CI."""

    @classmethod
    def load(cls, path: Path, **kw: Any) -> PermissionPolicy:
        """Read `.tapeloop/permissions.toml`. A missing file means defaults only."""
        rules: list[Rule] = []
        if path.exists():
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            for verdict in (Verdict.DENY, Verdict.ALLOW, Verdict.ASK):
                # Deny first, so an explicit deny beats an explicit allow no matter
                # what order they appear in the file.
                for entry in data.get(verdict.value, []):
                    tool, _, pattern = str(entry).partition(":")
                    rules.append(Rule(tool=tool, pattern=pattern or "*", verdict=verdict))
        return cls(rules=rules, **kw)

    def decide(self, tool: str, arguments: dict[str, Any], effect: Effect) -> Decision:
        rendered = render_arguments(arguments)

        for rule in self.rules:
            if rule.matches(tool, rendered):
                if rule.verdict is not Verdict.ASK:
                    return Decision(rule.verdict, tool, rendered, rule.as_text())
                return self._ask(tool, rendered, effect, rule.as_text())

        # No rule: the effect class decides. Reading is free; writing is a question.
        if effect is not Effect.WRITE:
            return Decision(Verdict.ALLOW, tool, rendered, f"default:{effect.value}")
        if self.denied_by_default:
            return Decision(Verdict.DENY, tool, rendered, "default:write(non-interactive)")
        return self._ask(tool, rendered, effect, "default:write")

    def _ask(self, tool: str, rendered: str, effect: Effect, rule: str) -> Decision:
        if (tool, rendered) in self.session_grants:
            return Decision(Verdict.ALLOW, tool, rendered, f"{rule} → granted this session")
        pending = Decision(Verdict.ASK, tool, rendered, rule)
        if self.prompter is None:
            # Nobody to ask. Refusing is the only safe answer -- assuming yes is how
            # an unattended run does something nobody agreed to.
            return Decision(Verdict.DENY, tool, rendered, f"{rule} → no prompter available")
        if self.prompter(pending):
            self.session_grants.add((tool, rendered))
            return Decision(Verdict.ALLOW, tool, rendered, f"{rule} → approved")
        return Decision(Verdict.DENY, tool, rendered, f"{rule} → refused")


def console_prompter(decision: Decision) -> bool:  # pragma: no cover - interactive
    answer = input(f"  allow {decision.tool}({decision.rendered})? [y/N] ")
    return answer.strip().lower() in {"y", "yes"}
