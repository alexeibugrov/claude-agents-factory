# `.agentic/` — agentic helpers

This folder holds everything that makes the agentic workspace *work* but is **not** part of the
configured project itself — kept separate so it doesn't interfere with the project's files. The
project-facing config lives at the repo root and in conventional locations: `.claude/`, `.devcontainer/`,
[.mcp.json](../.mcp.json), [CLAUDE.md](../CLAUDE.md), the `*.code-workspace` file, the `kb/`
knowledge base, and the agents themselves under `agents/`.

## Contents

| Path | What it is |
|---|---|
| [docs/workspace-setup.md](docs/workspace-setup.md) | How the single-mount + per-task-clone wiring works, and a meta-prompt to replicate it elsewhere. |
| [docs/security-strategy.md](docs/security-strategy.md) | The autonomy/security posture: defense-in-depth layers, the read-only-credential golden rule, and the harness `allow`/`ask` gating model. Read before widening any permission. |
| [tasks/create_task.sh](tasks/create_task.sh) · [tasks/delete_task.sh](tasks/delete_task.sh) | Create/remove a per-task clone of this repo under `<parent>/tasks/`, one devcontainer per task branch. Edit the `config` block if you rename the repo or its workspace file. |
| [linter-configs/](linter-configs/) | One config per linter, referenced from the tool skills via the `LINT_CONFIGS` env var (set in the Dockerfile). The indirection keeps skills transferable across projects. Index: [linter-configs/README.md](linter-configs/README.md). |

## Why these are here and not at the repo root

Agentic tooling evolves on a different cadence than the project. Keeping helpers under `.agentic/` means the
working tree (`.claude/` skills, `CLAUDE.md`, `kb/`, `agents/`) stays uncluttered by the machinery, and the machinery can be updated or pulled from an upstream blueprint without touching
project config. The one coupling is the `LINT_CONFIGS` env var, which points the skills at
`linter-configs/` regardless of where it sits — change the path in one place (the Dockerfile) if you move it.
