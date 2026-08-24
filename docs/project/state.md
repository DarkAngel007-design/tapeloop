# Current state

**Updated:** 2026-08-25 · **Milestone:** roadmap complete · **Remote:** `DarkAngel007-design/tapeloop` (**public** since M4)

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
| M6 — eval harness & baseline | ✅ shipped | 0.911 ± 0.268 deterministic, committed with the model id |
| M7 — context management | ✅ shipped | no regression on 18 shared tasks; −95.6% tokens on the context task |
| M8 — subagents & MCP | ✅ shipped | server verified against raw JSON-RPC from a foreign peer |
| M9 — viewer & observability | ✅ shipped | self-contained HTML trace, tree of tapes, cost visible |

## Confirm the working state

```bash
uv sync && uv run pytest && uv run ruff check . && uv run pyright
git config core.hooksPath .githooks   # required after a fresh clone
```

**After cloning, set `core.hooksPath`.** Git does not install hooks automatically, and the
pre-commit secret guard in `.githooks/` is inert until you do.

Expected as of this writing: **208 passed, 14 deselected (live)**, ruff clean, pyright **0 errors**. If any of these
fail on a fresh clone, that is a real regression — fix it before starting anything new.

## The roadmap is finished. What is actually left

All ten milestones shipped, all carried debt cleared. What remains is not a milestone list, it is
the ordinary work of a pre-1.0 project:

1. **The Anthropic adapter.** Deliberately never a milestone. **The conformance suite now exists**
   (`tapeloop conformance`), so this is a pass/fail check rather than a hopeful integration: the
   Anthropic target is already registered and fails 15 of 18 by name, which is the implementation
   checklist. When `test_the_anthropic_adapter_is_registered_and_currently_fails` starts failing,
   invert it and tick the charter criterion. Needs credits; nothing else blocks it.
2. **Publish `0.1.0` to PyPI.** The name is unclaimed. The API is not stable and should not pretend
   to be, but a claimed name and an installable package cost nothing.
3. **Grow the eval suite.** 19 deterministic tasks is enough to catch a regression and not enough
   for a confident absolute claim. Every new task needs the null-model check.
4. **Fill in the failure taxonomy** as new modes appear. F11 and F12 came from one baseline run.

**Do not start these by adding milestones.** The roadmap is complete; treating it as open-ended is
how a finished project stops looking finished.

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
- **A judged score moving between runs is usually the judge, not the agent.** Check
  `judge_agreement` before believing a judged delta — see `docs/evals/m7-delta.md`.
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

## The eval suite is now 30 tasks, and mostly saturated

Current baseline: `evals/baseline-2026-08-25/` — deterministic **0.900 ± 0.286**, judged
0.933 ± 0.116, on `gpt-5.4-mini-2026-03-17`. Compare **shared tasks only** against it.

**Only 4 of 30 tasks carry signal.** The other 26 score 5/5 and cannot detect a regression. Adding
eleven "hard" tasks moved that from 2/19 to 4/30 — the oracles proved them passable and the
null-model guard proved them non-trivial, and neither bound predicts *trivial for a capable model*.

The four that discriminate point somewhere specific: `impossible-request` 0/5,
`refuse-destructive` 0/5, `partial-availability` 4/5, `count-with-exclusions` 1/5. Three of the
four are about **restraint, not capability** — declining, admitting a limit, noticing something is
absent. That is where this model is weak and where future tasks should aim. Writing another
"transform this CSV" task will produce another 5/5.

## Superseded



The suite grew from 19 to 30 deterministic tasks on 2026-08-25. **`evals/baseline-2026-08-24/`
and `evals/m7-2026-08-24/` are no longer comparable to a new run**, for exactly the reason
`docs/evals/m7-delta.md` documents: headline means across different task sets are not
comparable. Comparing shared tasks only still works and is the right move for a regression
check; a fresh baseline is needed before quoting a headline number again.

Cost estimate: 33 tasks × 5 seeds, roughly 1.5× the last full run (~196k input tokens).

## Next action

Nothing is blocked. The highest-value next thing is the **Anthropic adapter** — it is the only
outstanding claim in the charter's success criteria, and passing the conformance suite unmodified
is what turns "provider-neutral" from a design intention into a demonstrated fact.

Regression policy unchanged: re-run `uv run tapeloop eval --repeats 5` and compare **shared tasks
only** against `evals/m7-2026-08-24/`. A move greater than one spread (0.261) is investigated
before merging.

Regression policy: re-run `uv run tapeloop eval --repeats 5` and compare against
`evals/m7-2026-08-24/`. A move greater than one spread (0.261) is investigated before merging.
Compare **shared tasks only** — headline means across different task sets are not comparable, a
mistake `docs/evals/m7-delta.md` documents.

The two known-failing tasks are findings about the model, not bugs: `impossible-request` 0/5 and
`count-with-exclusions` 2/5. Do not tune the suite to make them pass.

**Carried debt, still open:** `SnapshotStore` is built and tested but nothing calls it. Wiring it
into `resume` and into fork's `faithful` upgrade (ADR-0016) is small and well defined. Do it
alongside M7.

**Scope decision, 2026-08-24:** M9 is reduced to containerise + OTel + trace viewer. Worker pool,
queue, autoscaling and per-user quotas are cut — they follow from "not a hosted service" and only
existed to justify the phrase "production grade". Recorded in `ROADMAP.md` and the charter's
non-goals so it does not get relitigated.

**Order is not negotiable, and here is why:** M7 adds compaction and truncation records to the
tape; M8 turns a run from a list into a tree of child runs. Both change what a trace *contains*, so
a viewer built before them gets built twice — the same dependency argument that kept the sandbox
until M5.
