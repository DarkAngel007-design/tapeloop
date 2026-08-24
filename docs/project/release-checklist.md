# Release checklist

Run every one of these before publishing. They are ordered so the cheap ones fail first.

Most of this is ordinary. Two steps are not, and both caught a real bug the first time
they were run: **installing the built artifact in a clean environment**, and **testing
against the declared dependency floor rather than whatever happens to be installed**.

## 1. Static

```bash
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest
```

## 2. Version is single-sourced

`pyproject.toml` uses `dynamic = ["version"]` reading `src/tapeloop/__init__.py`. Nothing
else may hold a copy — a tape's header records the writer version, and a drifted copy
makes a tape claim provenance it does not have.

```bash
grep -rniE '\bversion\b.{0,4}[:=].{0,4}"[0-9]+\.[0-9]+\.[0-9]+"' src/
```

Case-insensitive, and matching `:` as well as `=`. The narrower first version of this grep
missed `SERVER_VERSION = "0.0.0"` and `"version": "0.0.0"` in the MCP layer, and 0.1.0 shipped
telling every MCP host it was version 0.0.0.

## 3. The declared dependency floor actually works

**Do not skip this.** `openai>=1.60` was declared for six milestones and was never
installable: `omit` and `ChatCompletionToolUnionParam` do not exist before 2.0, and both
are used unconditionally. Every local run used the latest version, so nothing caught it.

```bash
uv venv --python 3.12 /tmp/floor && \
uv pip install --python /tmp/floor/bin/python dist/*.whl "openai==2.0.0" pytest && \
PYTHONPATH=tests /tmp/floor/bin/python -m pytest tests -q
```

## 4. The declared Python floor actually works

`requires-python = ">=3.11"` is a claim. Test it, on the **built wheel**, not the source tree.

```bash
for py in 3.11 3.12 3.14; do
  uv venv --python $py /tmp/env$py
  uv pip install --python /tmp/env$py/bin/python dist/*.whl pytest
  PYTHONPATH=tests /tmp/env$py/bin/python -m pytest tests -q
done
```

## 5. Build, and check what is in it

```bash
rm -rf dist && uv build
uv run --with twine twine check dist/*
python -c "import zipfile,glob; print(zipfile.ZipFile(glob.glob('dist/*.whl')[0]).namelist())"
```

The wheel must contain **no** `tests/`, `.env`, `LOGBOOK.md`, or `evals/`.

## 6. Smoke test the CLI from the installed wheel

Not from the source tree — an entry point can be broken in ways `uv run` hides.

```bash
tapeloop --help && tapeloop show <tape> && tapeloop diff <tape> <tape> && tapeloop view <tape>
python -m tapeloop.mcp.server </dev/null
```

## 7. Optional extras degrade and upgrade correctly

Without `[tokens]`, `count_text` must report `estimated`. With it, `exact`. Neither may crash.

## 8. Eval regression

```bash
uv run tapeloop eval --repeats 5
```

Compare **shared tasks only** against the previous baseline in `evals/`. Headline means
across different task sets are not comparable. A move greater than one spread is
investigated before publishing, not explained afterwards.

## 9. Benchmarks

No thresholds are enforced, because nothing here is on a hot path — a step key takes ~150 µs
against a model call measured in seconds. They are recorded so a future regression is visible
as a change rather than discovered as a slowdown.

## 10. After publishing

Tag the commit, and confirm `pip install tapeloop` works from a clean environment on a
machine that has never seen the source.
