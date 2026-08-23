# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning is [semver](https://semver.org/); pre-1.0 means anything may move.

## [Unreleased]

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

### Fixed
- `get_type_hints` could not resolve types declared inside a factory function — the normal case
  for tool packs. The registry now passes the calling frame's locals as `localns`.
- The docstring parser leaked the `Returns:` section into a tool's description.
- `.env` was never loaded, and settings were read at import time before `load_dotenv()` ran —
  a configured model would have been silently ignored in favour of the default.
- Tests read the developer's real `.env` because `find_dotenv()` searches from the calling
  module's directory rather than the cwd.
