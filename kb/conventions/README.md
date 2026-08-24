# Convention routing

Maps a changed-file glob to the convention source(s) the
[task-review](../../.claude/skills/task-review/SKILL.md) agent loads and the skill whose *Linters*
section it runs. For the tool → config-file index see
[../../.agentic/linter-configs/README.md](../../.agentic/linter-configs/README.md).

| File glob | Skill(s) (linters) | Convention source |
|---|---|---|
| `agents/**/*.py` | [python](../../.claude/skills/python/SKILL.md) (ruff, pyright) + [security](../../.claude/skills/security/SKILL.md) (semgrep) | [agents.md](agents.md), [project.md](project.md) |
| `**/*.py` (elsewhere) | [python](../../.claude/skills/python/SKILL.md) | [project.md](project.md) |
| `agents/**/agent_config.yaml` | [yaml](../../.claude/skills/yaml/SKILL.md) + [secrets](../../.claude/skills/secrets/SKILL.md) | [agents.md](agents.md) |
| `**/*.yaml`, `**/*.yml` (not workflows) | [yaml](../../.claude/skills/yaml/SKILL.md) (yamllint) | [project.md](project.md) |
| `.github/workflows/**` | [github-actions](../../.claude/skills/github-actions/SKILL.md) (actionlint, zizmor) | [project.md](project.md) |
| `**/Dockerfile*` | [dockerfile](../../.claude/skills/dockerfile/SKILL.md) (hadolint, trivy) | [agents.md](agents.md) |
| `**/*.sh`, `**/*.bash` | [shell](../../.claude/skills/shell/SKILL.md) (shellcheck, shfmt) | [project.md](project.md) |
| `**/*.md` | [markdown](../../.claude/skills/markdown/SKILL.md) (markdownlint-cli2) | [project.md](project.md) (+ [comments](../../.claude/skills/comments/SKILL.md) when comments change) |
| a new or changed agent | [new-agent](../../.claude/skills/new-agent/SKILL.md) | [agents.md](agents.md) |
| every diff (cross-cutting) | [secrets](../../.claude/skills/secrets/SKILL.md) (gitleaks); [git](../../.claude/skills/git/SKILL.md) | [git.md](git.md) |

checkov / tflint / kubeconform / kube-linter are intentionally absent — this repo has no Terraform,
Kubernetes, or Helm substrate. Add the tool, its config and its skill together if that changes.
