# Architecture

## The loop is not the hard part

A complete agent runtime is about twelve lines:

```py
while True:
    response = client.complete(messages=messages, tools=tools)
    messages.append(response.message)
    if response.stop_reason is not StopReason.TOOL_USE:
        break
    messages.append(results(*[dispatch(c) for c in response.message.tool_calls]))
```

You can write that in an afternoon. What you cannot write in an afternoon is the thing
that stops it burning a context window on one file read, editing a file it never read,
looping between two tools forever, running `rm -rf` because a README told it to, or
dying on a rate limit halfway through a forty-minute task.

`m0/loop.py` in the repository is that twelve-line version, kept deliberately
unabstracted. When you want to know what the runtime is actually doing underneath,
read it — the diff against the real one is the design.

## Five contracts

Everything else serves these.

**1. Determinism up to first divergence.** Same tape plus same code reproduces a run
exactly, until something changes, then runs live from there. Enforced by a lint rule
and a replay-equivalence test rather than by discipline.

**2. Content-addressed step keys.** A step is keyed by provider, model, params, tool
schemas and the canonical event prefix. Change anything and every step from that index
onward misses; every step before it hits. That prefix property is why forking is cheap.

**3. Tools declare their effects.** `pure` / `read` / `write`, undeclared meaning
`write`. Replay is only sound if the runtime knows which tools touch the world.

**4. Replay is not resume.** Replay is a cached *simulation*; resume restores nothing
and re-executes for real. Two commands, two guarantees, two documentation pages.

**5. The tape is provider-neutral.** Canonical events, with anything the runtime cannot
interpret stored as an opaque payload and handed back verbatim. This is what makes
forking a run onto a different model possible at all.

## Four seams

Each is a Protocol with one implementation to start. They were defined before there was
anything to swap, and every one has since paid for itself:

| Seam | First implementation | What it absorbed later |
|---|---|---|
| `ModelClient` | OpenAI Chat Completions | Streaming, the conformance suite, a second provider |
| `Executor` | `SubprocessExecutor` | `DockerExecutor` arrived as a class, not a rewrite |
| `TranscriptStore` | in-memory | The JSONL tape swapped in without touching the loop |
| `Grader` | exact match | LLM-as-judge is a grader, not a special case |

## Package layout

```
tapeloop/
├── core/        loop, budget, cancellation, retry policy, errors
├── events.py    the canonical vocabulary everything speaks
├── tools/       registry, schema generation, effect classes, builtin pack
├── record/      canonical serialization, step keys, the tape, the cache
├── replay/      recording reader, fork, diff, resume
├── context/     token accounting, truncation, compaction
├── sandbox/     executors, permissions, snapshots
├── agents/      subagents, pipeline vs barrier
├── mcp/         client and server
├── eval/        tasks, graders, runner, report
├── observe/     cost, traces, the viewer
└── testing.py   ScriptedClient, for anyone building on this
```

## What a run leaves behind

One append-only JSONL tape: a header, then `run_start`, `message`, `step`,
`tool_result`, `permission`, `truncated`, `compaction`, `snapshot`, and `run_end`
records. A subagent writes its own tape and the parent records a `subagent` link — a
trace is a **tree of tapes**, not a nested document, which is why the viewer renders a
child with the same code as its parent.

No timestamps anywhere. Time comes from the filesystem, so two identical runs produce
identical files and `cmp` is a meaningful test.

## Further

- [Replay is not resume](replay-vs-resume.md)
- [Determinism](determinism.md)
- [Why not a framework](why-not-a-framework.md)
- [Decisions](../adr/README.md) — 21 ADRs, numbered and immutable
