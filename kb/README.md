# Knowledge base

How agents get built in this factory. This holds **non-derivable** knowledge — the *why* behind a
decision, the gotcha that cost a day, the rule that is not visible in any single file — not facts
that already live in the code or config.

## The one rule

**Don't duplicate. Point.** Any fact with an authoritative source (a value in `agent_config.yaml`,
an option in `agent/loop.py`, a step in the reusable workflow) must not be copied here. Copying
forks a source of truth and starts a countdown to drift. Write "see `path/to/source`" with a link instead.

The corollary for agents: **an agent's own documentation lives in `agents/<name>/README.md`**, one
page, next to its code. This KB describes the factory; the agent describes itself.

## Layout

- [architecture/](architecture/) — how the factory is put together.
  - [overview.md](architecture/overview.md) — the whole shape in one page. Start here.
  - [agent-anatomy.md](architecture/agent-anatomy.md) — the standard agent: what every agent has,
    and why each piece is not optional.
  - [auth.md](architecture/auth.md) — subscription auth, and the one environment variable that
    silently switches you to per-token billing.
  - [cicd.md](architecture/cicd.md) — one reusable pipeline, one caller per agent; the design
    choices and the failure each one prevents.
  - [ssh-mcp.md](architecture/ssh-mcp.md) — Claude's auto-approved root access to the runtime VM,
    and what does and does not constrain it.
  - [telegram-mcp.md](architecture/telegram-mcp.md) — the read-only Telegram MCP, and treating
    channel text as untrusted input.
- [patterns/](patterns/) — practices that generalise across agents.
  - [tool-design.md](patterns/tool-design.md) — designing the tool surface a model can actually use.
  - [prompts-and-evals.md](patterns/prompts-and-evals.md) — fixing behaviour with prompts and evals
    rather than hardcoded guardrails, and where that rule stops.
  - [lessons.md](patterns/lessons.md) — what the first generation of agents (`bb-trade-agent`)
    taught, with the incident behind each lesson.
- [conventions/](conventions/) — project-specific rules the `.claude/skills/` link out to.
- [runbooks/](runbooks/) — operator procedures.
- [tasks/](tasks/) — one folder per non-trivial task; see the
  [task-flow skill](../.claude/skills/task-flow/SKILL.md).
