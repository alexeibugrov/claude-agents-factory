# The factory in one page

A monorepo that builds, ships, and runs Claude Agent SDK agents, with the agentic tooling that
builds them living alongside the agents themselves.

## Shape

```text
claude-agents-factory/
  .claude/  .devcontainer/  .mcp.json   ← the harness Claude works inside
  .agentic/                             ← linter configs, task-dir scripts, system docs
  kb/                                   ← this knowledge base: how agents get built
  agents/
    _template/                          ← the canonical agent; /new-agent copies it
    <name>/                             ← one self-contained agent
      README.md                         ← THE documentation for that agent
      agent/  tests/  deploy/
      Dockerfile  pyproject.toml  uv.lock  agent_config.yaml
  .github/workflows/
    agent-deploy.reusable.yml           ← the one pipeline
    <name>.yml                          ← one path-filtered caller per agent
```

Three properties are load-bearing, and each is a deliberate trade:

**Agents are self-contained.** No shared library, no cross-imports. The build context is
`agents/<name>/`, so one agent's change can neither enter another's image nor invalidate its cache,
and a broken agent cannot break a working one. The cost is duplication: the same loop skeleton
appears in every agent. That is accepted — the skeleton is small and stable, and drift between
copies is a smaller problem than coupling between agents that must never fail together. Revisit
only when three agents have proven they need the *same* non-trivial change.

**Config ships separately from the image.** `agent_config.yaml` is not baked. CI `scp`s it to the
VM on every deploy and the container bind-mounts it read-only, so a prompt or model change is a
seconds-long redeploy instead of a rebuild, and a bad prompt can be reverted on the VM immediately.
The mirror of that: an edit made only on the VM is silently overwritten by the next deploy.

**One pipeline, many callers.** Every agent deploys through the same reusable workflow. A fix to
the pipeline reaches all agents at once; a new agent is a caller file, not a new pipeline.

## One run

Runs are stateless: one `query()`, a fresh tool server, nothing carried over. See
[agent-anatomy.md](agent-anatomy.md).

## Runtime

All agents run as separate docker-compose stacks on one VM, `157.90.18.149`, each in `/app/<name>`
with its own image, config, secrets file, and state. They share the host and its journald, nothing
else. Claude reaches the VM over SSH MCP for inspection ([ssh-mcp.md](ssh-mcp.md)); CI reaches it
with a separate deploy identity ([cicd.md](cicd.md)).

## Boundaries

The devcontainer is the security boundary for development: egress is default-deny
([init-firewall.sh](../../.devcontainer/init-firewall.sh)), so reaching a new external system is an
explicit, reviewable allowlist edit. The write gate in each agent is the security boundary for
runtime. Neither is a substitute for the other.
