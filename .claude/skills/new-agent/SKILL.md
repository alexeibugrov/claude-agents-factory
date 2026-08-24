---
name: new-agent
description: Use to scaffold a new Claude Agent SDK agent in this factory — "new agent", "create an agent", "add an agent", "scaffold an agent", "/new-agent". Copies agents/_template into agents/<name>, renames the placeholders, writes the path-filtered CI caller, and drives the interview that turns a template into a specified agent. Also the reference for what a finished agent must contain before it is deployed.
---

# new-agent

Scaffolding a new agent in this factory. The mechanics are a copy and a rename; the value of this
skill is the **interview** that comes first and the **checklist** that comes after, because a
template with the placeholders still in it is not an agent.

## Before scaffolding: settle four things

Ask the operator, in one batch, and do not start writing files until each has an answer. These are
the decisions that are expensive to change once the agent is running:

1. **Name** — lowercase, hyphenated (`price-watcher`). It becomes the directory, the image name
   (`ghcr.io/alexeibugrov/<name>`), the VM directory (`/app/<name>`), the journald tag, and the
   workflow file. One word chosen once, used everywhere.
2. **Trigger** — what starts a run? A poll, an inbound message, a schedule, a queue. This is
   `iter_requests()` in `agent/main.py` and it is the part the template cannot guess.
3. **Tools** — what may the model actually do? Name each tool and mark it read or write. The write
   set becomes `WRITE_TOOLS` in `guards.py`; getting it wrong is how an agent changes something it
   was never meant to touch.
4. **Blast radius** — what is the worst a bad run can do, and what stops it? If the answer is
   "nothing stops it", the agent is not ready to deploy; add a gate, a spend cap, or a dry-run mode.

## Scaffold

```bash
NAME=<name>
cp -R agents/_template "agents/$NAME"
rm -rf "agents/$NAME/.venv" "agents/$NAME"/**/__pycache__
mv "agents/$NAME/agent.env.template" "agents/$NAME/$NAME.env.template"
mv "agents/$NAME/deploy/workflow-caller.yml.template" ".github/workflows/$NAME.yml"
grep -rl 'AGENT_NAME' "agents/$NAME" ".github/workflows/$NAME.yml" | xargs sed -i '' "s/AGENT_NAME/$NAME/g"
```

The Python package stays named `agent` in every agent — the Dockerfile, tests and entrypoint are
then identical across the factory, and only the parts that genuinely differ actually differ.

## Then make it a real agent

Work through these in order. Each one replaces a `TEMPLATE` marker; when `grep -rn TEMPLATE
agents/<name>` is silent, the scaffold is fully specified.

1. **`agent_config.yaml`** — the system prompt (the agent's actual instructions), model, and
   `max_turns`. Leave `allow_writes: false` until the agent has been watched doing the right thing.
2. **`agent/tools.py`** — replace the `echo` placeholder with the real `TOOL_SPECS`. Handlers take
   `(ctx, **args)` and return a dict; they must never raise (a raising handler kills the session).
3. **`agent/guards.py`** — fill `WRITE_TOOLS` with every state-changing tool name.
4. **`agent/context.py`** — the per-run dependencies (clients, handles). Never module globals.
5. **`agent/main.py`** — the real `iter_requests()`.
6. **`<name>.env.template`** — the names of the secrets the VM must supply. Names only, never values.
7. **`tests/`** — at minimum, the config loads and the write gate denies what it should. These are
   the two failures that are silent in production.
8. **`README.md`** — rewrite it. This is the agent's whole knowledge-base page; the factory keeps
   nothing about an agent anywhere else.

## Verify before proposing a deploy

```bash
cd agents/<name>
uv lock && uv sync          # uv.lock MUST be committed — the image builds with --locked
uv run pytest -q
ruff check . && ruff format --check .
docker build -t <name>:local .   # proves the bundled claude CLI check passes
```

Then run `/task-review` over the diff, as for any other change.

## The VM side is not automatic

CI creates `/app/<name>` and ships the compose file and config, but the **secrets file
`/app/<name>/.env.<name>` is operator-provisioned** and Claude never reads it. Give the operator the
exact lines to paste; do not apply them. Full procedure:
[kb/runbooks/new-agent-vm-setup.md](../../../kb/runbooks/new-agent-vm-setup.md).

## Files covered

- `agents/<name>/**` — a new agent's directory
- `.github/workflows/<name>.yml` — its CI caller
- `agents/_template/**` — the template itself (changing it changes every future agent; say so)

## Linters

The scaffold spans several file types, so run each one's skill over what you touched:
[python](../python/SKILL.md) (`ruff`, `pyright`), [dockerfile](../dockerfile/SKILL.md),
[yaml](../yaml/SKILL.md), [github-actions](../github-actions/SKILL.md),
[markdown](../markdown/SKILL.md), and [secrets](../secrets/SKILL.md) over the whole diff — a new
agent is exactly where a real credential gets committed by accident.
