# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning is [semver](https://semver.org/); pre-1.0 means anything may move.

## [Unreleased]

### Added
- **The `ModelClient` conformance suite** (`providers/conformance.py`) — 18 checks defining what a
  ModelClient *is*, one per row of the divergence table plus general invariants. Shipped in the
  package rather than in `tests/`, so a third-party adapter author can import and run it. No
  network: every check runs against synthetic wire payloads the adapter builds itself, so a new
  provider can be conformance-tested before anyone has a key for it.
- **`tapeloop conformance`** — runs it, non-zero exit on failure.
- The **Anthropic target is registered while still unimplemented** and fails 15 of 18 by name.
  That is deliberate: the contract is written before the implementation, so nobody can shape it
  around whatever they happened to build. `test_the_anthropic_adapter_is_registered_and_currently_fails`
  will start failing the day it works, which is the signal to tick the charter criterion.

### Fixed
- **`DockerExecutor` could not write to the workspace on Linux.** `--cap-drop=ALL` removes
  `CAP_DAC_OVERRIDE`, the capability that lets root ignore permission bits — so root in the
  container was not the owner of a bind-mounted workspace and could not write to it. Perfectly
  isolated and completely useless.

  Invisible on macOS, where Docker Desktop's volume driver rewrites ownership so everything
  appears owned by the container user. CI on Linux caught it on its first run, through the
  positive-control test that exists because isolation which breaks the feature is a broken
  feature rather than security. The container now runs as the host uid, which is also the better
  posture — the fix and the hardening are the same change.
- **The OpenAI renderer did not order tool results against their calls.** ADR-0014 makes that a
  canonical invariant, but the ordering lived only in the tape codec — so a `Message` built in
  memory and handed straight to the renderer reached the wire unordered. Found by conformance
  check C05, on an adapter that had been in production since M1.
- No check existed for divergence #5, prompt-cache reporting. Found by a test asserting every
  documented divergence has a check behind it. A row in the table verified by nothing.

## [0.1.1] — 2026-08-24

### Fixed
- **The MCP server told every host it was version `0.0.0`.** `SERVER_VERSION` and the client's
  `clientInfo.version` were both hardcoded and stale — the same drift the 0.1.0 gate claimed to
  have eliminated. Both now read `__version__`.

  The gate had a version-consistency grep and it missed them: the pattern was case-sensitive and
  only matched `version =`, so `SERVER_VERSION = "0.0.0"` and `"version": "0.0.0"` were both
  invisible. Found by exercising the MCP handshake against the *published* package, which is the
  only reason it surfaced at all.

  Cosmetic in effect — nothing negotiates on it today — but a handshake reporting the wrong
  version is a compatibility negotiation conducted on false information.

### Added
- `test_no_version_string_is_hardcoded_anywhere_in_src`, and an assertion on the MCP handshake's
  reported version. Neither existed, which is why this shipped.

## [0.1.0] — 2026-08-24

First release. All ten roadmap milestones shipped. **The API is not stable**; 0.x is
the honest signal for that and nothing here should be depended on across versions.

Verified before publishing: built wheel installs and passes the full suite on Python
3.11, 3.12 and 3.14, and against the declared `openai>=2.0` floor as well as latest.

### Verified before release
- Full eval regression against the M7 baseline: deterministic **0.916 ± 0.261 → 0.916 ± 0.261**,
  a delta of exactly `+0.0000` across all 19 shared deterministic tasks. Results committed at
  `evals/prerelease-0.1.0/`.
- The only movement was `summarise-data`, a judged row that has now scored 3/5, 5/5 and 4/5 across
  three runs on answers verified correct by hand. Confirmed as judge instability (J1), not a
  regression — which is what `judge_agreement` exists to make visible.

### Fixed before release
- **`openai>=1.60` was a broken floor.** `omit` and `ChatCompletionToolUnionParam` do
  not exist before 2.0, both are used unconditionally, so `pip install` could have
  resolved a version that fails at import. Floor corrected to `>=2.0` and verified.
- The version was written in three places. It is now single-sourced from the package,
  because a drifted copy makes a tape's header claim a writer version that never wrote it.
- A zero cost rendered as `$0`, which reads as a missing value rather than a free run.

## [Unreleased]

### Added
- **Trace viewer** — `tapeloop view <tape>` writes one self-contained HTML file. No server, no
  collector, no external asset: a trace you can only read by running something is a trace you
  cannot attach to a bug report. Renders subagents as a **tree**, walking child tapes (ADR-0021).
- **Cost accounting** (`observe/cost.py`) — prices are data in `prices.toml`, not code. A model
  with no entry renders as `—`, never as zero, because a cost figure that is quietly wrong is
  worse than one that is visibly absent. Cached input is billed at its own rate when given.
- **OpenTelemetry export** — optional, and built *from the tape* rather than instrumented into the
  loop, so a run recorded last week can be traced today and there is only one source of truth.
- **Dockerfile** — runs the CLI as an unprivileged user. Deliberately unremarkable: the charter
  says this is not a hosted service.
