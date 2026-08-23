# Current state

**Updated:** 2026-08-23 · **Milestone:** M3 next · **Remote:** `DarkAngel007-design/tapeloop` (private)

> This file is the handoff. Update it at the end of every session, before anything else.

## Where we are

| Milestone | Status | Evidence |
|-----------|--------|----------|
| M0 — bare loop | ✅ shipped | 137 code lines (enforced by test), two-tool task verified against a fake client *and* live |
| M1 — registry, effects, four seams | ✅ shipped | 27 tests, 0 hand-written schemas, Anthropic adapter type-checks |
| M2 — streaming, interrupts, retries | ✅ shipped | `test_the_ship_criterion`: two forced 429s *and* a mid-stream cancel in one run |
| **M3 — the tape** | ⬜ **next** | the differentiator begins here |

## Confirm the working state

```bash
uv sync && uv run pytest && uv run ruff check . && uv run pyright
git config core.hooksPath .githooks   # required after a fresh clone
```

**After cloning, set `core.hooksPath`.** Git does not install hooks automatically, and the
pre-commit secret guard in `.githooks/` is inert until you do.

Expected as of this writing: **44 passed**, ruff clean, pyright **0 errors**. If any of these
fail on a fresh clone, that is a real regression — fix it before starting anything new.

## M3 — what "done" means

**Ship criterion:** re-running an unchanged agent is a 100% cache hit, byte-identical.

This is where the project earns its name. Four pieces:

1. **Append-only JSONL transcript** with a `format_version` on the first line (ADR-0010).
   Replaces `InMemoryStore` behind the existing `TranscriptStore` seam — the loop should not
   change.
2. **Canonical serialization.** Sorted keys, stable separators, an explicit float format, and a
   decided ordering for a parallel tool-result set. Getting any of these wrong produces a false
   cache miss, which presents as "replay is broken" and is miserable to debug. Write the test
   before the implementation.
3. **Content-addressed step keys** — `sha256(provider, model, params, canonical(tool_schemas),
   canonical(events[0..n]))`. Explicitly excludes timestamps and run ids (ADR-0004).
4. **The determinism lint rule** and a replay-equivalence test, so Contract 1 is enforced by CI
   rather than by discipline.

Write `docs/reference/transcript-format.md` as part of this milestone, not after. The moment a
tape exists on someone's disk, that document is a compatibility promise.

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
- **`.env.example` is committed by design — never put a real key in it.** One was pasted there
  and swept into six commits by a blanket `git add -A`; the history had to be rewritten. The
  `.githooks/pre-commit` guard now blocks key-shaped strings from being staged.
- **Do not use blanket `git add -A` without reading `git status` first.** That is what caused
  the above.
- **Settings read at import time will not see `.env`** unless `load_dotenv()` runs first, at
  module level. The failure mode is silent: the wrong model, no error.
- **`get_type_hints` cannot resolve a type declared inside a function** without `localns`. Tool
  packs are built by factory functions, so this is the normal case.
- **openai 3.x uses `omit`, not `NOT_GIVEN`,** for optional request parameters, and vendors its
  HTTP layer as **`httpx2`**, not `httpx`.
- **A `# pyright: ignore` on a call defeats overload resolution.** `stream=True` silently failed
  to select the streaming overload. Cast at a named boundary instead of ignoring at call sites.
- **Streaming reports zero tokens** unless `stream_options={"include_usage": True}` is set. The
  run works; only the cost accounting is wrong, so it would surface much later as a mystery.
- **`@contextmanager` with `-> Iterator[T]` is deprecated on 3.14.** Use `Generator[T]`.

## Next action

Start M3, in this order:

1. `docs/reference/transcript-format.md` — write the spec first. It is a compatibility promise.
2. Canonical serialization plus its tests, before anything depends on it.
3. `record/jsonl.py` — a `TranscriptStore` writing versioned append-only JSONL.
4. Step keys, and the cache-hit test that is the ship criterion.
5. The determinism lint rule (no wall-clock, no unseeded randomness, no unordered iteration
   reaching a prompt or a key) and a replay-equivalence test.

**Open design question to settle first:** what is the canonical ordering of a parallel
tool-result set? Arrival order is not stable across providers. Sorting by `call_id` is stable but
discards the order the model asked in. Decide, and write the ADR before implementing — this is
exactly the kind of thing that is cheap now and a migration later.
