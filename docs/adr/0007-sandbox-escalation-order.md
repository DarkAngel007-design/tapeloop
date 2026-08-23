# ADR-0007 — Sandbox backend escalation order

**Status:** Accepted · 2026-08-23

## Context

Agents execute model-authored commands. The threat model has two distinct parts: *accidents*
(a confused model running `rm -rf`) and *adversaries* (indirect prompt injection from a file the
agent reads). These need different amounts of isolation, and the strongest option is the most
expensive to build and to run.

## Decision

Escalate through three backends behind one `Executor` Protocol:

1. **Subprocess** — timeout, working-directory confinement, environment scrubbing. Addresses
   accidents only. Ships at M1 as the only implementation.
2. **Docker** — filesystem isolation, read-only mounts outside the workspace, network egress
   allowlist, no credentials inside. Addresses untrusted input. Ships at M5.
3. **bubblewrap / seccomp** — for users who want isolation without a Docker daemon. Later.

The sandbox lands at **M5, not M3**, against the usual "never retrofit isolation" advice. The
reason is specific: the replay contract determines what the sandbox must snapshot, so building
it before the tape exists means building it twice.

## Consequences

- The mitigation is non-negotiable: **every** tool call routes through the `Executor` seam from
  M1, so M5 adds a backend rather than rewriting call sites.
- Until M5, `SECURITY.md` does not exist and the README must say the runtime is unsafe on
  untrusted input. Honesty over marketing.
- M0 has no `Executor` at all — only workspace path confinement, enforced by a test.
