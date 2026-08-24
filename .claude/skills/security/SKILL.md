---
name: security
description: Use when editing agent code or any file in a language semgrep covers (Python, TS/JS, YAML, Dockerfile). Covers `semgrep` (pattern-based security/correctness). For accidental credential exposure, use the `secrets` skill instead. Config in `${LINT_CONFIGS}/`.
---

# security

**semgrep** — pattern-based scanning across many languages. Good for "did we accidentally do X"
rules; lighter than full SAST, and the right fit for agent code where the risky patterns are
specific (a swallowed exception, a subprocess call, a secret read into a log line).

For accidental credential exposure use the [`secrets` skill](../secrets/SKILL.md) (`gitleaks`) —
a different mental model, and it runs over every diff regardless of file type.

checkov is deliberately not installed: this repo has no Terraform, Kubernetes, or CloudFormation
substrate. If that changes, add the tool, its config, and its section here together.

## Files covered

- `**/*.py` — agent code and scripts
- `**/*.ts`, `**/*.tsx`, `**/*.js`
- `**/*.yaml`, `**/*.yml`, `**/Dockerfile*` — semgrep's own rules for these

## Linters

### semgrep — pattern-based code scan (JSON)

```bash
semgrep --config p/ci --config p/security-audit \
  --severity ERROR --severity WARNING \
  --json <file-or-dir>
```

The `p/ci` and `p/security-audit` packs are pulled from the public Semgrep registry on first run
(`semgrep.dev` is allowlisted in the firewall). For project-specific rules extend
[`semgrep.yml`](../../../.agentic/linter-configs/semgrep.yml) and chain another `--config` flag.

Output has `results[]` with `check_id`, `path`, `start.line`, `extra.severity`
(`ERROR`/`WARNING`/`INFO`), `extra.message`. **`ERROR` is a blocker; `WARNING` is fix-if-touched.**

## Per-line inline suppressions

```python
# nosemgrep: rule-id  -- the broad except is deliberate; a raising tool kills the session
except Exception as exc:
```

A suppression always carries a reason. In agent code the two legitimate ones are the
never-raise tool wrapper and the loop's top-level catch — both documented in
[kb/architecture/agent-anatomy.md](../../../kb/architecture/agent-anatomy.md). Anything else needs
justifying on its own terms.

## When the executor runs this

After editing non-trivial code in a scanned language. The
[`task-review` agent](../../agents/task-review.md) re-runs it over the diff before commits.
