---
name: python
description: Use when writing or reviewing any Python script — especially throwaway/temporary scripts written for task work (parsing, data transforms, one-offs). Covers `ruff check`, `ruff format`, `pyright` (basic mode). Configs tuned for one-off scripts, not production style. Configs in `${LINT_CONFIGS}/`.
---

# python

Bug-class lint (`ruff check`), formatter (`ruff format`), and type check (`pyright` in basic mode) for Python scripts.

The shipped configs are tuned for **throwaway/temporary scripts**: catch real bugs (undefined names, unused imports, type errors), ignore production-style nits (docstrings, full annotations, print statements). If a long-lived Python service ever lands, override these configs alongside it rather than loosening globally.

## Files covered

- `**/*.py`

## Linters

### ruff check — bug-class lint (JSON)

```bash
ruff check --config ${LINT_CONFIGS}/ruff.toml --output-format=json <file-or-dir>
```

Enabled rule groups: `E` (pycodestyle errors), `F` (pyflakes — undefined names, unused imports, syntax), `B` (bugbear — common bug patterns). Disabled: `D` (docstrings), `ANN` (type annotations), `T201` (print), `S101` (assert).

Output is a JSON array; each item has `filename`, `location.row/column`, `code`, `message`. Any `F`-code (undefined name, unused import, syntax) is a blocker.

### ruff format — formatter (exit code; no JSON)

```bash
ruff format --config ${LINT_CONFIGS}/ruff.toml --check <file-or-dir>   # check
ruff format --config ${LINT_CONFIGS}/ruff.toml <file-or-dir>           # write
```

### pyright — type check, basic mode (JSON)

```bash
pyright --project ${LINT_CONFIGS}/pyrightconfig.json --outputjson <file-or-dir>
```

`typeCheckingMode: "basic"` — catches real type errors without insisting on full annotations. `reportMissingTypeStubs: "none"` ignores missing third-party stubs.

Output JSON has `generalDiagnostics[]` with `severity` (`error`/`warning`/`information`), `file`, `range`, `message`, `rule`.

## Throwaway-script workflow

For a script Claude writes inline during a task:

```bash
mkdir -p /tmp/task-scratch && cat > /tmp/task-scratch/parse.py <<'PY'
...
PY

ruff check   --config ${LINT_CONFIGS}/ruff.toml --output-format=json /tmp/task-scratch/parse.py
pyright      --project ${LINT_CONFIGS}/pyrightconfig.json --outputjson /tmp/task-scratch/parse.py

python3 /tmp/task-scratch/parse.py
```

Skipping the lint and trusting an un-linted script's output has burned past sessions — a `NameError` or off-by-one is much cheaper to catch up front than to chase down after seeing a wrong answer.

## When the executor runs this

After writing or editing any `.py` file, before running it (per CLAUDE.md § Temporary Python scripts). The [`task-review` agent](../../agents/task-review.md) re-runs both on the diff before commits.
