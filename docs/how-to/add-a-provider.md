# Add a provider

An adapter's whole job is two functions: canonical events → wire format, and wire
response → canonical events. Everything else in tapeloop is provider-neutral.

## The contract

The `ModelClient` Protocol is only a signature. **The definition is the conformance
suite** — 18 checks, one per row of the [divergence
table](../explanation/provider-differences.md) plus general invariants:

```bash
tapeloop conformance --target openai
```

Run it against your adapter before you trust it. It needs no network and no API key:
every check runs against synthetic wire payloads your adapter constructs itself, so a
provider can be conformance-tested before anyone has credentials for it.

```python
from tapeloop.providers.conformance import run_conformance
from tapeloop.providers.targets import openai_target

report = run_conformance(openai_target())
print(report.render())
assert report.passed
assert len(report.checks) >= 18
```

## What your adapter must supply

A `ConformanceTarget` needs four things. An adapter that cannot provide them has not
separated rendering from parsing, which is the split the whole seam depends on:

- `render_messages` — canonical → wire
- `render_tools` — registry schemas → wire
- `parse` — wire response → `ModelResponse`
- `build_wire` — fabricate a synthetic provider response, so the parser is testable

Plus the provider's own stop-reason vocabulary, mapped into `StopReason`.

## The seven divergences

Each is a row in the table and a check in the suite. The two that catch people:

**Tool-result grouping.** OpenAI wants one `role: "tool"` message per result; Anthropic
wants every result inside a single `user` message. Splitting them for Anthropic teaches
the model to stop calling tools in parallel, and **nothing errors**. The tape stores
the *set*; each adapter lays it out its own way.

**Unknown stop reasons.** A value you do not recognise must map to `OTHER`, never to
`END_TURN`. A future stop reason that looks like a finished turn is a run that stops
silently and wrongly.

## Writing it

Add your target to `BUILTIN_TARGETS`, run the suite, and fix what fails. The Anthropic
target is already registered while its adapter is signatures-only — it fails 15 of 18
by name, and those failures are the implementation checklist.
