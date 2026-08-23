# tapeloop

**An agent runtime that records every step, so any run can be replayed, forked, and diffed.**

> ⚠️ **Status: pre-alpha, M2 of M9.** Built so far: the agent loop, a tool registry, four
> swappable seams, streaming, cancellation and retries. **The tape itself does not exist yet** —
> the `replay` / `fork` / `diff` commands below describe the design, not shipped behaviour.
> They land at M3–M4. There is no public API and no CLI yet.
> See [ROADMAP.md](ROADMAP.md) for what is built and what isn't.

---

## The problem

Building an agent today means iterating like this:

> change one line of the system prompt → re-run the whole task → wait four minutes →
> spend eighty cents → squint at the output → repeat

The feedback loop is measured in minutes and dollars, so most people run the experiment they
can afford rather than the one they need. Every other part of software solved this with a
debugger — breakpoints, stepping, replay. Agents don't have one.

## The idea

tapeloop writes every step of a run to an append-only **tape**. Because the tape is a complete,
provider-neutral record, you can:

```bash
tapeloop run "refactor the auth module"      # records as you go
tapeloop replay run_8f2                      # deterministic, from cache
tapeloop fork   run_8f2 --at 12              # branch at step 12, edit, continue
tapeloop diff   run_8f2 run_a41              # what actually changed
```

Editing your prompt and forking at step 12 replays steps 0–11 from the tape in milliseconds.
Only step 12 onward costs anything.

Because the tape stores canonical events rather than one vendor's wire format, you can also
branch a run **onto a different model**:

```bash
tapeloop fork run_8f2 --at 12 --model claude-opus-5
```

Same history, different model, from the exact step where it went wrong. That is the comparison
you actually want when choosing a model, and it is normally impossible because your history is
locked inside one provider's message format.

## Design

Five contracts hold the whole thing up:

1. **Determinism up to first divergence** — same tape + same code reproduces the run exactly,
   until something changes, then runs live from there.
2. **Content-addressed step keys** — a step is keyed by provider, model, params, tool schemas
   and the canonical event prefix. Change anything, and only that step onward misses.
3. **Tools declare their effects** — `pure` / `read` / `write`. Undeclared defaults to `write`,
   the most conservative class.
4. **Replay is not resume** — replay is a cached *simulation*; resume restores a workspace
   snapshot and re-executes for real. Two commands, two guarantees.
5. **The tape is provider-neutral** — canonical events, with anything the runtime can't
   interpret stored as an opaque payload and handed back verbatim.

Full reasoning lives in [`docs/adr/`](docs/adr/).

## Non-goals

Not an agent framework — no chains, no retriever abstractions, no prompt-template DSL. Not a
hosted service. Not a prompt-management product. A short dependency list is a stated feature.

## Running M0

M0 is a single unabstracted file. It exists so the protocol is visible before anything hides it.

```bash
uv sync
cp .env.example .env    # add your key
uv run python m0/loop.py "count the python files here and write the number to count.txt"
```

Works against any OpenAI-compatible endpoint — OpenAI, Groq, Together, OpenRouter, vLLM, or a
local Ollama. Set `OPENAI_BASE_URL` to point elsewhere.

## License

Apache-2.0.