- **Snapshots wired in** — `Agent` takes a workspace snapshot before each step, and a fork with a
  matching snapshot is restored and reported `faithful` instead of `simulated` (ADR-0016). This
  clears the debt M5 deliberately left open.

### Added
- **Subagents** (`agents/subagent.py`) — isolated context, narrowed tool set, and a *structured*
  return, which is what makes them composable rather than merely recursive. Each child writes its
  own tape (ADR-0021), so `show` / `fork` / `diff` work on a subagent unchanged. A failed child
  does not take down a fan-out.
- **Orchestration shapes** (`agents/orchestrate.py`) — `pipeline` and `barrier`, with
  `compare_shapes` measuring the difference deterministically.
- **MCP server** (`mcp/server.py`) — exposes a `Registry` over stdio JSON-RPC. Run with
  `python -m tapeloop.mcp.server`. Effect classes cannot cross the wire, so they are carried in
  the description text rather than silently lost.
- **MCP client** (`mcp/client.py`) — imports a third-party server's tools into a `Registry`, where
  they are dispatched, permission-gated and recorded exactly like local ones. Imported tools
  default to `write` (ADR-0005), because a remote tool that mutates must never look safe.
- **`Registry.register`** — a public way to add a spec whose schema came from the wire rather than
  from a signature.
- [`docs/evals/m8-orchestration.md`](docs/evals/m8-orchestration.md).

### Added
- **Context management** (`context/`) — a `ContextBudget` that caps oversized tool results and
  triggers compaction near the window ceiling.
- **Deterministic truncation** keeping head and tail with a visible elision marker, so an agent
  that has been given an excerpt knows to search rather than assume. Pure by construction: it
  feeds step keys, so anything non-deterministic here would break replay.
- **Compaction as a recorded step** (ADR-0020) — summarising is a model call, so it is keyed,
  cached and written to the tape. Done as a side effect it would produce a different summary on
  every replay and every key after it would diverge. The system prompt and the original task are
  never compacted.
- **Labelled token counts** (ADR-0019) — `exact` / `approximate` / `estimated`, with `tiktoken`
  as an optional extra. Nothing downstream can treat an estimate as a measurement.
- `needle-in-a-big-file` eval task, and `--no-budget` / `--only` on `tapeloop eval`.
- [`docs/evals/m7-delta.md`](docs/evals/m7-delta.md) — the measured comparison, including why the
  judged score's apparent improvement is judge noise and not a result.

### Added
- **First baseline** — `evals/baseline-2026-08-24/`, committed with the dated model id that
  produced it. Deterministic 0.911 ± 0.268 over 18 tasks; judged 0.867 ± 0.231 over 3.
- **`results.json`** alongside `results.md` — every judgment verbatim, per attempt. The markdown
  is what a reader looks at; the JSON is what someone checks when they doubt a row. This closes a
  gap where ADR-0018 required recorded judgments and the implementation recorded none.
- **Five harder tasks.** The first baseline scored 13/13 with zero spread — a suite that cannot
  detect a regression. Added a decoy file, a three-file rename, a count with exclusions whose
  naive answer is wrong, an edit that must preserve its surroundings, and a request that cannot
  be satisfied.

### Fixed
- The CLI never loaded `.env` — the same bug M0 had, repeated in the library. Fixed in
  `cli.main()` rather than the library, since a library that mutates `os.environ` on import
  surprises its host. `--model` now also defaults from `TAPELOOP_MODEL`.
- The `summarise-data` rubric demanded detail the prompt never asked for, so the judge failed
  correct answers and disagreed with itself doing it. Grades only what was requested now.

### Added
- **Eval harness** — `Task`/`Suite`, a runner with per-seed fresh workspaces, and a report that
  carries **mean ± spread**. A single run is not a result.
- **13 hand-written, held-out tasks** (`starter-v1`), plus 3 judged ones. Graded on the workspace
  rather than the agent's account of itself, and including two **refusal tasks** where success
  means declining.
- **`LlmJudge`** under ADR-0018: model pinned and recorded, judged `k` times with **agreement**
  reported, unparseable verdicts treated as FAIL, and judged results never blended into the
  deterministic headline.
- **`PythonBehaviour`** grader — runs the code instead of grepping it.
- **`tapeloop eval`**, and `docs/evals/{methodology,failure-taxonomy}.md`.
- **`test_no_task_is_passable_by_doing_nothing`** — the suite runs against a do-nothing model in
  CI, because a grader such a model can pass is a grader that tests nothing.

### Fixed
- `fix-the-bug` asserted that `calc.py` still contained `def average`, which its own setup
  guaranteed — so an agent doing nothing scored 1.0. Caught by the machinery check on its first
  run; it now executes the code and asserts `average([]) == 0`.

### Security
- **Permission model** (ADR-0017) — `allow` / `ask` / `deny`, per tool *and per argument*, with
  defaults derived from effect classes. Rules live in `.tapeloop/permissions.toml` so they can be
  reviewed in a pull request. Decisions are recorded on the tape, so replay never re-prompts and
  an eval is never interactive.
