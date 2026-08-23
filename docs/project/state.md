# Current state

**Updated:** 2026-08-23 · **Milestone:** M4 next · **Remote:** `DarkAngel007-design/tapeloop` (private)

> This file is the handoff. Update it at the end of every session, before anything else.

## Where we are

| Milestone | Status | Evidence |
|-----------|--------|----------|
| M0 — bare loop | ✅ shipped | 137 code lines (enforced by test), two-tool task verified against a fake client *and* live |
| M1 — registry, effects, four seams | ✅ shipped | 27 tests, 0 hand-written schemas, Anthropic adapter type-checks |
| M2 — streaming, interrupts, retries | ✅ shipped | `test_the_ship_criterion`: two forced 429s *and* a mid-stream cancel in one run |
| M3 — the tape | ✅ shipped | 100% cache hit and byte-identical tapes on re-run |
| **M4 — replay, fork, diff** | ⬜ **next** | the demo that goes at the top of the README |

## Confirm the working state

```bash
uv sync && uv run pytest && uv run ruff check . && uv run pyright
git config core.hooksPath .githooks   # required after a fresh clone
```

**After cloning, set `core.hooksPath`.** Git does not install hooks automatically, and the
pre-commit secret guard in `.githooks/` is inert until you do.

Expected as of this writing: **64 passed**, ruff clean, pyright **0 errors**. If any of these
fail on a fresh clone, that is a real regression — fix it before starting anything new.

## M4 — what "done" means

**Ship criterion:** editing the system prompt and forking at step 12 replays 0–11 in under a second.

Everything M4 needs now exists: the tape records step keys, and `StepCache` turns a key into a
response. What is missing is the operations on top and a way to invoke them.

1. `replay(tape)` — re-run from cache, reporting where it diverged and why.
2. `fork(tape, at=n)` — a new run sharing history to step *n*, then live. Cross-provider forks
   must **visibly drop** opaque payloads (ADR-0011), never silently.
3. `diff(a, b)` — step-by-step comparison, anchored at the first divergent key.
4. A CLI (`typer`) — this is the first milestone with a user-facing surface, and the README's
   headline demo depends on it existing.
5. An asciinema recording of fork-and-replay for the README.

**Design question to settle first:** what does `fork` do about tool *effects*? Replaying a cached
`write` means the workspace is not in the state the forked history implies (ADR-0006). Does fork
refuse without a snapshot, warn, or replay in simulation by default? This is the practical edge
of the replay/resume distinction and deserves an ADR before code.

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
- **Never write a tape inside the agent's workspace.** The tape becomes something the agent
  observes, so `list_files` differs on the second run, the step key diverges, and replay misses
  for no visible reason. Recording must not change what is recorded.
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

Start M4. Write the fork-and-effects ADR first (see above), then `replay` / `fork` / `diff`, then
the CLI, then re-record the README demo. M4 is also the point agreed for flipping the repo from
private to public — the headline demo will finally be real.
