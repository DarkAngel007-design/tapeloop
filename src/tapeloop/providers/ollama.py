"""Ollama: the same wire format, meaningfully different behaviour.

Ollama serves an OpenAI-compatible `/v1` endpoint, so this is a thin thing — and that
thinness is the point. It was built as a **free stress test of the provider seam**: an
adapter that reaches the same code by a different route, available to anyone with a
laptop, without waiting for a second vendor's credentials.

It earned that immediately. Wiring it up exposed that `provider_id` was hardcoded to
`"openai"` no matter where the client pointed, so a run against a local model produced
the same step key as one against a model of that name at OpenAI — a false cache hit
returning an answer that was never given. See `provider_id_for`.

**What differs from OpenAI in practice**, all of it handled by the shared adapter
rather than by special cases here:

- **No prompt caching.** `usage.prompt_tokens_details` is absent, so cached input reads
  as zero. That is honest rather than missing: there is nothing being cached.
- **Parallel tool calls are model-dependent** and many local models never emit them.
  Nothing breaks; the loop simply sees one call per step.
- **Tool support is model-dependent** entirely. A model without it ignores the `tools`
  parameter and answers in prose, which surfaces as a run that never calls anything.
- **A 500 can mean something permanent.** Ollama returns HTTP 500 for "model requires
  19.7 GiB but only 17.3 GiB are available", which will never succeed however long you
  wait. `translate` maps 5xx to `ProviderUnavailable`, which is retryable — so the
  policy will back off and try again several times before giving up. That is the right
  general default and deliberately not special-cased: a heuristic scanning error text
  for "GiB" would be brittle and provider-specific, and the cost of getting it wrong in
  the other direction — treating a transient outage as permanent — is worse. The retry
  count is bounded and the message is clear.
- **Model names carry a tag** — `qwen3:8b`, `llama3.2:3b-instruct-q4_K_M`. They are
  opaque strings to the runtime, but they *are* part of the step key, so a re-pull that
  changes the tag correctly invalidates the cache.
"""

from __future__ import annotations

from openai import OpenAI

from tapeloop.providers.openai import OpenAIClient

PROVIDER_ID = "ollama"
DEFAULT_BASE_URL = "http://localhost:11434/v1"


class OllamaClient(OpenAIClient):
    """An OpenAIClient pointed at a local Ollama, with an identity of its own.

    The identity is the whole reason this class exists rather than a documentation note
    saying "set OPENAI_BASE_URL". `provider_id` is hashed into every step key, so
    getting it wrong does not fail loudly — it silently serves one backend's answers
    for another's question.
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = "ollama",  # required by the SDK, ignored by the server
        client: OpenAI | None = None,
    ) -> None:
        super().__init__(
            client or OpenAI(base_url=base_url, api_key=api_key),
            provider_id=PROVIDER_ID,
        )

    def available(self) -> bool:
        """Whether a daemon is actually answering. Cheap; no model is loaded."""
        try:
            self._client.models.list()
        except Exception:
            return False
        return True

    def models(self) -> list[str]:
        """What this daemon has pulled. Useful because the tag is part of the step key."""
        try:
            return sorted(m.id for m in self._client.models.list().data)
        except Exception:
            return []
