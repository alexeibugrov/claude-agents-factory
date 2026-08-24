---
name: yaml
description: Use when authoring or modifying YAML files outside GH Actions workflows — agent configs, compose files, and any other YAML. Covers yamllint (structure + style). Config lives in `${LINT_CONFIGS}/`.
---

# yaml

Structural and stylistic lint for YAML via `yamllint`.

## Files covered

- `**/*.yaml`
- `**/*.yml`

**Excluded by `yamllint.yaml` config** (would fail on Go template syntax):
- `**/charts/**`
- `**/node_modules/**`
- `**/vendor/**`

For GH Actions workflows, see [`github-actions`](../github-actions/SKILL.md) — `actionlint` understands the workflow schema and is the right tool for those.

## Linters

### yamllint — style + structure (parsable text; no JSON)

```bash
yamllint -c ${LINT_CONFIGS}/yamllint.yaml <file-or-dir>
```

Machine-readable format:
```bash
yamllint -c ${LINT_CONFIGS}/yamllint.yaml -f parsable <file-or-dir>
```

Output (parsable):
```
<file>:<line>:<col>: [<level>] <message> (<rule>)
```

`level` is `error` (blocker) or `warning` (fix-if-touched or nit).

## Per-line inline suppressions

```yaml
# yamllint disable-line rule:line-length
some-key: very-long-string-...
```

Region:
```yaml
# yamllint disable rule:indentation
...
# yamllint enable
```

## When the executor runs this

After editing any `.yaml`/`.yml` outside the excluded paths. The [`task-review` agent](../../agents/task-review.md) re-runs yamllint on the diff before commits.
