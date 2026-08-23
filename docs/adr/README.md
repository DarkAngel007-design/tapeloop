# Architecture Decision Records

Numbered, dated, **immutable**. A decision that changes gets a *new* ADR marking the old one
superseded — never an edit to the original. The record of what we believed and why is worth more
than a tidy list.

Format: Context (the forces) → Decision (what we chose) → Consequences (what it costs).

| # | Decision | Status |
|---|----------|--------|
| [0001](0001-provider-neutral-core.md) | Provider-neutral core; OpenAI-compatible adapter first | Accepted |
| [0002](0002-modelclient-conformance-suite.md) | A conformance suite defines what a ModelClient is | Accepted |
| [0003](0003-jsonl-source-of-truth.md) | JSONL as the source of truth, SQLite as an index | Accepted |
| [0004](0004-step-key-contents.md) | What goes into a step key | Accepted |
| [0005](0005-three-effect-classes.md) | Three effect classes, defaulting to `write` | Accepted |
| [0006](0006-replay-is-not-resume.md) | Replay and resume are separate operations | Accepted |
| [0007](0007-sandbox-escalation-order.md) | Sandbox backend escalation order | Accepted |
| [0008](0008-exact-string-edit-tool.md) | Exact-string replacement for the edit tool | Accepted |
| [0009](0009-apache-over-mit.md) | Apache-2.0 over MIT | Accepted |
| [0010](0010-transcript-versioning.md) | Transcript schema versioning and migration policy | Accepted |
| [0011](0011-canonical-event-log.md) | Canonical event log, with opaque provider payloads | Accepted |
| [0012](0012-chat-completions-over-responses.md) | Chat Completions over the Responses API | Accepted |
| [0013](0013-hand-rolled-schema-generation.md) | Hand-rolled schema generation instead of pydantic | Accepted |
| [0014](0014-tool-result-ordering.md) | Tool results are ordered by their calls, not by arrival | Accepted |
| [0015](0015-tapes-contain-no-timestamps.md) | The tape contains no timestamps | Accepted |
| [0016](0016-fork-declares-its-own-soundness.md) | Fork declares its own soundness from the effects it replayed | Accepted |
| [0017](0017-permission-model.md) | Permission decisions are events on the tape | Accepted |
| [0018](0018-pinned-judge.md) | LLM-as-judge, pinned and measured | Accepted |
