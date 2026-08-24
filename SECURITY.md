# Security

tapeloop executes commands written by a language model, against files it was pointed at. That is
the product, not a side effect, so the honest question is not "is it safe" but **what is it safe
against, and what is it not**.

## Reporting a vulnerability

Open a [GitHub security advisory](https://github.com/DarkAngel007-design/tapeloop/security/advisories/new).
Please do not open a public issue for anything exploitable. This is a pre-1.0 personal project;
expect a reply in days, not hours.

## The defaults

Stated first, because the rest of this document describes mechanisms that are **opt-in**, and a
security document that describes protections without saying they are off by default is worse than
no document.

| Setting | Default | Meaning |
|---|---|---|
| `Agent.policy` | `None` | **No permission gating.** Every tool call the model makes is executed. |
| `Agent.budget` | `None` | No truncation, no compaction. |
| Executor | `SubprocessExecutor` | `shell=True` on your host. No isolation of any kind. |

So a bare `Agent(...)` runs model-authored shell commands on your machine, unrestricted. That is
deliberate — see ADR-0007 on why a container that silently failed to start would be worse than one
you knowingly did not use — but it is **opt-in safety, not opt-out**.

For anything you do not fully control, attach a `PermissionPolicy` *and* a `DockerExecutor`. Neither
alone is sufficient: the policy decides what may run, the executor decides what running can reach.

## What the sandbox actually protects against

Isolation is a ladder, and a run records which rung it was on — a recorded run must never be able
to claim protection it did not have.

| Backend | Protects against | Does not protect against |
|---------|------------------|--------------------------|
| `SubprocessExecutor` (default) | Nothing. Timeouts and a working directory only. | Anything at all. |
| `DockerExecutor` | Untrusted input: no network, no capabilities, no new privileges, read-only root, workspace is the sole writable mount, `noexec` tmp, **runs as the host uid rather than root**. **Verified by 14 adversarial tests against a real daemon** (`pytest -m live`). | A container escape, a malicious image, a kernel bug. |
| gVisor / microVM (not built) | The above plus kernel attack surface. | — |

**The default provides no isolation.** That is deliberate rather than sloppy: a container that
silently fails to start would be worse than one you knowingly did not use. `DockerExecutor` raises
if Docker is missing instead of degrading quietly.

## Prompt injection

A file the agent reads can contain text addressed to the model. It will sometimes work.

**tapeloop does not attempt to detect this, and any harness claiming to reliably detect it is
overselling.** A hostile instruction is just text; distinguishing it from a legitimate one is not a
solved problem, and a detector that mostly works trains people to trust it.

What tapeloop does instead is make persuasion insufficient. The model can be entirely taken in and
still not gain capability, because the dangerous action needs a permission rule that allows it. The
ship criterion for this milestone is exactly that test: the model dutifully attempts an injected
`curl … | sh`, and it does not run.

Practical consequences:

- **Attach a policy at all.** With `policy=None` there is nothing to deny with, and the paragraph
  above does not apply — the model's request goes straight to the tool.
- **Deny by default for anything that reaches outside the workspace.** Set rules in
  `.tapeloop/permissions.toml`; commit the file so changes get reviewed.
- **An unattended run with no prompter refuses** rather than assuming approval. Assuming yes is how
  a cron job does something nobody agreed to.
- **Do not put credentials in the workspace.** `DockerExecutor` passes no environment through, but
  a key in a file the agent can read is a key the agent can exfiltrate if any egress exists.

## Secrets

`.env` is gitignored. `.env.example` is committed and must contain placeholders only — a real key
once reached it and had to be purged from six commits.

A pre-commit hook blocks key-shaped strings. Git does not install hooks on clone, so enable it:

```bash
git config core.hooksPath .githooks
```

## Running the eval suite

`PythonBehaviour`, the grader that checks a code-change task, **executes the code the agent wrote,
in-process and unsandboxed**. That is inherent to the job — you cannot verify a fix works without
running it — but it is arbitrary code execution. It is reachable only from the eval suite and never
from the agent loop. Run evals in a container, on tasks you wrote, against workspaces you control.

## Tapes

A tape records the full conversation, including everything a tool read. **A tape can contain
secrets that were in the files the agent looked at.** Treat one like a debug log: `.tapeloop/` is
gitignored by default, and a tape should be reviewed before being attached to a bug report.
