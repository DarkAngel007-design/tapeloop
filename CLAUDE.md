# CLAUDE.md

Conventions for agents working in this repository.

## What this project is

tapeloop is an agent runtime whose distinguishing feature is an append-only **tape** of every
step, enabling deterministic replay, fork-at-step-N, and run diffing. Read `README.md` and
`docs/adr/` before making structural changes.

## Hard rules

**Determinism (Contract 1).** Nothing in `src/` may call `time.time()`, `datetime.now()`,
`random.*` without an explicit seed, or iterate an unordered collection in a way that reaches a
prompt or a step key. These break replay. Timestamps are injected at the boundary and stored on
the tape, never read mid-run. Ruff enforces part of this; the rest is on review.

**Effect classes (Contract 3).** Every tool declares `pure`, `read`, or `write`. An undeclared
tool is treated as `write`. Never widen a tool's class to make a test pass.

**The tape format is a contract.** `docs/reference/transcript-format.md` is a compatibility
promise once anyone has a saved tape. Changing it requires a new ADR and a migration.

**Provider neutrality (Contract 5).** Nothing outside `src/tapeloop/providers/` may reference a
provider's wire format. Anything the runtime cannot interpret is stored as an opaque payload and
returned verbatim to the provider that produced it — never inspected, never rewritten.

## Decisions

Architecture Decision Records live in `docs/adr/`, numbered and immutable. A decision that
changes gets a **new** ADR marking the old one superseded. Never edit a decided ADR's substance.

## Documentation

`docs/` follows [Diátaxis](https://diataxis.fr): `tutorials/` (learning), `how-to/` (doing),
`reference/` (looking up), `explanation/` (understanding). Do not mix the four modes in one page.
Every fenced Python block under `docs/` runs in CI — if you write an example, it must work.

## Commands

```bash
uv sync                    # install
uv run pytest              # tests (live-API tests are deselected by default)
uv run pytest -m live      # tests that cost money — never in CI
uv run ruff check .        # lint
uv run ruff format .       # format
uv run pyright             # types, strict mode
```

## Style

Match the surrounding code. Type annotations on everything public. Comments explain *why*, not
*what*. `m0/` is deliberately unabstracted and is exempt from most of this — do not "clean it up".
