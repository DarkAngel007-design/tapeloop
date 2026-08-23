# Current state

**Updated:** 2026-08-24 · **Milestone:** M6 next · **Remote:** `DarkAngel007-design/tapeloop` (**public** since M4)

> This file is the handoff. Update it at the end of every session, before anything else.

## Where we are

| Milestone | Status | Evidence |
|-----------|--------|----------|
| M0 — bare loop | ✅ shipped | 137 code lines (enforced by test), two-tool task verified against a fake client *and* live |
| M1 — registry, effects, four seams | ✅ shipped | 27 tests, 0 hand-written schemas, Anthropic adapter type-checks |
| M2 — streaming, interrupts, retries | ✅ shipped | `test_the_ship_criterion`: two forced 429s *and* a mid-stream cancel in one run |
| M3 — the tape | ✅ shipped | 100% cache hit and byte-identical tapes on re-run |
| M4 — replay, fork, diff | ✅ shipped | fork at step 12 replays the prefix in <1s; CLI works |
| M5 — sandbox, permissions, resume | ✅ shipped | hostile-README test: the model obeys the injection, the command does not run |
| **M6 — eval harness & first numbers** | ⬜ **next** | where it stops being a demo |

## Confirm the working state

```bash
uv sync && uv run pytest && uv run ruff check . && uv run pyright
git config core.hooksPath .githooks   # required after a fresh clone
```

**After cloning, set `core.hooksPath`.** Git does not install hooks automatically, and the
pre-commit secret guard in `.githooks/` is inert until you do.

Expected as of this writing: **88 passed**, ruff clean, pyright **0 errors**. If any of these
fail on a fresh clone, that is a real regression — fix it before starting anything new.

## M6 — what "done" means

**Ship criterion:** a committed results table with mean ± spread, and a baseline to regress against.

This is the milestone that separates the project from every other "I built an agent" repo. Not
because evaluation is hard, but because almost nobody publishes numbers with variance.

1. **~30 domain-neutral tasks** with deterministic graders where possible. File manipulation, data
   wrangling, API-shaped work. Written by hand, so no model memorized them.
2. **5 seeds per task.** A single run is not a result — agent runs are high-variance, and a lucky
   pass proves nothing. Report mean ± spread or report nothing.
3. **Fork makes this affordable**: shared prefixes replay from cache, so a suite is far cheaper
   than 150 cold runs. This is the first milestone where M4 pays for itself.
4. **`--require-faithful` on every eval fork** (ADR-0016). A silently simulated run poisons a table.
5. **A written failure taxonomy** — named modes, measured frequencies, what changed for each.
   `docs/evals/failure-taxonomy.md`. This is the artifact a reviewer actually stops on.

**Design question to settle first:** what is the grading contract for a task whose correct output
is not a fixed string? An `LLM-as-judge` Grader is the obvious answer and introduces
nondeterminism into the one place that must be trustworthy. Options: judge with a pinned model and
record the judgment on the tape, or restrict the suite to deterministically-gradable tasks and
accept narrower coverage. Decide before writing the runner.

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
- **A tape can contain secrets** — it records everything the tools read. `.tapeloop/` is
  gitignored; review a tape before attaching it to a bug report.
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

Start M6: settle the grading-contract ADR, then the task suite, then the runner with seeded
repeats, then the first results table, then the failure taxonomy.

**Carried debt from M5:** `SnapshotStore` exists and is tested, but nothing calls it yet. Wiring it
into `resume` and into fork's `faithful` upgrade (ADR-0016) is a small, well-defined job that was
deliberately left out of M5 to keep the milestone's ship criterion honest. Do it before or during
M6 — the eval suite is the first thing that will actually want `resume`.
