# Charter

The builder-facing counterpart to `README.md`. The README sells the idea; this states the
commitments.

## Problem

Iterating on an agent means changing one line of a prompt, re-running the entire task, waiting
minutes, and paying real money — every time. The feedback loop is so expensive that people run
the experiment they can afford rather than the one they need.

Every other kind of software solved this with a debugger: breakpoints, stepping, replay. Agents
do not have one.

## What we are building

A Python agent runtime that records every step to an append-only **tape**, so a run can be
replayed deterministically, forked at any step, and diffed against a variant.

## Who it is for

Developers building agents in Python, on any OpenAI-compatible endpoint — which includes
running entirely locally against Ollama or vLLM, with no API credits at all. That on-ramp is a
requirement, not a nice-to-have: a runtime nobody can try is a runtime nobody adopts.

## The five contracts

Non-negotiable. Everything in the codebase serves these. Reasoning is in the ADRs.

1. **Determinism up to first divergence** — same tape + same code reproduces exactly, until
   something changes; live from there. (ADR-0004)
2. **Content-addressed step keys** — provider, model, params, tool schemas, canonical event
   prefix. (ADR-0004)
3. **Tools declare their effects** — `pure` / `read` / `write`, undeclared defaults to `write`.
   (ADR-0005)
4. **Replay is not resume** — replay is a cached simulation; resume restores a snapshot and
   re-executes for real. (ADR-0006)
5. **The tape is provider-neutral** — canonical events, with anything uninterpretable stored as
   an opaque payload and handed back verbatim. (ADR-0011)

## Success criteria

This project is finished — as a piece of work, not as software — when all of these hold:

- [ ] Editing a system prompt and forking at step 12 replays steps 0–11 in under a second.
- [ ] A run recorded on one provider can be forked onto another with identical history.
- [ ] A committed eval table with **mean ± spread across seeds**, not a single lucky run.
- [ ] A written failure taxonomy: named modes, measured frequencies, what changed for each.
- [ ] The Anthropic adapter passes the conformance suite **unmodified** — the proof that the
      provider abstraction was designed rather than transcribed.
- [ ] Someone who is not the author runs a task, and their trace is viewable.

## Explicitly out of scope

Stated so they do not get relitigated:

- **Not an agent framework.** No chains, no retriever abstractions, no prompt-template DSL. If
  it can be a plain function, it stays a plain function.
- **Not a hosted service.** You run it. The viewer is a local process.
- **Not a prompt-management product.** Prompts live in git.
- **Not multi-provider breadth.** Only adapters exercised by the conformance suite ship.
- **Not dependency-maximal.** A short dependency list is a stated feature, enforced in review.

## Constraints

- Python ≥ 3.11. Apache-2.0.
- Built part-time alongside an unrelated research project — milestones are sequential and
  each must be independently shippable.
- Developed against OpenAI credits; Anthropic credits arrive later. This is why the provider
  abstraction is real from day one rather than aspirational (ADR-0001).
