---
name: skill-author
description: Use when the user asks to create, edit, or review a `.claude/skills/<name>/SKILL.md` file. Encodes the project's rules for what belongs in a skill vs. a convention file, the required frontmatter shape, the Files-covered + Linters sections that the task-review agent reads, and the writing conventions inherited from `kb/conventions/project.md`.
---

# skill-author

How to author a skill in `.claude/skills/<name>/SKILL.md` so it integrates with this repo's agentic setup.

## What a skill IS (vs. what it ISN'T)

A skill is **generic, transferable tool guidance** — how a tool works, how to invoke it, how to read its output, inline-suppression patterns. If you copied the skill folder into a different project, only the lint-config paths would need updating.

A skill is **not** the right home for:
- Project-specific facts ("the chart lives at `<chart-path>`", "real secrets live in `<secret-store>` path X", "service ports are not all the same"). These belong in [`kb/conventions/<file>.md`](../../../kb/conventions/) — skills link to them.
- Project-wide *operating* rules (what the agent is/isn't allowed to do, when to escalate, ask vs proceed). These live in [`CLAUDE.md`](../../../CLAUDE.md).
- Snapshots of the current repo's content (file counts, dir listings, named files). Those rot the moment the repo changes.
- Long preambles describing the project. The skill description is enough orientation.
- One-time or one-off job machinery (a backfill sweep, a migration runner, a single audit). A skill holds the *recurring* mechanism; a one-time job is a task artefact — a prompt or script in the task folder. (E.g. the [`harvest-lessons`](../harvest-lessons/SKILL.md) skill is the recurring live harvest; the one-time old-thread backfill prompt lives in its task folder, not the skill.)

Rule of thumb: if the same skill, copy-pasted into an unrelated repo, would still make sense after just updating the config path → it's correctly scoped.

## Required structure

```markdown
---
name: <kebab-case-slug>             # MUST match the folder name
description: <one paragraph>        # Explains WHEN to trigger and what the skill covers
---

# <name>

<1–2 line introduction to the tool(s) this skill covers>

## Files covered                    # Required for tool/linter skills
- `**/*.<ext>`
- ...

## Linters                          # Required for tool/linter skills

### <tool> — <one-liner>

```bash
<minimum-parameter command using ${LINT_CONFIGS}/...>
```

<output format notes, severity tier mapping>

## Per-line inline suppressions      # If applicable
<tool's suppression syntax + reason-comment rule>

## Project-specific conventions      # Optional, if a conventions file exists
Link to `kb/conventions/<file>.md`. Do not restate its rules in the skill.

## When the executor runs this
One short paragraph. Link to CLAUDE.md § Verification with linters.
```

### Frontmatter

- **`name`** — kebab-case, single word or hyphenated; matches the folder slug under `.claude/skills/`. Skills get triggered via `/<name>`.
- **`description`** — one paragraph. Includes trigger keywords the model uses to decide when this skill is relevant (file extensions, tool names, common operations). Examples to study: [`new-agent`](../new-agent/SKILL.md), [`shell`](../shell/SKILL.md), [`github-actions`](../github-actions/SKILL.md).

### Files covered

Globs that determine *automatic* applicability. The [`task-review` agent](../../agents/task-review.md) reads this section to decide which skill's linters to run for each changed file. For cross-cutting skills (like [`secrets`](../secrets/SKILL.md)) that aren't file-pattern-scoped, state that and explain when it runs.

### Linters

For each tool the skill covers, give one minimum-parameter command example using `${LINT_CONFIGS}/<file>`. Don't add flags that the config can hold — configs do the rest. Note whether the tool emits JSON / SARIF / text, and map its native severities to the project tiers (blocker, fix-if-touched, nit).

If a tool has *no* JSON output, say so explicitly so the agent doesn't waste effort parsing.

## Writing conventions

Inherit [`kb/conventions/project.md`](../../../kb/conventions/project.md):

- **Comments meager.** Same rule in skill prose as in code — one short line per point, describe purpose, drop multi-paragraph explanations.
- **Don't copy config into the doc.** If the rule lives in the tool's config file or in a conventions file, link to it. Don't restate it.
- **Naming honesty.** Describe what the tool does *today*, not what it might do once we add a hypothetical feature.
- **Scope discipline.** Skill content covers what the tool does and how to call it. Future-proofing belongs in a follow-up task, not in the skill.
- **Investigation rigor.** Don't speculate about tool behavior — verify with the tool's docs or run a quick command.

## Linter-config paths

Skill examples reference `${LINT_CONFIGS}/<config-file>`, never a literal absolute path. The variable is set in the [devcontainer Dockerfile](../../../.devcontainer/Dockerfile). This keeps skills transferable: in another project, only the env var moves.

If a tool needs no config file, omit the `--config` flag from the example.

## Adding a new tool/linter skill: checklist

1. Pick the kebab-case slug (`<tool>` for single-tool skills, `<area>` for multi-tool).
2. Create `.claude/skills/<name>/SKILL.md` with the structure above.
3. If the tool needs a config, add it to [`.agentic/linter-configs/`](../../../.agentic/linter-configs/) and reference it via `${LINT_CONFIGS}/`. Update [`.agentic/linter-configs/README.md`](../../../.agentic/linter-configs/README.md).
4. Pin the tool's version in [`.devcontainer/Dockerfile`](../../../.devcontainer/Dockerfile) — `ARG <TOOL>_VERSION=…` near the other linter ARGs. Use the existing install pattern (release binary / pip / npm).
5. For arch-dependent URLs, use BuildKit's `ARG TARGETARCH` (already declared at the top of the Dockerfile) directly when the asset uses dpkg-style naming; otherwise inline a one-line ternary at the RUN that needs it. Don't re-compute `dpkg --print-architecture` or `uname -m` in the install layer.
6. Update the routing table in [`kb/conventions/README.md`](../../../kb/conventions/README.md) — add the file glob → skill → convention-source row.
7. Update the [`task-review` agent](../../agents/task-review.md) routing table in step 5 of its prompt if the new skill covers a new file pattern.
8. If the tool is genuinely project-specific (config tuned to one repo, rules that don't transfer), the body of the skill should still be tool-generic; the project parts go in a sibling `kb/conventions/<topic>.md` file.

## Reviewing an existing skill

When asked to review a SKILL.md:

- Does it have the required frontmatter (`name`, `description`)?
- For tool/linter skills, does it have **Files covered** and **Linters** sections in the shapes the [`task-review` agent](../../agents/task-review.md) reads?
- Could the same skill make sense in an unrelated project after only changing the container env vars (`${LINT_CONFIGS}`, `${AGENTS_FACTORY}`, `${AGENTS}`, `${KB}`)? If not, scrub project-specific content into a conventions file.
- Are paths referenced via the container env vars (`${LINT_CONFIGS}/...`, `${AGENTS}/...`, etc.) and not literal absolute paths or deep `../<code-repo>/...` relative paths?
- Are inline-suppression examples paired with a reason comment?
- Is severity-tier mapping spelled out for each tool that emits severity?
- Is there a link to project-specific rules in `kb/conventions/<topic>.md` where applicable?

## Anti-patterns

- "Project: <name>. <Long description of the project, the team, the architecture>" preamble — drop, the description field is enough.
- Restating rules from `kb/conventions/<topic>.md` verbatim. Link, don't duplicate.
- Hard-coded absolute paths in shell commands or cross-repo code-spans — use the container env vars defined in [.devcontainer/Dockerfile](../../../.devcontainer/Dockerfile): `${LINT_CONFIGS}`, `${AGENTS_FACTORY}`, `${AGENTS}`, `${KB}`. Skills stay transferable across projects and the Dockerfile is the single source of truth — only the env var moves when paths change.
- Multi-paragraph "Background" sections that read like architecture docs.
- Examples that include flags the config already supplies (`--severity HIGH --severity CRITICAL --soft-fail-on LOW,MEDIUM ...`) — leave those in the config; the example shows the call site.
- Enumerating every file in the repo that matches the skill's globs. The globs themselves are the contract; the listing rots.
