# Roadmap

Ten milestones. Each has a **ship criterion** that is an observable fact, not a feeling.
Nothing advances until its criterion holds.

Legend: `[ ]` not started · `[~]` in progress · `[x]` done

---

- [x] **M0 — Bare loop**
      Raw SDK, three hand-written schemas, one file, no abstractions. Deliberately ugly.
      **Ship when:** <150 lines, completes a two-tool task, no framework.
      *Shipped 2026-08-23: 137 code lines · no framework · two-tool task verified against a
      fake client and against a live model.*

- [x] **M1 — Tool registry, effect classes, four seams**
      Schema generation from typed signatures, emitting the strictest schema every target
      provider accepts. Effect declaration on every tool. The four Protocols, with the OpenAI
      adapter implemented and the Anthropic adapter as *type signatures only* — a design check
      that costs nothing and catches a provider-shaped abstraction immediately.
      **Ship when:** adding a tool is one decorated function; zero hand-written JSON Schema;
      the unimplemented Anthropic adapter type-checks.
      *Shipped 2026-08-23: all three verified. 27 tests, zero API spend. pyright strict clean.*

- [x] **M2 — Streaming, interrupts, retries**
      Token-by-token render, partial-JSON accumulation for tool arguments, clean mid-stream
      cancellation, typed error chain with backoff.
      **Ship when:** survives a forced 429 and a mid-stream Ctrl-C without corrupting the tape.
      *Shipped 2026-08-23: `test_the_ship_criterion` does exactly that. 44 tests, zero API
      spend, pyright strict clean.*

- [x] **M3 — The tape** ◆
      Append-only JSONL with a versioned schema. Canonical serialization. Content-addressed
      step keys. The determinism lint rule and the replay-equivalence test.
      **Ship when:** re-running an unchanged agent is a 100% cache hit, byte-identical.
      *Shipped 2026-08-23: `test_ship_criterion_replay_is_a_total_cache_hit_and_byte_identical`
      asserts hit_rate == 1.0 and `first.read_bytes() == second.read_bytes()`. 64 tests.*

- [ ] **M4 — Replay, fork, diff** ◆
      The differentiator. This demo goes at the top of the README as an asciinema recording.
      **Ship when:** editing the system prompt and forking at step 12 replays 0–11 in <1s.

- [ ] **M5 — Sandbox, permissions, resume**
      Docker executor, permission rules per tool and argument, workspace snapshotting — which
      is what makes `resume` possible as distinct from `replay`.
      **Ship when:** a repo file that tries to instruct the agent is refused, and it's a test.

- [ ] **M6 — Eval harness & first numbers**
      ~30 domain-neutral tasks, deterministic graders, 5 seeds each. Fork makes this cheap.
      **Ship when:** a committed results table with mean ± spread, and a baseline to regress against.

- [ ] **M7 — Context management**
      Per-step token accounting, tool-result truncation budgets, compaction near the ceiling.
      **Ship when:** a task that previously died on context completes, with the eval delta measured.

- [ ] **M8 — Subagents & MCP, both ends**
      **Ship when:** the server runs in a different MCP host; orchestration delta measured
      in either direction.

- [ ] **M9 — Viewer, deploy, observability**
      **Ship when:** someone who is not the author runs a task and their trace is viewable.

---

**Not a milestone:** the Anthropic adapter. It lands whenever credits allow. The day it passes
the conformance suite *unmodified* is the day the provider abstraction is proven.
