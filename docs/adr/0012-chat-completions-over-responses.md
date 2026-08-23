# ADR-0012 — Chat Completions over the Responses API

**Status:** Accepted · 2026-08-23

## Context

OpenAI offers two surfaces. The Responses API is newer, stateful, and carries reasoning items
across turns. Chat Completions is older, stateless, and is the shape every OpenAI-compatible
server implements.

## Decision

Target **Chat Completions**.

Two reasons. First, tapeloop keeps conversation state in the tape — that is the entire project. A
server-side stateful conversation would be a second source of truth competing with it, and the
first time they disagreed, replay would be wrong. Second, Chat Completions is the lingua franca:
one adapter reaches Groq, Together, OpenRouter, vLLM and Ollama, so contributors can develop
against a local model for free.

## Consequences

- **Cost, stated plainly:** Chat Completions does not return reasoning items, so runs on reasoning
  models carry less across turns than they could. For a runtime whose job is faithful recording,
  losing something the provider will not give us is acceptable; pretending we recorded it is not.
- Revisit if the reasoning gap measurably hurts eval scores at M6. That would be a new ADR
  superseding this one, not an edit here.
- The opaque-payload mechanism in [ADR-0011](0011-canonical-event-log.md) already accommodates
  reasoning items, so a Responses adapter is additive rather than a redesign.
