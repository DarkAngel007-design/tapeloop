# ADR-0001 — Provider-neutral core; OpenAI-compatible adapter first

**Status:** Accepted · 2026-08-23

## Context

The original plan was "Claude-first, with a `ModelClient` seam for later." That is a comfortable
fiction: a provider abstraction validated against exactly one provider is that provider's API
wearing a hat. The seam only becomes real when a second, differently-shaped provider goes through it.

Separately, the author has OpenAI credits and no Anthropic credits today.

## Decision

The core is provider-neutral by construction. The first adapter targets the **OpenAI Chat
Completions shape**; the Anthropic adapter follows when credits allow.

Chat Completions is not just OpenAI — it is the de facto interchange format spoken by Groq,
Together, OpenRouter, vLLM and Ollama. One adapter reaches all of them, which means anyone can
run tapeloop against a local model with no API credits at all. For an open-source runtime, that
on-ramp is worth more than starting with the "nicer" API.

## Consequences

- The `ModelClient` Protocol must be designed against real divergence, not imagined divergence.
  See [ADR-0002](0002-modelclient-conformance-suite.md).
- Roughly one extra week of work at M1.
- Risk: an abstraction designed against one provider ends up shaped like it. Mitigated by writing
  the Anthropic adapter's *type signatures* at M1 — it will not run, but it type-checks, and a
  provider-shaped interface fails that check immediately for zero API spend.
- The Anthropic adapter is deliberately **not a milestone**. The day it passes the conformance
  suite unmodified is the day this abstraction is proven.
