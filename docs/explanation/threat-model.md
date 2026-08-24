# Threat model

Who this is meant to stop, what it costs them, and where it stops being true. Written down because
a security posture nobody states is one nobody can check.

## Assets

1. **The host machine.** Files outside the workspace, other processes, the network.
2. **Credentials.** API keys in the environment, tokens in files, cloud metadata endpoints.
3. **The workspace.** The code the agent is meant to change.
4. **Tapes.** They contain the full conversation, including whatever tools read.

## Actors

**The confused model.** Not malicious, wrong. Writes to the wrong path, `rm -rf`s the wrong
directory, loops. Overwhelmingly the common case.

**The hostile document.** A README, issue, dependency, or web page containing text addressed to the
model. The author never touches the machine; they only need the agent to read something.

**The hostile prompt.** The operator is the adversary — they cloned this to abuse it. Out of scope;
it is their machine and their key.

**The compromised dependency.** A package in the workspace's own tree. Partly out of scope: an agent
that can run tests can run whatever the tests run.

## What is claimed

| Claim | Mechanism | Confidence |
|---|---|---|
| A tool cannot read or write outside the workspace | Path confinement, plus a single writable mount under Docker | High — path confinement is tested |
| An unattended run cannot take an action nobody approved | No prompter means deny | High — **only with a policy attached**; `policy=None` is the default and gates nothing |
| A persuaded model still cannot act outside policy | Permission rules gate the consequence | High for shell; only as good as the rules |
| Commands cannot reach the network | `--network=none` | High under Docker; **false by default** |
| A run states the isolation it actually had | `Executor.isolation` is recorded | High |
| Hostile text in a document is detected | — | **Not claimed.** See below |

## What is not claimed

**Injection is not detected.** Deliberately. The defence is that persuasion does not grant
capability, not that persuasion is spotted. A detector that catches most attempts is worse than
none, because it manufactures trust it cannot support.

**The default configuration is not isolated, and not gated either.** `SubprocessExecutor` runs on
the host and says so in its `isolation` string. Less obviously, `Agent.policy` defaults to `None`,
so out of the box there is no permission check at all — every row in the table above that depends
on a policy is a claim about a *configured* harness, not a default one. Both are opt-in.

**`PythonBehaviour` executes agent-written code in-process.** Eval-suite only, never the agent
loop, but it is arbitrary code execution and routing it through the `Executor` seam is not done.

**Container escape is not prevented, but the obvious routes are now tested.**
`tests/test_container_escape.py` runs 14 adversarial checks against a real daemon: host
filesystem unreachable, read-only root, `noexec` tmp, no DNS and no outbound TCP, no routable
interface, empty effective capability set, `NoNewPrivs`, **no Docker socket anywhere** (the
classic escape), host PIDs invisible, memory cap enforced under real page residency, timeout
kill, and `--rm` leaving nothing behind. Plus a positive control, because isolation that breaks
the feature is a broken feature rather than security.

That tests the configuration, not the kernel. A container escape through a kernel or runtime bug
is still unaddressed; the next rung is gVisor or a microVM and it is not built. Run these with
`uv run pytest -m live`.

**Tapes are not sanitized.** A tape holds what the tools read. If that included a secret, so does
the tape.

**Effect declarations are trusted.** A tool declared `read` that writes will produce a `faithful`
label on a fork that is not (ADR-0016). This is why an undeclared tool defaults to `write`, and why
`AGENTS.md` forbids widening a class to make a test pass. It is a code-review property, not a
technical control.

## Where the boundary actually sits

The single load-bearing idea, worth stating plainly because everything else follows from it:

> **Instructions come from the operator. Everything a tool returns is data.**

A file's contents, a command's output, a web page, an error message — none of these are ever
promoted to instructions, no matter how authoritative they sound, how urgent they claim to be, or
what authority they invoke. The harness has no mechanism by which tool output can grant permission,
and that absence is the control.

Everything else on this page is depth behind that one line.
