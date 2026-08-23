# pyright: basic
#
# Strict mode is the standard for src/. This file is exempt on purpose: it is an
# unabstracted spike over an SDK whose tool-call types are partially unknown, and
# satisfying strict here would mean adding the abstractions M0 exists to omit.
"""M0 — the bare agent loop, deliberately unabstracted.

This file exists so the protocol is visible before anything hides it. Everything
here is hand-written on purpose:

  * tool schemas are literal dicts       -> M1 generates them from type hints
  * dispatch is an if/elif chain         -> M1 is a registry
  * there is no tape                     -> M3 records one
  * there is no sandbox                  -> M5 adds one

Do not refactor this file. Its ugliness is the point: when M1 replaces it, the
diff is the lesson.

Usage: uv run python m0/loop.py "<task>"    (see m0/README.md)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from dotenv import find_dotenv, load_dotenv
from openai import OpenAI

# usecwd=True: find .env from where the command was run, not from this file's
# directory. Must run BEFORE the settings below are read, not inside main().
load_dotenv(find_dotenv(usecwd=True))

MODEL = os.environ.get("TAPELOOP_MODEL", "gpt-4o-mini")
WORKSPACE = Path(os.environ.get("TAPELOOP_WORKSPACE", ".")).resolve()
MAX_STEPS = 12

SYSTEM = (
    "You are a careful engineering assistant working inside a single directory. "
    "Use the tools to inspect and change files. Do the smallest thing that "
    "satisfies the request, then stop and say what you did."
)

# --- tool schemas ---------------------------------------------------------
# Hand-written JSON Schema. Note how much of this duplicates the Python
# signatures below -- that duplication is exactly what M1's registry removes.

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file, relative to the workspace root.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write or overwrite a UTF-8 text file, relative to the workspace root.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command in the workspace root and return its output.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
]


def _safe_path(rel: str) -> Path:
    """Confine every path to the workspace. A stand-in for M5's sandbox."""
    p = (WORKSPACE / rel).resolve()
    if not p.is_relative_to(WORKSPACE):
        raise ValueError(f"path escapes workspace: {rel}")
    return p


def dispatch(name: str, args: dict[str, Any], *, confirm: bool) -> str:
    """Execute one tool. Returns a string; NEVER raises into the loop.

    Errors come back as ordinary tool output so the model can read them and
    recover. A tool that raises is a dead run.
    """
    try:
        if name == "read_file":
            return _safe_path(args["path"]).read_text(encoding="utf-8")

        if name == "write_file":
            p = _safe_path(args["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args["content"], encoding="utf-8")
            return f"wrote {len(args['content'])} bytes to {args['path']}"

        if name == "run_command":
            cmd = args["command"]
            if confirm and input(f"  run: {cmd}\n  [y/N] ").strip().lower() != "y":
                return "ERROR: the user declined to run this command."
            r = subprocess.run(  # noqa: S602 - no sandbox until M5, see ADR-0007
                cmd, shell=True, cwd=WORKSPACE, capture_output=True, text=True, timeout=60
            )
            out = (r.stdout + r.stderr).strip()
            if not out:
                return f"exit={r.returncode} (no output)"
            return f"exit={r.returncode}\n{out[:4000]}"

        return f"ERROR: no such tool {name!r}"
    except Exception as e:  # deliberate: errors are data, not exceptions
        return f"ERROR: {type(e).__name__}: {e}"


def main() -> int:
    if not sys.argv[1:]:
        print(__doc__)
        return 2
    if not os.environ.get("OPENAI_API_KEY"):
        print(
            "OPENAI_API_KEY is not set. Copy .env.example to .env, or export it.", file=sys.stderr
        )
        return 2

    task = " ".join(sys.argv[1:])
    confirm = os.environ.get("TAPELOOP_YOLO") != "1"
    client = OpenAI()

    messages: list[Any] = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task}]
    sent = recv = 0

    print(f"model={MODEL}  workspace={WORKSPACE}", file=sys.stderr)

    step = -1  # so the summary below is correct even if MAX_STEPS is 0
    for step in range(MAX_STEPS):
        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            # cast() because hand-written dicts do not satisfy the SDK's tool param
            # types. That gap is not incidental -- it is exactly what M1's registry
            # closes by generating schemas from typed signatures instead.
            tools=cast(Any, TOOLS),
            max_completion_tokens=4096,
        )
        choice = resp.choices[0]
        msg = choice.message
        if resp.usage:
            sent += resp.usage.prompt_tokens
            recv += resp.usage.completion_tokens

        # Append the assistant message VERBATIM. Reconstructing it by hand is how
        # you silently lose tool_calls, refusals, and provider-specific fields.
        messages.append(msg.model_dump(exclude_none=True))

        print(f"[{step:02}] finish={choice.finish_reason} +{recv} tok", file=sys.stderr)

        if choice.finish_reason == "length":
            print("hit the output cap mid-message; stopping.", file=sys.stderr)
            break
        if not msg.tool_calls:
            print(f"\n{msg.content or ''}")
            break

        # One tool message per call, each carrying its tool_call_id. Merging or
        # reordering these breaks the pairing the model relies on.
        for tc in msg.tool_calls:
            fn = tc.function  # type: ignore[union-attr]
            print(f"     -> {fn.name}({fn.arguments[:80]})", file=sys.stderr)
            try:
                content = dispatch(fn.name, json.loads(fn.arguments or "{}"), confirm=confirm)
            except json.JSONDecodeError as e:
                content = f"ERROR: arguments were not valid JSON: {e}"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})
    else:
        print(f"stopped: hit MAX_STEPS={MAX_STEPS}", file=sys.stderr)

    # The seed of the tape: this is the only record M0 keeps, and it vanishes
    # when the process exits. M3 makes it durable and replayable.
    print(f"\nsteps={step + 1}  tokens_in={sent}  tokens_out={recv}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
