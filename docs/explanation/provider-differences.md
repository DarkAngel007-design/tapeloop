# Provider differences

This table is the specification for the `ModelClient` conformance suite
([ADR-0002](../adr/0002-modelclient-conformance-suite.md)). **If a divergence is not written here,
the seam does not handle it.** Add the row before you add the adapter.

Status legend: ✅ handled · 🚧 planned · ❔ unverified

| # | Divergence | OpenAI (Chat Completions) | Anthropic (Messages) | Status |
|---|-----------|---------------------------|----------------------|--------|
| 1 | Assistant tool calls | `tool_calls` array on the message | `tool_use` content blocks | 🚧 |
| 2 | **Tool results** | one `role:"tool"` message per call, each with `tool_call_id` | **all results in a single `user` message**, as `tool_result` blocks | 🚧 |
| 3 | Stop signal | `finish_reason`: `stop`, `tool_calls`, `length`, `content_filter` | `stop_reason`: `end_turn`, `tool_use`, `max_tokens`, `refusal`, `pause_turn` | 🚧 |
| 4 | Token counting | local, `tiktoken` | server endpoint, `count_tokens` | 🚧 |
| 5 | Prompt caching | automatic prefix cache, no control; reported in usage | explicit `cache_control` breakpoints | 🚧 |
| 6 | Reasoning | not returned by Chat Completions; opaque items on Responses | `thinking` blocks, must be replayed verbatim | 🚧 |
| 7 | Strict schemas | strict mode requires every field required + `additionalProperties: false` | more permissive | 🚧 |

## Notes on the sharp ones

**#2 — tool-result grouping** is the trap. Anthropic requires every parallel tool result in one
user message; splitting them teaches the model to stop calling tools in parallel, and nothing
errors. The canonical event model stores results as a *set belonging to one step*, and each
adapter renders that set to its provider's shape. Neither provider's layout leaks into the tape.

**#6 — reasoning** is why opaque payloads exist
([ADR-0011](../adr/0011-canonical-event-log.md)). tapeloop stores whatever the provider returns,
tagged with its origin, and hands it back untouched. It never tries to interpret it, and it drops
it — visibly — when forking to a different provider.

**#7 — strict schemas** means the tool registry must emit the *strictest common denominator*, so
one schema ports everywhere. That constraint is easier to hold from the start than to retrofit.

## Free ways to stress the seam

An **Ollama** adapter speaks the same wire format as OpenAI but behaves very differently — often
no parallel tool calls, different failure modes, no caching. It costs nothing to run and will find
seam bugs long before the Anthropic adapter does.
