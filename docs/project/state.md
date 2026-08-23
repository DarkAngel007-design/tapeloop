# Current state

**Updated:** 2026-08-24 · **Milestone:** M5 next · **Remote:** `DarkAngel007-design/tapeloop` (private)

> This file is the handoff. Update it at the end of every session, before anything else.

## Where we are

| Milestone | Status | Evidence |
|-----------|--------|----------|
| M0 — bare loop | ✅ shipped | 137 code lines (enforced by test), two-tool task verified against a fake client *and* live |
| M1 — registry, effects, four seams | ✅ shipped | 27 tests, 0 hand-written schemas, Anthropic adapter type-checks |
| M2 — streaming, interrupts, retries | ✅ shipped | `test_the_ship_criterion`: two forced 429s *and* a mid-stream cancel in one run |
| M3 — the tape | ✅ shipped | 100% cache hit and byte-identical tapes on re-run |
| M4 — replay, fork, diff | ✅ shipped | fork at step 12 replays the prefix in <1s; CLI works |
| **M5 — sandbox, permissions, resume** | ⬜ **next** | the layer most portfolios skip |

## Confirm the working state

```bash
uv sync && uv run pytest && uv run ruff check . && uv run pyright
git config core.hooksPath .githooks   # required after a fresh clone
```

**After cloning, set `core.hooksPath`.** Git does not install hooks automatically, and the
pre-commit secret guard in `.githooks/` is inert until you do.

Expected as of this writing: **72 passed**, ruff clean, pyright **0 errors**. If any of these
fail on a fresh clone, that is a real regression — fix it before starting anything new.

## M5 — what "done" means

**Ship criterion:** a repo file that tries to instruct the agent is refused, and it is a test.

1. **`DockerExecutor`** behind the `Executor` seam that has been in place since M1 — so this adds
   a backend rather than rewriting call sites. Read-only mounts outside the workspace, an egress
   allowlist, no credentials inside.
2. **Permission rules** per tool *and per argument*: `Bash(git status)` is not `Bash(*)`.
3. **Prompt-injection defence** — the instruction/data boundary. Tool output is data, never
   commands, regardless of how authoritative it sounds. The hostile-README test is the gate.
4. **Workspace snapshotting**, which is what makes `resume` possible as distinct from `replay`
   (ADR-0006) and upgrades a `simulated` fork to `faithful` (ADR-0016).
5. `SECURITY.md` — it deliberately does not exist yet, because until now there was nothing
   truthful to put in it.

**Design question to settle first:** what is the permission model's storage? Per-project config,
per-session memory, or both — and does an approval persist across runs? Getting this wrong makes
the tool either annoying or unsafe, and it is much cheaper to decide before the sandbox is wired
in than after.

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

Start M5: write the permission-storage ADR, then `DockerExecutor`, then permission rules, then the
hostile-README test, then snapshotting, then `SECURITY.md`.

**Also pending:** the repo is still private. M4 was the agreed point to flip it public, and the
headline demo now works. That is a one-line change (`gh repo edit --visibility public`) and the
author's call.
