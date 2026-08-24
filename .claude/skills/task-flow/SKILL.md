---
name: task-flow
description: Use whenever starting, executing, or finalizing a non-trivial multi-step task in this project — when the user asks for a "task entry", when applying queued doc/skill updates at end of task, or when adding a new entry to `kb/tasks/`. Encodes the per-task folder structure (`NNN-<slug>-YYYY-MM-DD/{plan.md, report.md}`) and the rule that documentation and skill updates are deferred to the end of the task (tracked via TodoWrite during execution, applied and recorded in `report.md` at finalize). The companion [task-planner agent](../../agents/task-planner.md) writes `plan.md` upfront.
---

# task-flow

The lifecycle Claude follows for non-trivial work in this project. Trivial one-shot edits don't need this. Anything that takes more than ~3 steps, anything involving review-and-iterate with the user, anything that adds or changes an agent, touches CI, or spans multiple files: yes.

The shape solves two real problems from previous tasks:

- **Docs updated mid-execution end up wrong** — the work pivots (we picked an umbrella chart instead of per-component workflows, renamed `monitoring-stack` to `logging-stack`, trimmed values against defaults), and every doc touched before those pivots had to be re-edited. Defer docs to the end.
- **Lessons captured mid-execution get scattered** — review feedback ("no underscore prefix", "no Co-Authored-By trailer", "no event branching in reusables") is cheaper to apply once at the end than each time it surfaces.

## Artefact: one folder per task

```
kb/tasks/
  NNN-<slug>-YYYY-MM-DD/
    plan.md      # pre-execution — written by task-planner agent
    notes.md     # mid-execution scratchpad — queued updates and reverts
    report.md    # post-execution — written at finalize by this skill
```

- One folder per task. Name: `NNN-<slug>-YYYY-MM-DD` — three-digit zero-padded counter, kebab-case slug matching the eventual branch name minus its prefix, ISO date the planner first wrote `plan.md`. Look at the highest existing number under `kb/tasks/`; pick the next.
- `plan.md` — **pre-execution artefact**, authored by the [task-planner agent](../../agents/task-planner.md). May be rewritten as the conversation evolves. Not this skill's responsibility.
- `notes.md` — **execution-phase scratchpad**. As the main agent executes, it appends every doc edit, skill edit, conventions rule, or revert that should be applied at finalize. Free-form bulleted list; consumed by this skill at finalize but kept in the folder afterwards as part of the task record.
- `report.md` — **post-execution artefact** this skill produces. Describes the final state of the task. No plan, no in-progress drafts, no "originally planned vs what shipped" comparison.
- `report.md` is written at the end on user signal ("done", "wrap this up", "write the task entry"). Not mid-execution.

Reviews from the [task-review agent](../../agents/task-review.md) are chat-only — no file lands in the task folder. Iteration history lives in the transcript.

## `report.md` template

```markdown
# NNN — <slug>

**Date:** YYYY-MM-DD

## Task
One paragraph: what the user asked for, why it mattered.

## What was done
Concise file-by-file or component-by-component summary, with markdown links to the repo files and PRs. Stay in this paragraph/short-list shape — no narrative of how we got there.

## Result
What the cluster / repo / CI looks like now. Deployed? Merged? Verified how? Link to CI runs or live-state evidence.

## Comment
Optional. Decisions worth keeping for future readers — "no Loki operator because X", "no OTel Logs migration because Y". One short paragraph per decision, only the ones future readers actually need.

## Follow-ups
Optional. Things deliberately out of scope, tracked elsewhere (usually `kb/improvements.md`). Link them.
```

Sections `Comment` and `Follow-ups` are optional. `Task`, `What was done`, `Result`, and the `Date` line are not.

Use ISO format (`YYYY-MM-DD`) for the date — matches the convention used elsewhere in the project. The date is when the task wrapped up (file written), not when it started; it can differ from the folder's date (which is when the planner created `plan.md`).

## During execution

- **Queue every deferred update in `notes.md`** inside the task folder. As user feedback surfaces a new rule, append a line like `skill: add no-event-branching rule to github-actions`. As you notice that a KB page will need a line added, append it. Same for conventions additions, CLAUDE.md rule additions, things to revert at finalize. This is the authoritative queue — TodoWrite is fine for in-flight progress, but the durable list lives in `notes.md`.
- **Don't touch `kb/` outside the task folder during execution.** Don't touch `.claude/skills/` either. The exception is the file you're working on (agent code, workflows, configs) — that's the work product, not docs.
- The plan lives in `plan.md` and may be iterated. Use the task-planner agent to update it when scope changes — don't hand-edit it from the main agent.
- **Don't run linters per file edit.** The implementation pass focuses on writing the diff. `/task-review` runs every relevant linter once against the full diff and returns a consolidated report — running them piecemeal between Write/Edit calls is churn that adds no coverage. Reach for a linter only to verify a specific fix the reviewer asked for.

