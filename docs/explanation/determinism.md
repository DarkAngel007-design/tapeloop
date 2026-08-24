# Determinism

Every property tapeloop sells rests on one thing: two identical runs producing
identical bytes. That makes serialization load-bearing in a way it usually is not, and
the failure mode is nasty — a false cache miss looks exactly like "replay is broken",
with nothing to point at.

## What is hashed

```
key(n) = sha256(canonical_json({
    provider, model, params, tool_schemas, events[0..n]
}))
```

Explicitly **excluded**: timestamps, run ids, machine identity, tool execution order,
latency — anything that would make a byte-identical re-run miss.

Provider and model are *inside* the key deliberately. Cross-provider replay is a miss
by arithmetic, not a limitation: a different model is a different run. The useful
cross-provider operation is `fork`.

## Four hazards in serialization

Each is handled explicitly, and each would silently break replay:

**Key order.** Dict insertion order is not semantic, so keys are sorted.

**Incidental whitespace.** Compact separators, because a space is a difference that
means nothing.

**Unicode.** `é` is one code point or two. Same string to a human, different bytes to
sha256. Everything is NFC-normalized before hashing — without it, a model emitting one
form and a tape holding the other never agree.

**NaN and Infinity.** Not valid JSON. Python emits them anyway by default, producing a
file no other parser will read. They are rejected.

## No timestamps, anywhere

The obvious approach is to record time and exclude it from the hash. That sounds fine
and is a trap: it creates two notions of "the same tape" — really the same, and the
same-except-the-bits-we-agreed-to-ignore — and every later feature has to remember
which one it wants. The first that forgets gives a silently wrong answer.

So a tape holds no wall-clock values at all. When a run happened is the file's mtime.

## Enforced, not intended

A test walks the AST of `src/` looking for wall-clock reads and unseeded randomness.
`random.Random(seed)` is fine — it is an instance, not the global stream — and
`time.sleep` is fine because it reads no clock.

```bash
uv run pytest -k determinism_lint
```

The one deliberate exception is retry jitter, and the reason it is safe is specific:
retry timing is transport-level. It never reaches a prompt, never reaches a step key,
and never appears on the tape. The policy still owns a seeded RNG rather than the
global one, so two identical processes back off identically.

## Compaction

Summarising is a model call, so it is nondeterministic. Done as a side effect it would
produce a different summary on every replay and every key after it would diverge —
Contract 1 failing silently. So compaction is a **step**: keyed, cached, and written to
the tape like any other.

Truncation deliberately is not. It is a pure function of its input, so it happens
inline and needs no record beyond the elision marker the model can already see.

## The observer effect

**Never write a tape inside the workspace the agent can see.** The tape becomes
something the agent observes: a directory listing on the second run includes the first
run's file, the tool result differs, the step key diverges, and replay misses for no
visible reason.

Recording must not change what is recorded. This is pinned by a test that asserts the
effect still exists, so if it ever stops being true the warning can go too.
