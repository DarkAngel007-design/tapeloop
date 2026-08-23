# Current state

**Updated:** 2026-08-23 · **Milestone:** M2 in progress · **Commits:** 3, local only, no remote

> This file is the handoff. Update it at the end of every session, before anything else.

## Where we are

| Milestone | Status | Evidence |
|-----------|--------|----------|
| M0 — bare loop | ✅ shipped | 137 code lines (enforced by test), two-tool task verified against a fake client *and* live |
| M1 — registry, effects, four seams | ✅ shipped | 27 tests, 0 hand-written schemas, Anthropic adapter type-checks |
| **M2 — streaming, interrupts, retries** | 🚧 **in progress** | see below |
| M3 — the tape | ⬜ not started | the differentiator begins here |

## Confirm the working state

```bash
uv sync && uv run pytest && uv run ruff check . && uv run pyright
```

Expected as of this writing: **27 passed**, ruff clean, pyright **0 errors**. If any of these
fail on a fresh clone, that is a real regression — fix it before starting anything new.

## M2 — what "done" means

**Ship criterion:** survives a forced 429 and a mid-stream Ctrl-C without corrupting the tape.

Four pieces:

1. **Streaming** — token-by-token output from the provider.
2. **Partial-JSON accumulation** — tool arguments arrive as string *fragments* across chunks and
   must be assembled per call index before parsing. This is the subtle one.
3. **Cancellation** — a Ctrl-C mid-stream must stop cleanly and leave the record consistent: no
   half-written assistant message, an explicit cancellation event instead.
4. **Retries** — a typed error chain distinguishing retryable (429, 5xx, connection) from
   terminal (400, 404), with exponential backoff plus jitter, honouring `Retry-After`.

**Determinism note:** retry jitter uses randomness, which `CLAUDE.md` bans in `src/`. The
resolution is that retry timing is transport-level — it never reaches a prompt or a step key —
and the policy owns a *seeded* `random.Random` instance rather than touching the global one.

## Environment facts that cost time to rediscover

- Python **3.14**, `uv` **0.12**. Managed entirely by `uv`; there is no `requirements.txt`.
- The `openai` SDK is at **3.x, not 1.x.** Introspect the installed version rather than writing
  from memory — `max_tokens` is superseded by `max_completion_tokens`.
- `pyright` runs **strict on `src/`**. `m0/` and `tests/` opt down via a file-level
  `# pyright: basic` pragma, visible in the file rather than hidden in config.
- `reportUnusedFunction` is off project-wide: registration decorators (`@registry.tool`,
  `@pytest.fixture(autouse=True)`) define functions never called by name. That is the pattern.
- **No test may hit a live API.** Everything runs against fakes. A `live` pytest marker exists
  for tests that cost money; it is deselected by default and must never run in CI.

## Traps already hit — do not re-learn these

- **`find_dotenv()` walks up from the calling module's directory, not the cwd.** Tests once read
  the author's real `.env` because of this. Fixed with `usecwd=True` plus a `conftest.py` autouse
  fixture that scrubs the environment for every test. Do not remove that fixture.
- **Never assert directly on a secret-shaped value.** pytest renders both sides of a failed
  comparison, which is how a live API key gets printed. Compare into a bool, then assert the bool.
- **Settings read at import time will not see `.env`** unless `load_dotenv()` runs first, at
  module level. The failure mode is silent: the wrong model, no error.
- **`get_type_hints` cannot resolve a type declared inside a function** without `localns`. Tool
  packs are built by factory functions, so this is the normal case.

## Next action

Implement M2 in this order — each step is independently testable:

1. `core/errors.py` — the typed error taxonomy.
2. `core/retry.py` — `RetryPolicy` with seeded jitter and `Retry-After` handling.
3. `core/cancel.py` — a cancellation token plus a SIGINT context manager.
4. `providers/base.py` — add `stream()` to the `ModelClient` Protocol; the Anthropic
   signatures-only adapter must be extended to match, or it stops type-checking (which is the
   design check working).
5. `providers/openai.py` — implement `stream()` with a tool-call fragment accumulator.
6. `core/loop.py` — thread streaming, cancellation, and retries through.
7. Tests, including the ship-criterion test: forced 429 *and* mid-stream interrupt.
