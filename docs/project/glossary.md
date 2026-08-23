# Glossary

Shared vocabulary. Where a term has a plain-language meaning and a technical one, both are given
— the plain one is what you say out loud, the technical one is what appears in the code.

## The domain

**Harness / runtime** — the code *around* the model that actually runs things. Not the model.
This whole project is a harness.

**Step** — one round of: ask the model, run whatever it asked for. The unit the tape is made of.
Distinct from a *turn* (a user-visible exchange) and a *run* (a whole task).

**Tool** — a Python function the model is allowed to call. The model never runs it; it asks, and
the harness runs it and reports back.

**Tool schema** — a machine-readable description of a tool so the model knows what arguments it
takes. Generated here from type hints; hand-written in most tutorials, which is how the two
drift apart.

**Effect class** — whether a tool changes the world: `pure` (nothing), `read` (observes only),
`write` (mutates). Undeclared means `write`. Replay soundness depends entirely on this.

## The tape

**Tape** — the append-only recording of a run. The project's namesake and its source of truth.

**Canonical event** — the provider-neutral form a message takes on the tape. Never any one
vendor's wire format.

**Opaque payload** — something the runtime cannot interpret (a reasoning blob, an encrypted
item, a vendor extension). Stored verbatim, tagged with its provider, handed straight back
untouched, and dropped *visibly* when forking to a different provider.

**Step key** — the fingerprint of a step: provider, model, params, tool schemas, and the
canonical event prefix. Change anything and every step from there on misses the cache; every
step before it hits.

**Replay** — re-running from the tape. A *simulation*: cached `write` results are returned
without touching the world, so the filesystem is **not** in the state the tape implies. Right
for prompt experiments, evals, and forks.

**Resume** — restoring a workspace snapshot and re-executing *for real*. Slower, needs the
sandbox. Right after a crash. **Not the same as replay** — see ADR-0006.

**Fork** — starting a new run that shares history with an old one up to a chosen step. The
cheap way to A/B a prompt change. Across providers, it is the feature nothing else has.

**Divergence** — the point where a replay stops matching and goes live. Also used for the seven
known behavioural differences between providers (see `docs/explanation/provider-differences.md`).

## The architecture

**Seam** — a deliberate interface where one implementation can be swapped for another. There are
four: `ModelClient`, `Executor`, `TranscriptStore`, `Grader`.

**Protocol** — Python's structural typing: "any class with these methods counts." How the seams
are expressed. No inheritance required.

**Adapter / provider** — the translation layer between canonical events and one company's API.
The only place allowed to know a wire format.

**Conformance suite** — the tests that actually define what a `ModelClient` is. The Protocol is
the signature; the suite is the contract (ADR-0002).

**Tool pack** — a registry of related tools built by a factory function, bound to a workspace.

## The process

**ADR** — Architecture Decision Record. Numbered, dated, immutable. A decision that changes gets
a *new* ADR marking the old one superseded — never an edit.

**Ship criterion** — an observable fact that ends a milestone, never a feeling. "148 code lines"
not "small enough". Several are executable tests.

**Divergence table** — `docs/explanation/provider-differences.md`. If a difference is not in it,
the seam does not handle it. It is the spec, not documentation.
