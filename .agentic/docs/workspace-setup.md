# Workspace wiring

How this repo is mounted, how parallel work gets its own container, and what to check after a
rebuild. The security posture is [security-strategy.md](security-strategy.md).

## One mount, one repo

This is a monorepo, so the devcontainer needs exactly one bind mount: the opened checkout.

```text
<host-parent>/
├── claude-agents-factory/     # the main checkout — mounted at /workspaces/claude-agents-factory
└── tasks/
    └── <task-dir>/            # a per-task clone, same mount target, its own container
```

`${localWorkspaceFolder}` in [devcontainer.json](../../.devcontainer/devcontainer.json) substitutes
to whichever checkout is opened, so one config serves the main checkout and every task container
without edits.

Everything Claude touches lives under that mount, so `.claude/settings.json` needs no
`additionalDirectories`.

## Paths come from the Dockerfile

[.devcontainer/Dockerfile](../../.devcontainer/Dockerfile) is the single source of truth for
`AGENTS_FACTORY`, `AGENTS`, `KB`, and `LINT_CONFIGS`. Docs and skills write `${VAR}` in shell
examples so a move needs one edit rather than a doc sweep. In-repo *references* stay markdown links
— those render on GitHub and click through in VS Code.

## What each file does

| File | Role |
|---|---|
| [claude-agents-factory.code-workspace](../../claude-agents-factory.code-workspace) | VS Code entry point. A single folder (`.`) — deliberately minimal; editor settings belong in `devcontainer.json`. |
| [.devcontainer/devcontainer.json](../../.devcontainer/devcontainer.json) | Mounts, container env, the firewall `postStartCommand`. |
| [.devcontainer/Dockerfile](../../.devcontainer/Dockerfile) | Pinned toolchain, path env vars, and `gh` wired as git's HTTPS credential helper. |
| [.devcontainer/init-firewall.sh](../../.devcontainer/init-firewall.sh) | Default-deny egress, re-run at every container start. |
| [tasks/create_task.sh](../tasks/create_task.sh) · [tasks/delete_task.sh](../tasks/delete_task.sh) | Create/remove a per-task clone and its container. |

## Credentials that persist

Three things must survive both a rebuild and a switch between task containers, so each is a
host-side or named mount rather than container state:

- **`gh` auth** — a fixed-name volume (`claude-agents-factory-gh-config`). One `gh auth login` is
  enough, forever. A `${devcontainerId}`-keyed volume would force a re-login per task container.
- **Claude config/history** — `~/.claude-agents-factory-devcontainer` on the host. Factory-specific
  so it never collides with another project's devcontainer.
- **The VM SSH key** — `~/.ssh/pulse-vm-agent`, mounted read-only. Never committed.

Bash history is deliberately *per*-container (`${devcontainerId}`), so parallel tasks don't
interleave.

## Per-task containers

One container per task branch, each a full clone:

```bash
.agentic/tasks/create_task.sh feat/my-task     # from the MAIN checkout
.agentic/tasks/delete_task.sh <task-dir>       # -f to override the dirty-work guard
```

`create_task.sh` clones **fresh from the remote** (the URL comes from the main checkout's `origin`;
the local checkout may be behind and is never the clone source), branches from `origin/main`, and
opens VS Code on a `vscode-remote://dev-container+<hex>/...` URI so the container is built and
attached automatically. `delete_task.sh` refuses to remove a dir with uncommitted or unpushed work
unless forced.

Durable state flows only through pushed branches and PRs. A task dir is disposable.

## Rebuild rules

- **Dockerfile, mounts, or firewall changed → Rebuild and Reopen in Container.** A plain reopen is
  not enough: `sudo` re-runs the *baked* `/usr/local/bin/init-firewall.sh`, not the working-tree
  copy, so a firewall edit does nothing until the image is rebuilt.
- **`.mcp.json` or `.devcontainer/ssh-manager/*` changed → restart the Claude Code session.** MCP
  children read their config once at startup.

## Verification after a rebuild

```bash
pwd                                  # /workspaces/claude-agents-factory
echo $AGENTS $KB $LINT_CONFIGS       # all under /workspaces/claude-agents-factory
gh auth status                       # authenticated without a fresh login
ruff --version && hadolint --version && gitleaks version && semgrep --version
uv --version
```

Then confirm egress is actually locked: the firewall script's own closing checks must report that
`example.com` is unreachable and `api.github.com` is reachable. If both pass but a tool still can't
reach something, that host needs an explicit allowlist entry — see
[security-strategy.md](security-strategy.md) § Egress firewall.

If `gh auth status` asks for a login after a rebuild, the gh-config volume name changed — check it
is the fixed name and not keyed by `${devcontainerId}`.
