# 001 — agents-factory-setup

**Date:** 2026-08-24

## Task

Turn a fresh clone of the agentic-devops blueprint into a working **factory for Claude Agent SDK
agents**: a monorepo holding the harness, a knowledge base on how agents get built, a reusable
CI/CD pipeline, and a template that makes a new agent a scaffold-plus-fill-in rather than a project.
Knowledge was extracted from [`bb-trade-agent`](https://github.com/arbproject-org/bb-trade-agent),
which already ran three agents in production.

## What was done

**Model change.** The blueprint assumed product repos are *cloned on demand* into `repos/`. This is
a monorepo, so that whole layer was removed: the `repo-setup` skill, the `repos.md` registry, and the
`${CODE_REPO}` indirection. Container paths are now `${AGENTS_FACTORY}` / `${AGENTS}` / `${KB}`.

- **Layout** — [kb/](../../) (how agents get built), [agents/](../../../agents/) (one self-contained
  agent per directory), [.github/workflows/](../../../.github/workflows/).
- **Template** — [agents/_template/](../../../agents/_template/): config / context / tools / guards /
  loop / main, tests, Dockerfile, compose, and a README that is the agent's only documentation page.
  uv + committed `uv.lock`; the package is always named `agent` so every agent's Dockerfile, tests,
  and entrypoint are identical.
- **CI/CD** — [agent-deploy.reusable.yml](../../../.github/workflows/agent-deploy.reusable.yml): one
  pipeline, one path-filtered caller per agent, everything derived from `inputs.agent`. Adds
  `type=sha` tagging and a post-deploy running-container check, neither of which the source pipeline
  had; host keys are scanned rather than pinned. Rationale:
  [kb/architecture/cicd.md](../../architecture/cicd.md).
- **Skill** — [/new-agent](../../../.claude/skills/new-agent/SKILL.md): the four decisions to settle
  before scaffolding, the copy-and-rename, and the checklist that turns a template into an agent.
- **Substrate** — Dockerfile stripped of kubectl/helm/terraform/vault/aws/az/gcloud/ansible/Go and
  their linters; uv and a pinned telegram-mcp added. Firewall allowlist rewritten (PyPI, GHCR,
  semgrep, the VM, Telegram's DC ranges; cloud/HashiCorp entries removed).
- **Harness** — `mcp__ssh-manager` kept in `allow` at the operator's direction; every mutating
  Telegram MCP tool denied; `Read` denied on `.env*`.
  `devops-ro` provisioning removed. `devops-planner`/`devops-review` renamed to
  `task-planner`/`task-review`; Linear, wiki and writing-style skills removed.
- **KB** — architecture (overview, agent-anatomy, auth, cicd, ssh-mcp, telegram-mcp), patterns
  (tool-design, prompts-and-evals, [lessons](../../patterns/lessons.md)), conventions, and the
  [VM setup runbook](../../runbooks/new-agent-vm-setup.md).

## Result

Repo remote set to `alexeibugrov/claude-agents-factory`. Verified on the host:

- `ruff check` and `ruff format --check` clean over `agents/`; `yamllint` clean.
- `uv run pytest -q` in the template: 7 passed, 1 skipped.
- `docker build` of the template succeeds, including its two build-time assertions (the bundled
  `claude` CLI is present in the wheel; `agent.loop` imports).
- All three startup refusals fire in the real container with exit 1: missing
  `CLAUDE_CODE_OAUTH_TOKEN`, present `ANTHROPIC_API_KEY`, missing config.
- Every internal markdown link resolves; every committed JSON file parses.

**Not yet verified** — the devcontainer has not been rebuilt, so the in-container linters
(hadolint, shellcheck, actionlint, zizmor, gitleaks, semgrep, markdownlint) have not run, and no
deploy has executed against the VM.

## Comment

**Agents are self-contained, with no shared library.** Duplication of the small loop skeleton was
accepted over coupling: agents must be able to fail independently, and the build context being one
agent's directory is what stops a change to one from invalidating another's image or cache. Revisit
only when three agents need the same non-trivial change.

**VM access is root and auto-approved.** The blueprint's keystone was a server-side read-only
identity. The operator chose direct root, and then chose to put `mcp__ssh-manager` in
`permissions.allow` for friction-free operation — so neither the credential layer nor the harness
gates it. Recorded as the repo's most significant accepted risk in
[security-strategy.md](../../../.agentic/docs/security-strategy.md) § 5, together with the
consequence that the Telegram → root-shell prompt-injection chain has no mechanical break.

**Host keys are scanned per run, not pinned.** The committed `known_hosts` inherited from
`bb-trade-agent` was stale and was removed, so CI now `ssh-keyscan`s the host each run. Weaker at
scan time; the restore path is in [cicd.md](../../architecture/cicd.md).

## Follow-ups

- Rebuild the devcontainer and run the full linter sweep via `/task-review`.
- Provision `SSH_PRIVATE_KEY` as a repository secret before the first deploy.
- Re-pin the VM host key once its fingerprint is verified out of band.
- Provision a non-root read-only VM identity — the known hardening for the item above.
- No eval harness ships with the template. The shape that worked is described in
  [patterns/prompts-and-evals.md](../../patterns/prompts-and-evals.md); building it is deferred
  until the first agent needs one.
