---
name: markdown
description: Use when authoring or modifying Markdown docs. Covers `markdownlint-cli2` — structural lint (heading levels, list consistency, link sanity). Config keeps style rules loose; docs are read by Claude, not rendered to a static site. Config in `${LINT_CONFIGS}/`.
---

# markdown

Structural lint via `markdownlint-cli2`. Config in [`markdownlint.jsonc`](../../../.agentic/linter-configs/markdownlint.jsonc) keeps style off (line length, inline HTML) and catches real structural problems (duplicate H1s, broken list nesting, malformed link syntax).

## Files covered

- `**/*.md`
- `**/*.mdx`

## Linters

### markdownlint-cli2 — markdown structural lint

```bash
markdownlint-cli2 --config ${LINT_CONFIGS}/markdownlint.jsonc <file-or-glob>
```

Default output: `<file>:<line>:<col> <rule>/<alias> <description>`. For machine output, configure a SARIF formatter via the config file or pipe through a converter. The text format is grep-friendly and usually enough.

**Single-file invocation gotcha.** The config carries a `globs:` array, and the CLI *adds* its positional args to those globs rather than replacing them — running `markdownlint-cli2 ... <some.md>` from a repo root will still scan every `**/*.md` under cwd. To lint exactly one file (e.g., the file you just edited), `cd` into its parent directory first; the glob then scopes to that directory only:

```bash
cd "$(dirname <file.md>)" && markdownlint-cli2 --config ${LINT_CONFIGS}/markdownlint.jsonc "$(basename <file.md>)"
```

Or pass `--no-globs` (markdownlint-cli2 ≥ 0.14) to disable config globs entirely and use only the positional args.

Disabled rules in the config:
- `MD013` — line-length (off; docs aren't reflowed)
- `MD033` — inline HTML (off; `<details>` blocks are common)
- `MD041` — first-line-h1 (off; some docs start with frontmatter)
- `MD024 siblings_only` — duplicate-headings only flagged within the same section

Markdown-only findings are typically nit severity, not blockers.

## Per-line inline suppressions

```markdown
<!-- markdownlint-disable MD013 -->
...
<!-- markdownlint-enable -->
```

Single line:
```markdown
<!-- markdownlint-disable-next-line MD013 -->
A very long line we know is long...
```

## When the executor runs this

After editing any `.md` file. The [`task-review` agent](../../agents/task-review.md) re-runs markdownlint on the diff before commits, but typically classifies findings as nit unless they're broken structurally.
