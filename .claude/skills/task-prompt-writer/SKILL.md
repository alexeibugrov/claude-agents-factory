---
name: task-prompt-writer
description: Use when the operator hands over raw, unstructured notes — a problem dump, a Slack paste, a half-formed request — to be turned into a clean task prompt and then executed. Drives the task-prompt-writer subagent to restructure the notes (the mess and the restructuring stay in the subagent's context), surfaces the prompt for confirmation, then executes the task in the same session from the distilled prompt. Triggers on "write a task prompt", "structure this task", "make a task out of this", "turn these notes into a prompt".
---

# task-prompt-writer

Turns raw operator notes into one clean **task prompt** and then runs it — two phases in a single session:

1. **Generate.** The [`task-prompt-writer`](../../agents/task-prompt-writer.md) subagent restructures the messy dump into a tight, structured prompt **in its own context**, so the classify/tighten reasoning and any grounding lookups stay isolated — they never reach the main session.
2. **Execute.** On the operator's go-ahead, the same (main) session runs the task directed at the distilled prompt — it works from the clean brief rather than re-deriving structure from the raw notes.

The split is the point: generation noise stays isolated in the subagent; the executor works from a clean brief. The subagent holds the authoritative generation rules; this skill orchestrates the two phases.

## The format

Every produced prompt has these sections, in order:

```
# Context              what's going on, why, which systems — enough to start cold
# Task                 numbered imperative steps, in order
# Constraints          (optional) hard must-nots: "deploy is not allowed"
# Notes                (optional; rename per task) loose directives / heads-up / PS
# Acceptance criteria  numbered, checkable definition of done
```

`# Notes` is renamed when a sharper word fits — `# Permissions`, `# Heads-up`, `# Working mode`. Omit `# Constraints` / `# Notes` when there's nothing for them. Keep the whole prompt short — ~15–25 lines, not pages.

## How it runs

1. **Generate** — spawn the [`task-prompt-writer`](../../agents/task-prompt-writer.md) subagent, passing the operator's raw notes **verbatim** (don't pre-clean or summarise — the restructuring is the agent's whole job, and it should see the original mess). It returns the formatted prompt plus a short `Gaps & assumptions` block. Because it runs isolated, its tool calls and reasoning never reach the main context — only the finished prompt comes back.
2. **Confirm — ask before executing.** Present the prompt and surface any gaps, then pose an explicit question with the `AskUserQuestion` tool: **execute now**, **edit / fill gaps first**, or **stop with just the prompt**. Do not begin execution until the operator picks *execute* — the subagent can't ask the operator itself (it runs isolated and returns once), so this gate lives here in the main thread. If the agent flagged gaps (missing acceptance criteria, a `<placeholder>`, thin Context), call them out in the question so the operator resolves them first. Small wording tweaks can be edited directly; a substantive change re-spawns the agent with the notes plus the correction.
3. **Execute** — run the task **in this same session**, working from the confirmed prompt. The working context is now the clean, structured brief, not the original dump. Follow the normal project rules for the work itself: non-trivial multi-step work goes through [`task-flow`](../task-flow/SKILL.md); planning-heavy work starts with the [`task-planner`](../../agents/task-planner.md) agent.

## The analysis the agent performs

The "basic analysis" is structural, not investigative:

- Classify each piece of the raw input into the five buckets (a constraint buried in prose → `# Constraints`; a PS → `# Notes`).
- Tighten: cut filler, dedupe, turn rambling prose into numbered steps.
- Preserve load-bearing operator directives verbatim (`CHECK LOGS`, "deploy is not allowed", "stop and ask me").
- Flag gaps (missing AC, vague task, thin context) rather than invent specifics.

The agent does **not** investigate or solve the task — it only writes the prompt that tells the executor to.

## Relationship to task-flow

`task-prompt-writer` shapes the *brief* and then drives execution from it; [`task-flow`](../task-flow/SKILL.md) governs the *lifecycle* of that execution (plan → execute → finalize) when the work is non-trivial. They compose in one session: `task-prompt-writer` produces and confirms the structured prompt, then execution proceeds under `task-flow`'s rules. The [`task-prompt-writer`](../../agents/task-prompt-writer.md) subagent itself never executes — it only writes the prompt; execution is the main session's job.
