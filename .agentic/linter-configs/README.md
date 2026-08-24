# linter-configs

Central configs for every linter installed in the devcontainer. Each config is consumed by exactly one tool; tools are pointed at their config via a CLI flag from the relevant skill in [`.claude/skills/`](../../.claude/skills/) — never via working-directory auto-discovery, so the same configs work whatever working dir the lint target lives in.

## Tool → config → skill

| Tool | Config | Skill |
|---|---|---|
| yamllint | [yamllint.yaml](yamllint.yaml) | [yaml](../../.claude/skills/yaml/SKILL.md) |
| shellcheck | [.shellcheckrc](.shellcheckrc) | [shell](../../.claude/skills/shell/SKILL.md) |
| shfmt | (flags only, no config) | [shell](../../.claude/skills/shell/SKILL.md) |
| actionlint | [actionlint.yaml](actionlint.yaml) | [github-actions](../../.claude/skills/github-actions/SKILL.md) |
| zizmor | [zizmor.yml](zizmor.yml) — placeholder | [github-actions](../../.claude/skills/github-actions/SKILL.md) |
| gitleaks | [gitleaks.toml](gitleaks.toml) | [secrets](../../.claude/skills/secrets/SKILL.md) |
| hadolint | [hadolint.yaml](hadolint.yaml) | [dockerfile](../../.claude/skills/dockerfile/SKILL.md) |
| trivy | [trivy.yaml](trivy.yaml) | [dockerfile](../../.claude/skills/dockerfile/SKILL.md) |
| ruff | [ruff.toml](ruff.toml) | [python](../../.claude/skills/python/SKILL.md) |
| pyright | [pyrightconfig.json](pyrightconfig.json) | [python](../../.claude/skills/python/SKILL.md) |
| semgrep | [semgrep.yml](semgrep.yml) — placeholder, registry packs chained at call site | [security](../../.claude/skills/security/SKILL.md) |
| markdownlint-cli2 | [markdownlint.jsonc](markdownlint.jsonc) | [markdown](../../.claude/skills/markdown/SKILL.md) |

checkov, tflint, kubeconform and kube-linter are deliberately absent: this repo has no Terraform,
Kubernetes, or Helm substrate. Adding one means adding the tool to the Dockerfile, its config here,
and its skill — all three, or the routing lies.

## How configs are referenced

Every skill example passes the explicit path through the `LINT_CONFIGS` env var (set in [.devcontainer/Dockerfile](../../.devcontainer/Dockerfile)):

```bash
shellcheck --rcfile=${LINT_CONFIGS}/.shellcheckrc <file>
```

Reason: linters auto-discover dotted-name configs in the working directory, which would only fire when run from a specific cwd. An invocation from another directory would silently fall back to tool defaults. Explicit paths remove the ambiguity — and using `${LINT_CONFIGS}` keeps each skill transferable across projects (only the env var moves).

## Placeholders

[`semgrep.yml`](semgrep.yml) and [`zizmor.yml`](zizmor.yml) ship empty. The two tools work fine without local rules:

- `semgrep` is invoked with registry packs (`--config p/ci --config p/security-audit`) directly in the [`security` skill](../../.claude/skills/security/SKILL.md). The local file is a hook for project-specific rules if they ever land.
- `zizmor`'s built-in audit set covers most real-world workflow issues. The local file is a hook for project-wide suppressions or severity tuning.

## Changing a config

Edit here, not in any per-tool default. If a rule is being suppressed for a one-off reason, prefer a per-target inline disable (`# shellcheck disable=...`, `# yamllint disable-line ...`, `# nosemgrep: ...`) over loosening the global config.
