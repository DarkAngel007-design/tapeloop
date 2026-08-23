"""The command line.

Built on `argparse` rather than typer or click. The charter states that a short
dependency list is a feature, and this layer is thin — it parses arguments and
calls library functions. A CLI framework would be the third dependency in the
project, added for help-text formatting.

Commands mirror the library exactly: anything the CLI can do, a caller can do.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from tapeloop.core.loop import Agent
from tapeloop.record.jsonl import JsonlStore
from tapeloop.replay.diff import diff_tapes
from tapeloop.replay.fork import UnsoundFork, plan_fork
from tapeloop.replay.recording import Recording


def _default_tape(directory: Path, stem: str) -> Path:
    """Tapes live outside the workspace: a tape the agent can see changes the run."""
    directory.mkdir(parents=True, exist_ok=True)
    n = 1
    while (candidate := directory / f"{stem}-{n:03}.jsonl").exists():
        n += 1
    return candidate


def _build_agent(*, model: str, workspace: Path, tape: Path, system: str | None) -> Agent:
    from tapeloop.providers.openai import OpenAIClient
    from tapeloop.tools import builtin

    kwargs = {"system_prompt": system} if system else {}
    return Agent(
        client=OpenAIClient(),
        registry=builtin.build(workspace),
        model=model,
        store=JsonlStore(tape),
        **kwargs,  # pyright: ignore[reportArgumentType]
    )


def cmd_run(args: argparse.Namespace) -> int:
    tape = Path(args.tape) if args.tape else _default_tape(Path(args.tapes), "run")
    agent = _build_agent(
        model=args.model, workspace=Path(args.workspace), tape=tape, system=args.system
    )
    result = agent.run(args.task, on_delta=None if args.quiet else _echo)
    print(f"\n{result.text or ''}")
    print(f"\nsteps={result.steps}  tape={tape}", file=sys.stderr)
    return 0


def _echo(event: object) -> None:
    text = getattr(event, "text", None)
    if text:
        sys.stdout.write(text)
        sys.stdout.flush()


def cmd_show(args: argparse.Namespace) -> int:
    rec = Recording.load(Path(args.tape))
    print(f"{rec.path.name}: {rec.provider}/{rec.model}  {len(rec.steps)} steps")
    if rec.parent:
        print(
            f"  forked from {rec.parent.get('source')} @ {rec.parent.get('at')} "
            f"({rec.parent.get('soundness')})"
        )
    print(f"  tools: {', '.join(rec.tools) or '—'}")
    for step in rec.steps:
        calls = ", ".join(c.name for c in step.response.message.tool_calls)
        summary = calls or (step.response.message.text or "")[:70].replace("\n", " ")
        print(f"  {step.index:>3}  {step.key[:12]}  {summary}")
    writes = [t for t in rec.tool_calls if t.effect.value == "write"]
    if writes:
        print(f"  {len(writes)} write(s) — forking past them yields a simulated run")
    return 0


def cmd_fork(args: argparse.Namespace) -> int:
    try:
        plan = plan_fork(
            Path(args.tape),
            at=args.at,
            model=args.model,
            system=args.system,
            require_faithful=args.require_faithful,
        )
    except UnsoundFork as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    print(plan.report(), file=sys.stderr)
    if args.dry_run:
        print(f"  would replay {plan.at} step(s) from cache, then run live", file=sys.stderr)
        return 0

    tape = Path(args.tape).parent / f"fork-{Path(args.tape).stem}-at{plan.at}.jsonl"
    store = JsonlStore(tape)
    from tapeloop.record.base import Event

    store.append(
        Event(
            kind="fork",
            step=0,
            payload={
                "source": Path(args.tape).name,
                "at": plan.at,
                "soundness": plan.soundness.value,
            },
        )
    )
    agent = _build_agent(
        model=plan.model, workspace=Path(args.workspace), tape=tape, system=args.system
    )
    agent.store = store
    agent.cache = plan.cache
    result = agent.run(args.task, history=plan.history, on_delta=None if args.quiet else _echo)
    print(f"\n{result.text or ''}")
    print(
        f"\ncache: {plan.cache.stats.hits}/{plan.cache.stats.total} hit  tape={tape}",
        file=sys.stderr,
    )
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    report = diff_tapes(Path(args.a), Path(args.b))
    print(report.render())
    return 0 if report.identical else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tapeloop", description="An agent runtime that records every step."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a task, recording a tape")
    run.add_argument("task")
    run.add_argument("--model", default="gpt-4o-mini")
    run.add_argument("--workspace", default=".")
    run.add_argument("--tapes", default=".tapeloop", help="directory for tapes")
    run.add_argument("--tape", help="explicit tape path")
    run.add_argument("--system", help="override the system prompt")
    run.add_argument("--quiet", action="store_true")
    run.set_defaults(func=cmd_run)

    show = sub.add_parser("show", help="summarize a tape")
    show.add_argument("tape")
    show.set_defaults(func=cmd_show)

    fork = sub.add_parser("fork", help="branch a tape at a step and continue live")
    fork.add_argument("tape")
    fork.add_argument("task")
    fork.add_argument("--at", type=int, required=True, help="step to branch at")
    fork.add_argument("--model")
    fork.add_argument("--system", help="the thing you are usually changing")
    fork.add_argument("--workspace", default=".")
    fork.add_argument(
        "--require-faithful",
        action="store_true",
        help="refuse if the replayed prefix contains a write (ADR-0016)",
    )
    fork.add_argument("--dry-run", action="store_true", help="report soundness, run nothing")
    fork.add_argument("--quiet", action="store_true")
    fork.set_defaults(func=cmd_fork)

    diff = sub.add_parser("diff", help="compare two tapes step by step")
    diff.add_argument("a")
    diff.add_argument("b")
    diff.set_defaults(func=cmd_diff)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
