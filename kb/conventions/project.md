# Project conventions

Project-specific rules the generic tool skills under `.claude/skills/` link out to. Agent-specific
rules live in [agents.md](agents.md).

## Documentation

- **Point, don't duplicate.** A value with an authoritative source is referenced, never copied. See
  [kb/README.md](../README.md).
- **Docs are read by Claude, not rendered to a site.** Optimise for a reader who needs the *why* and
  can open the file for the *what*.
- **Defer doc updates to the end of a task.** Plans change mid-execution; queue doc changes and
  apply them once at finalize. See the [task-flow skill](../../.claude/skills/task-flow/SKILL.md).

## Comments

Baseline is the [comments skill](../../.claude/skills/comments/SKILL.md). The carve-out that matters
here: in agent code, **comment the non-obvious safety property**, not the mechanism. `tools=[]`
needs a comment because nothing about it says "this is what stops the agent having a shell";
`WORKDIR /app` does not.

## Task review criteria

Project lenses the [task-review](../../.claude/skills/task-review/SKILL.md) agent applies on top of
the generic skill checks:

- **Scope discipline.** Review against the task's `plan.md` Goal / Out-of-scope.
- **No disguised workarounds.** A skipped test, a swallowed exception, a weakened assertion, or a
  `--no-verify` is a blocker regardless of what it unblocks.
- **Guardrail check.** New behaviour-constraining code in an agent must meet the sanctioned-veto bar
  in [patterns/prompts-and-evals.md](../patterns/prompts-and-evals.md), or it is a finding.
- **Secrets.** Nothing under `.env*`, no key material, no token in a committed file.
