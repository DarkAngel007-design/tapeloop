# tapeloop

An agent runtime that records every step, so any run can be replayed, forked, and diffed.

> **Pre-alpha (M5 of M9).** The public API does not exist yet. See [ROADMAP](https://github.com/DarkAngel007-design/tapeloop/blob/main/ROADMAP.md).

These docs follow [Diátaxis](https://diataxis.fr) — four modes, kept strictly separate:

- **[Tutorials](tutorials/README.md)** — learning-oriented. Follow along, end to end.
- **[How-to guides](how-to/README.md)** — task-oriented. You already know why; here is how.
- **[Reference](reference/README.md)** — information-oriented. Dry, complete, no narrative.
- **[Explanation](explanation/architecture.md)** — understanding-oriented. Why it is built this way.

Decisions live in **[ADRs](adr/README.md)**, numbered and immutable.

## Start here

If you want to understand the project, read [the architecture](explanation/architecture.md) and
then [ADR-0011](adr/0011-canonical-event-log.md), which is the idea everything else serves.
