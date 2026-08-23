# Transcript format

**Format version: 1** · Normative. Changing anything here requires a new ADR and a migration
(ADR-0010).

This document is a **compatibility promise**. The moment anyone has a saved tape, a tape written
in January must still replay in December.

## Shape

A tape is a UTF-8 text file of newline-delimited JSON. Line 1 is the header; every subsequent
line is a record. Records are append-only: a correction is a new record, never an edit.

```jsonl
{"kind":"header","tapeloop":"0.0.0","v":1}
{"data":{"model":"gpt-4o-mini","provider":"openai","tools":["read_file"]},"kind":"run_start","seq":0,"step":0}
{"data":{"role":"user","text":"count the files"},"kind":"message","seq":1,"step":0}
{"data":{...},"key":"5f2c…","kind":"step","seq":2,"step":0}
```

The header carries no timestamp, run id, or machine identity, and neither does any record. Time
is filesystem metadata: a run's identity is its filename, and when it happened is its mtime
(ADR-0015). This is what makes byte-identity a checkable property rather than one with an
exclusion list.

## Where a tape must not live

**A tape must not be written inside the workspace the agent can see.** If it is, the tape becomes
part of what the agent observes: a directory listing on the second run includes the first run's
file, the tool result differs, the step key diverges, and replay misses — with nothing obviously
wrong to look at.

Recording must not change what is recorded. Keep tapes in a separate directory. This is pinned by
`test_recording_into_the_workspace_changes_the_run`.

## Canonical JSON

Every line is serialized identically or the format is worthless. The rules:

| Rule | Value | Why |
|---|---|---|
| Key order | sorted | Dict insertion order is not semantic |
| Separators | `(",", ":")` | No incidental whitespace |
| Non-ASCII | emitted literally, UTF-8 | Tapes stay greppable (ADR-0003) |
| Unicode | **NFC-normalized** | `é` has two encodings; same string, different bytes, different hash |
| NaN / Infinity | **rejected** | Not valid JSON; silently accepted by Python's default |
| Trailing newline | exactly one per line | |

Floats use Python's `repr` shortest-round-trip form, which is stable across CPython versions.

## Records

Every record has `kind`, `seq` (0-based, gapless, in write order), and `step`.

| `kind` | Meaning | Extra fields |
|---|---|---|
| `header` | Line 1 only | `v`, `tapeloop` |
| `run_start` | Opens a run | `data`: `model`, `provider`, `tools`, `streaming` |
| `message` | One canonical message | `data`: an encoded `Message` |
| `step` | A model response and its key | `key`, `data`: an encoded `ModelResponse` |
| `tool_result` | One tool outcome | `data`: `tool`, `effect`, `is_error` |
| `cancelled` | Run was interrupted | `data`: `reason` |
| `run_end` | Closes a run | `data`: `stop_reason`, `cancelled` |

A `step` record is what the cache reads. Its `key` is the content-addressed step key.

## Encoded types

### Message

```json
{"role":"assistant","text":"…","tool_calls":[…],"tool_results":[…],"opaque":[…]}
```

Empty collections and a null `text` are **omitted**, not written as `[]` or `null` — one
representation per value, or byte-identity fails.

`role` is one of `system`, `user`, `assistant`, `tool_results`.

### ToolCall

```json
{"id":"call_a","name":"read_file","arguments":{"path":"a.txt"}}
```

`arguments` is a decoded object, never the provider's JSON *string*.

### ToolResult

```json
{"call_id":"call_a","content":"…","is_error":false}
```

**Ordering is normative** (ADR-0014): results appear in the order of their corresponding calls in
the preceding assistant message, never in arrival order. `is_error` is omitted when false.

### Opaque

```json
{"provider":"openai","kind":"reasoning","data":…}
```

Content the runtime does not interpret. Stored verbatim, returned verbatim to the provider that
produced it, and dropped — visibly — when forking elsewhere (ADR-0011). `data` is whatever the
provider sent; it must survive a JSON round-trip unchanged.

## Step keys

```
key(n) = sha256(canonical_json({
    "provider":     provider_id,
    "model":        model_id,
    "params":       {...},        # max_tokens, effort, …
    "tools":        [tool schemas, by name],
    "events":       [canonical events 0..n],
}))
```

Explicitly **excluded**: timestamps, run ids, machine identity, tool *execution* order, latency —
anything that would make a byte-identical re-run miss.

Provider and model are inside the key deliberately: cross-provider replay is a miss by
definition, because a different model is a different run. The useful cross-provider operation is
`fork`, not `replay`.

## Compatibility

A reader encountering an unknown `v` **must** fail with a message naming the version. It must
never best-effort parse: a partially-understood tape that appears to work is worse than one that
refuses to open.

Unknown `kind` values on individual records are skipped with a warning — that direction is
additive and safe.
