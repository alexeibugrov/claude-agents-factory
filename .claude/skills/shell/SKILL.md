---
name: shell
description: Use when authoring or modifying shell scripts (.sh, .bash). Covers shellcheck (static analysis) and shfmt (formatter). Configs live in `${LINT_CONFIGS}/`.
---

# shell

Static analysis (`shellcheck`) and formatting (`shfmt`) for bash/sh scripts.

## Files covered

- `**/*.sh`
- `**/*.bash`

## Linters

### shellcheck — static analysis (JSON)

```bash
shellcheck --rcfile=${LINT_CONFIGS}/.shellcheckrc --format=json <file>
```

Returns a JSON array; empty `[]` means clean. Each finding has `file`, `line`, `endLine`, `column`, `level` (`error`/`warning`/`info`/`style`), `code` (`SCxxxx`), `message`.

Severity tier mapping:
- `error` → blocker
- `warning` → fix-if-touched
- `info`, `style` → nit

### shfmt — formatter (exit code only; no JSON)

```bash
shfmt -d -i 2 -ci <file>      # diff mode; non-zero exit if formatting changes needed
shfmt -w -i 2 -ci <file>      # write formatted output in place
```

Use `-d` for verification, `-w` to fix.

**Project style: 2-space indent with case-indent (`-i 2 -ci`).** The scripts under `.agentic/` and `.devcontainer/` use 2-space indent. shfmt's default is tabs, which produces whole-file noise diffs every time. Always pass `-i 2 -ci` to match. Don't reformat whole files in unrelated PRs — apply the flags so your edits don't drift, and let dedicated reformat PRs (if anyone ever wants one) handle the rest.

## Authoring

- **Never parse `ls` output.** Use `find` with `-maxdepth`, `-type f`, and a name glob, piping `printf '%f\n'` to downstream filters — `ls` output isn't safe to parse (spaces/newlines/control chars in names, unstable formatting). shellcheck flags the `ls | …` form as SC2012.

## Per-line inline suppressions

```bash
# shellcheck disable=SC2086  # word-splitting intentional
```

One disable + a reason comment. Prefer inline over loosening the global config.

## When the executor runs this

After editing any `.sh` or `.bash` file (see CLAUDE.md § Verification with linters). The [`task-review` agent](../../agents/task-review.md) re-runs both on the diff before commits.
