"""The ModelClient contract, enforced.

ADR-0002 says the Protocol is only a signature and the real definition of a
`ModelClient` is the conformance suite. This is where that becomes true rather than
aspirational.

The Anthropic target is included deliberately while its adapter is signatures-only.
It is expected to fail, and the failure is asserted — so the day someone implements
it, this file already states what the implementation has to satisfy, and nobody gets
to shape the contract around whatever they happened to build.
"""

from __future__ import annotations

import pytest

from tapeloop.providers.conformance import ConformanceTarget, run_conformance
from tapeloop.providers.targets import BUILTIN_TARGETS, anthropic_target, openai_target


def test_the_openai_adapter_is_fully_conformant() -> None:
    report = run_conformance(openai_target())
    assert report.passed, "\n" + report.render()
    assert len(report.checks) >= 16, "the suite lost checks"


@pytest.mark.parametrize("cid", ["C05", "C12"])
def test_the_checks_that_found_real_bugs_still_run(cid: str) -> None:
    """C05 caught the OpenAI renderer not ordering tool results against their calls;
    the ordering lived only in the tape codec, so a Message built in memory reached
    the wire unordered. C12 could not even be constructed at first, because the SDK
    rejects an unknown finish_reason before our fallback runs.

    Both are pinned by id so a future refactor cannot quietly drop them.
    """
    report = run_conformance(openai_target())
    check = next((c for c in report.checks if c.id == cid), None)
    assert check is not None, f"{cid} disappeared from the suite"
    assert check.passed, check.detail


def test_the_anthropic_adapter_is_registered_and_currently_fails() -> None:
    """Registered before it exists, on purpose (ADR-0001).

    When this test starts failing, the adapter has been implemented and the assertion
    should be inverted — that is the moment the provider abstraction is proven rather
    than asserted, and it is the last open item in the charter's success criteria.
    """
    report = run_conformance(anthropic_target())
    assert not report.passed, (
        "the Anthropic adapter now passes conformance. Invert this assertion, tick the "
        "charter criterion, and note it in the changelog — the abstraction is proven."
    )
    reasons = {c.detail for c in report.failures}
    assert all("not implemented" in r for r in reasons), (
        "a failure that is not 'not implemented' means the stub is wrong, not absent:\n"
        + report.render()
    )
    # It must fail for the right reason, not because it was never wired up.
    assert next(c for c in report.checks if c.id == "C01").passed, "provider_id should work"


def test_every_builtin_target_is_runnable() -> None:
    """A target that cannot even be constructed is worse than one that fails."""
    for name, factory in BUILTIN_TARGETS.items():
        target = factory()
        assert isinstance(target, ConformanceTarget)
        assert target.provider_id, name
        report = run_conformance(target)
        assert len(report.checks) == len(run_conformance(openai_target()).checks), (
            f"{name} ran a different number of checks — the suite must be identical for all"
        )


def test_every_documented_divergence_has_a_check() -> None:
    """`provider-differences.md` is the spec; this is its coverage.

    A divergence in the table with no check behind it is a claim nobody verifies.
    """
    from pathlib import Path

    table = (
        Path(__file__).resolve().parents[1] / "docs/explanation/provider-differences.md"
    ).read_text(encoding="utf-8")
    documented = {f"#{n}" for n in range(1, 8) if f"| {n} |" in table}
    covered = {c.divergence for c in run_conformance(openai_target()).checks}
    missing = documented - covered
    assert not missing, f"divergences with no conformance check: {sorted(missing)}"
