---
name: task-review
description: Use after the executor finishes implementing plan.md, and before every commit during a CI fix loop. Spawns the task-review subagent to flag mechanical violations of project conventions, CLAUDE.md operating rules, tech-skill rules, and disguised workarounds. User-invocable as /task-review.
---

# task-review

User-invocable handle for the [`task-review` agent](../../agents/task-review.md). The agent does the work; this skill is the thin orchestrator.

## When to invoke

- After the executor finishes implementing `plan.md` — before asking the user to review. Don't invoke on partial work.
- Before every commit during a CI fix loop. If the verdict contains `blocker` items, do **not** commit. Address them or escalate.

Both triggers are encoded as operating rules in [`CLAUDE.md`](../../../CLAUDE.md); the user invokes the skill on demand.

## How

1. Spawn the `task-review` subagent. Pass it:
   - `$ARGUMENTS` (optional) — path to the active task folder. If omitted, the subagent locates the highest-numbered folder under `kb/tasks/` matching today's date.
   - Whether this invocation is pre-commit during a CI fix loop. Include that context so workaround detection is weighted accordingly.
2. The subagent returns its verdict as a chat message — no file written.
3. Present the message to the user verbatim.
4. **Do not auto-apply fixes.** The user decides which findings to address. When fixes land, the user invokes the skill again — re-review is a separate run.
5. If the verdict contains `blocker` items in a pre-commit context, do not proceed with the commit.

## Why skill + subagent

Same shape as `task-flow` → `task-planner`. The subagent has its own context, so the full diff and the loaded rule files don't pollute the main thread — important during a CI fix loop where main is already heavy with CI logs and fix iterations.

The subagent is also reusable: a future delivery-verification agent will invoke it as one of its checks without going through this skill.

## When NOT to invoke

- Read-only investigation ("does X work?") — no diff to review.
- Trivial one-line edits — review overhead outweighs the win.
- Mid-edit, before the chunk is logically complete — review at a checkpoint, not in the middle of a thought.
