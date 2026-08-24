# TEMPLATE agent

> Copy this directory to `agents/<name>/` to start a new agent — or let `/new-agent` do it, which
> also renames the placeholders and writes the CI caller. Then rewrite this file: it is the agent's
> **single knowledge-base page**, and the factory's rule is that everything about an agent lives here.

*One paragraph: what this agent is for, what triggers it, what it is allowed to change, and who
depends on it. Write this first — if it is hard to state, the agent's scope is not yet decided.*

## Purpose

TEMPLATE — the job this agent does, in the operator's terms rather than the code's.

## Architecture

One run is stateless: a fresh `query()` with a fresh in-process tool server, no session carried
between runs. A crashed or retried run is therefore harmless.

```text
trigger (agent/main.py: iter_requests)
  │  (run_id, prompt)
  ▼
RunContext(run_id, client)          ← per-run binding; never module globals
  │
  ▼
agent/loop.py: run_once
  • build_server(ctx)               → this agent's tools as mcp__agent__*
  • build_write_gate(allow_writes)  → PreToolUse veto on state-changing tools
  • query(prompt, ClaudeAgentOptions(tools=[], setting_sources=[], …))
  • stream → {status, content, tool_executions, cost_usd, num_turns}
  ▼
result → logged to stdout → host journald (tag: <name>)
```

| File | Role |
|---|---|
| [agent_config.yaml](agent_config.yaml) | **Committed, secret-free.** Model, limits, system prompt, agent knobs. Bind-mounted at deploy, not baked. |
| [agent.env.template](agent.env.template) | Names of the secrets the VM's gitignored `.env.<name>` must supply. Values never live in git. |
| [agent/config.py](agent/config.py) | `AgentConfig.load()` — parse and validate; fail fast at startup. |
| [agent/context.py](agent/context.py) | `RunContext` — one run's binding, passed explicitly to every tool. |
| [agent/tools.py](agent/tools.py) | `build_server(ctx)` — the tool surface. Handlers never raise. |
| [agent/guards.py](agent/guards.py) | `build_write_gate()` — sanctioned config-gated deny hook. |
| [agent/loop.py](agent/loop.py) | `run_once()` — one query, reduced to a result dict. |
| [agent/main.py](agent/main.py) | Entrypoint and trigger: `python -m agent.main`. |
| [deploy/docker-compose.yaml](deploy/docker-compose.yaml) | The VM stack: image, journald logging, config mount, security posture. |

## Configuration

Split by whether a value is safe to version:

- **`agent_config.yaml`** — committed. Every deploy re-ships it and the container bind-mounts it
  read-only, so a prompt or model change redeploys without an image rebuild. Because each deploy
  re-ships the file, a hand-edit on the VM is a hotfix only: it is overwritten by the next deploy
  unless the same change also lands in git.
- **`.env.<name>` on the VM** — gitignored, operator-provisioned, never read by Claude. Its shape
  is documented by `agent.env.template`.

Auth is the owner's Claude **subscription** via `CLAUDE_CODE_OAUTH_TOKEN`. `ANTHROPIC_API_KEY` must
stay unset — it takes precedence and silently switches to per-token API billing, so the agent
refuses to start when it is present. See [kb/architecture/auth.md](../../kb/architecture/auth.md).

## Safety

Writes are gated by [agent/guards.py](agent/guards.py): the tools named in `WRITE_TOOLS` are denied
while `agent.allow_writes` is false. Enabling them is a config flip plus a redeploy of that config —
never a code change. The gate holds even under `permission_mode="dontAsk"`.

List here anything else that constrains this agent: rate limits, spend caps, blast radius, what a
bad run could do at worst.

## Develop

```bash
cd agents/<name>
uv sync                 # create/refresh .venv from uv.lock
uv run pytest -q        # tests
ruff check . && ruff format --check .
uv run python -m agent.main   # needs CLAUDE_CODE_OAUTH_TOKEN in the environment
```

Adding or changing a dependency means `uv lock` and committing the updated `uv.lock` — the image
build uses `uv sync --locked` and fails if the lock is stale.

## Deploy

Push to `main` with a change under this directory. The caller at
`.github/workflows/<name>.yml` invokes the shared
[reusable pipeline](../../.github/workflows/agent-deploy.reusable.yml), which builds
`ghcr.io/alexeibugrov/<name>`, ships the compose file and `agent_config.yaml` to `/app/<name>` on
`157.90.18.149`, restarts the stack, and verifies a container is running.

One-time VM setup, and the rationale for the pipeline's design choices, are in
[kb/architecture/cicd.md](../../kb/architecture/cicd.md) and
[kb/runbooks/new-agent-vm-setup.md](../../kb/runbooks/new-agent-vm-setup.md).

```bash
# Read this agent's decision trace on the VM (survives redeploys):
journalctl CONTAINER_TAG=<name> --since '1 hour ago'
```

## Known gaps

*What to distrust about this agent today. Be concrete; an empty section is a claim, not a default.*