- An **unattended run refuses** rather than assuming approval: no prompter means deny.
- **`DockerExecutor`** behind the M1 `Executor` seam — no network, all capabilities dropped, no
  new privileges, read-only root, workspace as the sole writable mount, `noexec` tmp. Raises if
  Docker is absent rather than degrading silently.
- **`SnapshotStore`** — workspace copies per step, which is what makes `resume` distinct from
  `replay` (ADR-0006) and what will upgrade a `simulated` fork to `faithful` (ADR-0016).
- **`SECURITY.md`** and **`docs/explanation/threat-model.md`**, both stating plainly what is *not*
  claimed — notably that prompt injection is not detected, only made insufficient.

### Added
- **`replay/`** — `Recording` reads a tape back (it is self-describing, so no configuration is
  needed beyond a path), `plan_fork` branches at a step, `diff_tapes` compares two runs anchored
  on step keys.
- **Fork soundness** (ADR-0016) — a fork classifies itself `faithful` or `simulated` from the
  effect classes in the prefix it replayed, names the specific writes, and records the tier on
  the new tape. `--require-faithful` turns `simulated` into a refusal.
- **CLI** — `tapeloop run | show | fork | diff`, built on stdlib `argparse` rather than a CLI
  framework, keeping the dependency list at two.
- `message` records on the tape, so history is reconstructable. Previously `tool_result` records
  carried only the tool name and effect, not the content, which fork needs.

### Added
- **The tape** (`record/jsonl.py`) — append-only JSONL behind the existing `TranscriptStore`
  seam, with a versioned header. An unknown format version refuses to open rather than
  best-effort parsing.
- **Canonical serialization** (`record/canonical.py`) — sorted keys, compact separators, NFC
  normalization, NaN/Infinity rejected. Non-ASCII stays literal so tapes remain greppable.
- **Content-addressed step keys** (`record/keys.py`) with the prefix property: change a prompt
  and only the steps after it miss.
- **Step cache** (`record/cache.py`) — a previous run indexed by key, with hit-rate stats.
  `Agent` consults it before spending anything.
- **`docs/reference/transcript-format.md`** — the normative spec, written before the code.
- **Determinism lint** — an AST scan of `src/` for wall-clock reads and unseeded randomness,
  run as a test so Contract 1 is enforced by CI rather than by discipline.
- ADR-0014 (tool results ordered by their calls), ADR-0015 (tapes contain no timestamps).

### Added
- **Streaming** (`providers/stream.py`) — `TextDelta`, `ToolCallDelta`, `StreamEnd`, and a
  `ToolCallAccumulator` that reassembles tool arguments arriving as JSON fragments split at
  arbitrary points across chunks and interleaved by call index.
- **`ModelClient.stream()`** on the Protocol and the OpenAI adapter. The Anthropic
  signatures-only adapter was extended to match, which is the design check doing its job.
- **Typed error taxonomy** (`core/errors.py`) — retryable (`RateLimited`, `ProviderUnavailable`)
  versus terminal (`RequestInvalid`, `AuthenticationFailed`), plus `Cancelled` and
  `BudgetExceeded`. SDK exceptions are mapped by `providers.openai.translate`.
- **Retry policy** (`core/retry.py`) — exponential backoff with *seeded* jitter, honouring
  `Retry-After`, sleeping on the cancellation token so an interrupt is felt immediately.
- **Cooperative cancellation** (`core/cancel.py`) — `CancellationToken` plus an `on_sigint`
  context manager. A second Ctrl-C restores the default handler and re-raises.
- **`docs/project/`** — cold-start handoff: charter, current state, glossary, resume prompt.
- ADR-0013: hand-rolled schema generation instead of pydantic.

### Changed
- The loop discards an in-flight turn entirely on cancellation and records a `cancelled` event.
  A partial assistant message is never written — it would replay as speech the model never made.
- A stream failure after the first delta is re-raised as non-retryable: restarting would re-emit
  text the user has already seen.
- Vendor extensions from a provider are captured generically via `model_extra` as opaque
  payloads, rather than naming individual fields.

### Security
- A real OpenAI key had been pasted into the committed `.env.example` and reached six commits.
  History was rewritten to purge it, verified against a fresh clone. The key had already been
  rotated. A tracked `.githooks/pre-commit` guard now blocks key-shaped strings from being staged,
  and `core.hooksPath` points at it.

### Fixed
- `get_type_hints` could not resolve types declared inside a factory function — the normal case
  for tool packs. The registry now passes the calling frame's locals as `localns`.
- The docstring parser leaked the `Returns:` section into a tool's description.
- `.env` was never loaded, and settings were read at import time before `load_dotenv()` ran —
  a configured model would have been silently ignored in favour of the default.
- Tests read the developer's real `.env` because `find_dotenv()` searches from the calling
  module's directory rather than the cwd.
