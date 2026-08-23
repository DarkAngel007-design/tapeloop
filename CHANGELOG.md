# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning is [semver](https://semver.org/); pre-1.0 means anything may move.

## [Unreleased]

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
