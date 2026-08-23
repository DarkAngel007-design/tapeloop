# Security

tapeloop executes commands written by a language model, against files it was pointed at. That is
the product, not a side effect, so the honest question is not "is it safe" but **what is it safe
against, and what is it not**.

## Reporting a vulnerability

Open a [GitHub security advisory](https://github.com/DarkAngel007-design/tapeloop/security/advisories/new).
Please do not open a public issue for anything exploitable. This is a pre-1.0 personal project;
expect a reply in days, not hours.

## What the sandbox actually protects against

Isolation is a ladder, and a run records which rung it was on — a recorded run must never be able
to claim protection it did not have.

| Backend | Protects against | Does not protect against |
|---------|------------------|--------------------------|
| `SubprocessExecutor` (default) | Nothing. Timeouts and a working directory only. | Anything at all. |
| `DockerExecutor` | Untrusted input: no network, no capabilities, no new privileges, read-only root, workspace is the sole writable mount, `noexec` tmp. | A container escape, a malicious image, a kernel bug. |
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

## Tapes

A tape records the full conversation, including everything a tool read. **A tape can contain
secrets that were in the files the agent looked at.** Treat one like a debug log: `.tapeloop/` is
gitignored by default, and a tape should be reviewed before being attached to a bug report.
