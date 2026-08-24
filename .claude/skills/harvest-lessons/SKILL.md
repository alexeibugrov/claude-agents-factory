---
name: harvest-lessons
description: Use at the end of a task (or when the user says "harvest lessons", "what did you learn", "capture feedback", "update your skills from this") to turn the operator's corrections, preferences, and approach improvements from a session into durable rules — routed into the right skill, conventions file, or CLAUDE.md. Runs in the MAIN thread (it already holds the conversation), classifies each lesson, de-dupes against existing rules, and proposes edits for approval before writing them. Also audits every ASK the session made (questions, stop-and-ask escalations, permission/tool gaps) and proposes the config, permission, or rule change that would let the next session proceed without asking — without removing genuine human gates.
---

# harvest-lessons

The mechanism that makes Claude *learn* from the operator instead of being re-told the same thing.
It runs at finalize (and on demand) to **collect → analyse → propose → apply** the session's
feedback into the project's existing persistence layer. It adds no new store — it routes into the
skills / conventions / CLAUDE.md targets that already exist.

## What this captures (and what it does NOT)

**Captures** transferable *rules about how to work*: operator corrections ("no event branching in
reusables"), preferences ("always latest for SAST tool images"), approach improvements ("mirror the
legacy deploy bash to shrink blast radius on a cutover PR"), and working-style guidance.

**Does NOT capture** system documentation — "how the CI / log-shipping / secret-store setup works"
belongs in `kb/` and the project developer wiki, written by
[task-flow](../task-flow/SKILL.md) finalize step 2.
Litmus test: *"how the system works"* → docs; *"a rule Claude should follow next time"* → here.

## Core principle: run in the main thread

The harvest runs in the **main thread**, not a subagent. The main thread lived through the
conversation — it already holds every correction in full. A subagent can't be given *more* context
than that; it would only re-read the transcript from disk at a fidelity loss, with no isolation
benefit. So **do not spawn a subagent for the harvest.** (If a future reader is tempted to "fix"
this into a subagent: don't — this is deliberate.)

## The procedure

### 1. Collect

Gather candidate lessons from, in priority order:

1. **The live conversation** — every place the operator corrected, redirected, or taught you.
2. **The task's `notes.md` → `## Lessons & operator feedback` queue** — the durable list logged
   during execution (see [task-flow](../task-flow/SKILL.md)).
3. **The working-tree diff** — choices the operator approved during human review that imply a rule.
4. **The session transcript on disk, only if the session was long enough to have compacted** —
   compaction silently drops early turns from live context, so recover them from the raw log:

   ```bash
   # current session = most recently written transcript for this project
   ls -t ~/.claude/projects/-workspaces-claude-agents-factory/*.jsonl | head -1
   ```

   Then read/grep that file for `"role":"user"` entries to recover feedback no longer in context.
   Skip this step for short sessions — the live context already has everything.
5. **The session's ASK ledger** — every point where you interrupted the operator: `AskUserQuestion`
   calls, "stop and ask" escalations, permission-gap flags, and blocked-tool / firewall /
   environment-limit asks. Recover the ones dropped by compaction from the transcript (§1.4). Feeds
   the **autonomy pass (§2b)**, not the lessons routing.

### 2. Analyse — classify and de-dupe each candidate

For every candidate, walk this decision tree. The boundary definitions are owned by
[skill-author](../skill-author/SKILL.md) § "What a skill IS (vs. what it ISN'T)" and
[`conventions/README.md`](../../../kb/conventions/README.md) — **read those, don't restate
them here.**

1. **Already covered?** Open the candidate target file and check. If the rule (or a stronger version)
   is already written → **skip**. De-duping is mandatory; re-adding existing rules is noise.
2. **Generic, transferable tool guidance** (true in any project after swapping config paths) →
   a rule in the matching `.claude/skills/<skill>/SKILL.md`. If no skill covers that tool/topic and
   the lesson is substantial → **new skill** via [skill-author](../skill-author/SKILL.md).
3. **Project-specific code/workflow rule** tied to a tool → `kb/conventions/<tool>.md`;
   project-wide but not tool-specific → [`conventions/project.md`](../../../kb/conventions/project.md).
4. **Operating rule** — what Claude may do, when to ask, when to stop, when to escalate →
   [`CLAUDE.md`](../../../CLAUDE.md).
5. **Task-specific / ephemeral / a one-off fact** → **drop.** It stays in `notes.md` / `report.md`;
   it does not earn a skill rule. Over-promoting one-offs rots the rule set.

### 2b. Autonomy pass — turn each ASK into more autonomy next time

The goal: **fewer asks next session.** For every entry in the ASK ledger (§1.5), classify it, then
de-dupe against what's already granted/ruled:

- **Genuine human gate → keep, do not touch.** A decision only the operator can make (which of two
  valid designs, a business/product call), or a deliberately-gated action (PR creation, pushing or
  promoting past the integration branch, touching production, rotating or creating secrets,
  destructive git on a shared ref, starting/stopping a live stack). These asks are *correct* — the
  point is **not** to eliminate them. Note the ones that recur so the gate stays documented, never
  removed.
- **Avoidable friction → propose the change that removes the ask.** Route by cause:
  - *Denied tool call / not-allow-listed tool* → a pre-grant in [`.claude/settings.json`](../../settings.json)
    `permissions.allow`, **only** against the concrete named need and **only** where a server-side or
    behavioural backstop still holds (never move an MCP with no server-side write backstop, like `mcp__ssh-manager`, to `allow`;
    keep present-and-wait gates behavioural). Name the exact tool + why it's safe to pre-grant.
  - *A too-narrow tool/arg allowlist* (a CI `--allowedTools`, an action's `permissions:` block) → the
    config that owns it, widened to what the task actually needed.
  - *A CLI/tool that wasn't installed* → [`.devcontainer/Dockerfile`](../../../.devcontainer/Dockerfile).
  - *A blocked egress / firewall deny* → [`.devcontainer/init-firewall.sh`](../../../.devcontainer/init-firewall.sh).
  - *An ambiguity that was investigable* (asked when evidence on the server / in the repo / a read-only
    probe would have settled it) → an operating rule in [`CLAUDE.md`](../../../CLAUDE.md) or the relevant
    skill: "resolve X by investigation, don't ask." Highest-value class — it turns a reflex-ask into a
    reflex-investigate.

Litmus: *"only the operator could have answered this"* → keep; *"a permission, a config line, a tool,
or a rule would have let me proceed"* → propose that change.

### 3. Propose

Return a single chat message, grouped by target file. Nothing is written yet. For each item:

```text
### .claude/skills/github-actions/SKILL.md
- Lesson: prefer official action > `container:` > `docker run`; `working-directory:` is ignored on
  `uses:` steps so a docker-action tool can't target a nested workspace.
  Insert as: rule "#15 — Tool invocation preference" (verbatim text below).
  <exact text to insert>

### kb/conventions/project.md
- ...

### Autonomy (fewer asks next session)
- ASK "grant me the log-egress host so I can read the failing job" → avoidable (blocked egress).
  Target: `.devcontainer/init-firewall.sh` — allowlist `<host>`. <exact line>
- ASK "which of <config A> vs <config B> for the registry credential?" → avoidable (investigable/decidable).
  Target: CLAUDE.md operating rule — "default to <X>; only ask if <Y>." <exact text>
- Kept as genuine gates (not promoted): PR-body approval before `gh pr create`; production cert rotation.

### Dropped (task-specific, not promoted)
- ...
```

Lead with a one-line summary: "N candidates → X to skills, Y to conventions, Z to CLAUDE.md, W
skipped (already covered), V dropped; A autonomy fixes proposed, K asks kept as genuine gates."

### 4. Apply (after operator approval)

Only after the operator approves do you write the edits — main thread, directly. Items the operator
defers or rejects are dropped. **Never** force-add a rule the operator didn't sign off on. When
adding a numbered rule to a skill, match that skill's existing rule shape and numbering.

Autonomy fixes that **widen a permission or an allowlist** are security-sensitive: apply each only on
**explicit per-item approval**, never on a blanket "yes to all." Operating-rule and tooling fixes
follow the same approval as any other lesson.

## When NOT to run

- Trivial one-shot tasks with no operator feedback — nothing to harvest.
- Mid-task — harvest at finalize, once feedback has settled (mirrors the "defer doc updates to the
  end" rule in [task-flow](../task-flow/SKILL.md)).

## Relationship to the lifecycle

[task-flow](../task-flow/SKILL.md) finalize calls this skill as a mandatory step, after applying the
`notes.md` doc queue and before/alongside documenting the system. The
[`CLAUDE.md`](../../../CLAUDE.md) § Persistence of context and lessons names it as the mechanism for
the routing it describes.
