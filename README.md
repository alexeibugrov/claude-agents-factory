# claude-agents-factory

A monorepo for building, shipping, and running **Claude Agent SDK** agents — together with the
agentic setup that builds them.

Adding an agent is a directory and a CI caller file. Everything else — the image build, the deploy to
the VM, the safety posture, the linting, the review loop — is already wired.

## What's here

| Path | What it is |
|---|---|
| [agents/](agents/) | One self-contained agent per directory. [`_template/`](agents/_template/) is the canonical one. |
| [kb/](kb/) | How agents get built: architecture, patterns, conventions, runbooks, task records. |
| [.claude/](.claude/) | Skills and subagents — the review loop, the task lifecycle, `/new-agent`. |
| [.devcontainer/](.devcontainer/) | The sandbox Claude works in: pinned toolchain, default-deny egress. |
| [.agentic/](.agentic/) | Linter configs, per-task container scripts, system docs. |
| [.github/workflows/](.github/workflows/) | One reusable build+deploy pipeline, one caller per agent. |

## Getting started

1. Open the repo in VS Code → **Dev Containers: Reopen in Container**.
2. `gh auth login` once (it persists across rebuilds and task containers).
3. Read [kb/architecture/overview.md](kb/architecture/overview.md), then
   [kb/architecture/agent-anatomy.md](kb/architecture/agent-anatomy.md).

## Building an agent

Ask Claude for `/new-agent`. It interviews you for the four decisions that are expensive to change
later — name, trigger, tool surface, blast radius — scaffolds from
[agents/_template/](agents/_template/), and writes the path-filtered CI caller.

```bash
cd agents/<name>
uv sync
uv run pytest -q
uv run python -m agent.main     # needs CLAUDE_CODE_OAUTH_TOKEN
```

Merging to `main` builds `ghcr.io/alexeibugrov/<name>` and deploys it to `/app/<name>` on the runtime
VM. The one manual step is the VM's secrets file —
[kb/runbooks/new-agent-vm-setup.md](kb/runbooks/new-agent-vm-setup.md).

## How it stays safe

- **Agents run on the owner's Claude subscription**, never an API key; an agent refuses to start if
  `ANTHROPIC_API_KEY` is set. [kb/architecture/auth.md](kb/architecture/auth.md)
- **Agents get no built-in tools** — no shell, no file access, no web. Only the tools they declare.
- **State-changing tools are denied until `allow_writes` is flipped in config**, by a hook that holds
  even under auto-approval. [kb/architecture/agent-anatomy.md](kb/architecture/agent-anatomy.md)
- **Secrets never enter git or an image.** They are operator-provisioned on the VM, and Claude is
  denied from reading them.
- **The devcontainer's egress is default-deny**, so reaching a new external system is an explicit,
  reviewable change. [.agentic/docs/security-strategy.md](.agentic/docs/security-strategy.md)
- **Root VM access via MCP is auto-approved** — a deliberate speed-over-friction choice, with the
  residual risk written down rather than glossed. [kb/architecture/ssh-mcp.md](kb/architecture/ssh-mcp.md)

Operating rules for Claude are in [CLAUDE.md](CLAUDE.md).
