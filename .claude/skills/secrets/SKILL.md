---
name: secrets
description: Use whenever a diff is about to be committed. Covers `gitleaks` — detects accidental credential exposure (API keys, tokens, private keys, AWS/GCP signatures) before commit. Cross-cutting: runs against the diff regardless of file type. Any finding is a blocker. Config in `${LINT_CONFIGS}/`.
---

# secrets

`gitleaks` scans diffs and files for accidentally-staged credentials. Cross-cutting — runs against the whole diff or staged tree, not specific file globs.

## Files covered

Any diff. Run before every commit.

## Linters

### gitleaks — secret detection (SARIF)

Scan staged changes only (pre-commit verify):
```bash
gitleaks protect --staged \
  --config=${LINT_CONFIGS}/gitleaks.toml \
  --report-format=sarif --report-path=/tmp/gitleaks.sarif --exit-code=1
```

Scan branch commits vs. the integration branch:
```bash
gitleaks detect --log-opts="main..HEAD" \
  --config=${LINT_CONFIGS}/gitleaks.toml \
  --report-format=sarif --report-path=/tmp/gitleaks.sarif --exit-code=1
```

Scan a specific file (no git history needed):
```bash
gitleaks detect --no-git --source=<file> \
  --config=${LINT_CONFIGS}/gitleaks.toml \
  --report-format=sarif --report-path=/tmp/gitleaks.sarif --exit-code=1
```

SARIF output at `/tmp/gitleaks.sarif`. Findings in `runs[0].results[]` — each has `ruleId`, `message.text`, `locations[0].physicalLocation.artifactLocation.uri`, and `region.startLine`.

**Any finding is a blocker.** Do not commit. Investigate: is it a real leak (rotate the credential, scrub from history) or a false positive (add to the allowlist in [`gitleaks.toml`](../../../.agentic/linter-configs/gitleaks.toml) with a reason)?

## Per-line inline suppression

```python
api_key = "AKIAIOSFODNN7EXAMPLE"  # gitleaks:allow — well-known AWS docs example
```

Inline `gitleaks:allow` only with a reason. If you're tempted to suppress without one, you're probably wrong about it being a false positive.

## Real-leak response

If `gitleaks` finds a credential that was actually exposed (even briefly, even in a branch nobody pulled):

1. **Rotate the credential immediately.** The exposure window starts at `git add`, not at merge.
2. **Scrub from history** with `git filter-repo` or BFG — destructive history rewrite, escalation per project rules.
3. **Audit consumers** of the rotated credential. Coordinate the rotation across them before the new value lands in storage.

Project secrets storage and rotation specifics live in CLAUDE.md § Secrets.

## When the executor runs this

Before every commit (`gitleaks protect --staged ...`). The [`task-review` agent](../../agents/task-review.md) also runs gitleaks against the branch diff — defense in depth.