## After execution — the review sequence

Once the executor finishes implementing `plan.md`, the path to commit is a strict sequence. Each step has its own purpose; don't merge or reorder them.

1. **`/task-review`** — runs every relevant linter against the full diff and returns a consolidated report (block / fix-if-touched / nit) in chat. This is the single point of linter execution; per-file linting during implementation is not how this project works.
2. **Fix the reviewer's block-tier findings.** Optionally re-invoke `/task-review` to confirm clean. Fix-if-touched and nit findings: surface them in the human-review summary; let the user decide whether to address them now or later.
3. **Human review (mandatory).** Stop. Do not commit. Do not open the PR. Present the work in chat:
   - Summarise the diff: files added, files modified, the shape of each.
   - Surface the `/task-review` verdict, including any findings the user should weigh in on.
   - Call out anything that drifted from `plan.md` (scope adjustments, value changes during execution, decisions that emerged mid-flight).
   - Wait for explicit user approval ("ship it", "looks good, commit", "proceed").
4. **Only after explicit approval:** commit, push, open the PR, and run the CI watch + fix-forward loop per [`git` skill](../git/SKILL.md) (§ PR creation, § CI watch & fix-forward loop). A green check from a step with `continue-on-error: true` is not enough; a green status with empty step logs is not enough; read the relevant step's log content and grep for the expected markers.
5. **After merge: control the deploy run.** The merge to `main` triggers the agent's caller, and *that* run builds the image and mutates the VM. Wait for it, fetch its logs (`gh api .../jobs/<id>/logs`), and verify: no `Error:` lines, the image pushed, and the pipeline's running-container check green. Then confirm the live stack over the SSH MCP (`docker compose ps`, and the agent's journald trace showing a clean start). **The task is finalized only when this post-merge run is green AND the stack is confirmed running.** Merge alone does not close the task.

The human-review gate is mandatory. It exists because Claude can produce diffs that pass automated review yet miss something a fresh reader would catch — a value choice, a phrasing, a deferral that should have been bundled. The user signing off **before** the commit hits git history is cheaper than reverting after.

If the user requests changes during human review, iterate in chat. Substantive changes go back through step 1 (re-run `/task-review`); minor wording tweaks can jump straight to re-presenting.

## At finalize — on user signal

User says "done" / "wrap this up" / "write the task entry":

1. Walk `notes.md`. Apply every queued doc edit and skill edit.
2. **Document the system. This is mandatory, not optional, and it is the most-skipped finalize step.**
   `report.md` records *what was done in this task*; it does **not** make the system understandable to
   the next person. Route the documentation to exactly one place:
   - **A change to an agent → that agent's `agents/<name>/README.md`.** One page per agent, and the
     factory keeps nothing about an agent anywhere else. Update the sections the change touched
     (Architecture, Configuration, Safety, Known gaps); a new agent gets the whole page rewritten
     from the template.
   - **A change to how agents get built → `kb/`.** Architecture pages for the factory's shape,
     `kb/patterns/` for a practice that generalises, `kb/conventions/` for a rule `/task-review`
     should enforce, `kb/runbooks/` for an operator procedure. When a new page is added, add its
     pointer line to the entry-points table in [`CLAUDE.md`](../../../CLAUDE.md).

   Values stay in the source files and the doc points to them (the *Documentation rule* in
   [`conventions/project.md`](../../../kb/conventions/project.md)). Skip this and the system is
   undocumented the moment the task scrolls out of chat — the failure this rule exists to prevent.
3. Write `kb/tasks/NNN-<slug>-YYYY-MM-DD/report.md` using the template above. **Concise.** This file is read at a glance; verbosity defeats the purpose. (The detailed documentation lives in step 2's surfaces — `report.md` stays a terse task record.)
4. Leave `plan.md` and `notes.md` in place alongside `report.md` — the trio is the task record. Do not delete or rewrite `plan.md` or `notes.md` at finalize.
5. **Commit the finalize edits on `feat/<slug>`, then open a PR against `main`.** Reconcile with `origin/main`, push, and open the PR (base `main`, squash-merged after review) — see [`git` skill](../git/SKILL.md) § Finalizing a feature branch and § PR creation via gh. The present-and-wait gate applies: present the PR title and body and wait for explicit approval before `gh pr create`. `main` advances when GitHub merges the PR — **not** by a host-side merge or any hand-advance of the ref.

## Persistence note

Lessons learned go into project skills / `CLAUDE.md` / the task file — **not** into Claude Code's memory system. The memory directory at `~/.claude/projects/-workspaces-claude-agents-factory/memory/` is ephemeral across task clones in this devcontainer; project files persist with the repo.

## When this skill is NOT used

- Single-step tweaks ("fix this typo", "rename this var") — just do it. No task file.
- Read-only investigation ("what does X do?") — no task file.
- Continuing work on an existing task — the file is written/updated when the user signals end-of-task, not before.
