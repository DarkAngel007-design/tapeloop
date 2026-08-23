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

- [x] **M4 — Replay, fork, diff** ◆
      The differentiator. This demo goes at the top of the README as an asciinema recording.
      **Ship when:** editing the system prompt and forking at step 12 replays 0–11 in <1s.
      *Shipped 2026-08-24: `test_ship_criterion_fork_at_step_12_replays_the_prefix_in_under_a_second`.
      Plus a zero-dependency CLI (`run` / `show` / `fork` / `diff`) and ADR-0016. 72 tests.*

- [x] **M5 — Sandbox, permissions, resume**
      Docker executor, permission rules per tool and argument, workspace snapshotting — which
      is what makes `resume` possible as distinct from `replay`.
      **Ship when:** a repo file that tries to instruct the agent is refused, and it's a test.
      *Shipped 2026-08-24: `test_ship_criterion_a_hostile_file_cannot_make_the_agent_act`.
      Plus ADR-0017, SECURITY.md, and a stated threat model. 88 tests.*

- [x] **M6 — Eval harness & first numbers**
      ~30 domain-neutral tasks, deterministic graders, 5 seeds each. Fork makes this cheap.
      **Ship when:** a committed results table with mean ± spread, and a baseline to regress against.
      *Shipped 2026-08-24. Baseline: `gpt-5.4-mini-2026-03-17`, 21 tasks x 5 seeds, deterministic
      0.911 ± 0.268 and judged 0.867 ± 0.231, committed at `evals/baseline-2026-08-24/`.
      The first run scored 13/13 ± 0.00 — no discriminating power — so five harder tasks were
      added before freezing a baseline. Failure taxonomy filled in from real tapes; F11 and F12
      are new modes found by this run.*

- [x] **M7 — Context management**
      Per-step token accounting, tool-result truncation budgets, compaction near the ceiling.
      **Ship when:** a task that previously died on context completes, with the eval delta measured.
      *Shipped 2026-08-24. `test_ship_criterion_a_task_that_died_on_context_now_completes` proves
      the death case deterministically. Real-world delta measured in
      [`docs/evals/m7-delta.md`](docs/evals/m7-delta.md): identical accuracy on all 18 shared
      tasks, and 289,056 → 12,615 input tokens on the context-pressure task (−95.6%).
      ADR-0019 (token counts are labelled) and ADR-0020 (compaction is a recorded step).*

- [x] **M8 — Subagents & MCP, both ends**
      **Ship when:** the server runs in a different MCP host; orchestration delta measured
      in either direction.
      *Shipped 2026-08-24. The MCP server is driven by raw JSON-RPC over a subprocess pipe with
      no tapeloop code on the sending side — a conformance check, not a round-trip. Subagents get
      their own tape (ADR-0021). Orchestration delta in
      [`docs/evals/m8-orchestration.md`](docs/evals/m8-orchestration.md): 60% saved on one
      workload, 0% on another, and the eval suite has no fan-out task so its delta is
      deliberately not claimed. 125 tests.*

- [ ] **M9 — Viewer & observability** *(scope reduced 2026-08-24 — see below)*
      Containerise, OpenTelemetry spans carrying per-step tokens and dollars, and a local web
      trace viewer. Nested runs from M8 render as a tree, not a list.
      **Ship when:** someone who is not the author runs a task and can open their trace, with
      per-step cost visible.

      **Cut from the original scope:** worker pool, queue, autoscaling, per-user quotas.
      The charter already says this is not a hosted service, so a queue would exist only to let
      the README say "production grade". That third of M9 is the least distinctive work in the
      project and the most time-consuming, and a reader stops on the eval table and a trace
      screenshot long before they check for a worker pool. Recorded here rather than quietly
      under-delivered against the wider criterion.

---

**Not a milestone:** the Anthropic adapter. It lands whenever credits allow. The day it passes
the conformance suite *unmodified* is the day the provider abstraction is proven.

**Why the order is what it is.** M7 and M8 both change what a trace *contains* — M7 adds
compaction and truncation records, M8 turns a run from a list into a tree of child runs. A viewer
built before either would be built twice, for the same reason the sandbox waited for the replay
contract in M5. The only part of M9 that legitimately moves earlier is the token and cost
accounting, and it moves because **M7 needs it**, not because M9 does.

**Carried debt:** `SnapshotStore` (M5) is built and tested but nothing calls it. Wiring it into
`resume` and into fork's `faithful` upgrade (ADR-0016) belongs alongside M7.
