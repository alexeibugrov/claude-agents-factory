---
name: comments
description: Use whenever authoring or editing code comments, in any language, in any project. Covers the universal "minimum comment" discipline plus the rule against gratuitous rewrites of pre-existing comments. Transferable across projects; project-specific carve-outs live in `kb/conventions/project.md` § Comments and similar per-tool conventions.
---

# comments

Universal rules for writing and editing code comments. Applies to every language and every project — these are not project-specific. Per-project overrides (if any) sit in the project's own conventions file.

## Files covered

- Comments in any source file Claude authors or edits: `*.py`, `*.go`, `*.ts`, `*.tsx`, `*.sh`, `*.yaml`, `*.tf`, `*.md`, `Dockerfile`, etc.

## Rules

### 1. Default to no comment

Most code doesn't need a comment. Well-named identifiers, focused functions, and clear control flow do the explaining. Reach for a comment only when the *why* is non-obvious — a hidden constraint, a subtle invariant, a workaround for a specific upstream bug, behavior that would surprise a reader.

Comments that restate what the code already shows are noise. Examples to delete on sight:

```python
# Increment counter
counter += 1

# Loop over users
for user in users: ...
```

**Declarative config (YAML values, HCL, K8s manifests, `.env`) is the same rule — and it's where the temptation is strongest.** A key whose name states its purpose needs no comment, not even a one-liner. `enabled: true` under `metrics:`, `replicaCount: 1`, `path: /oauth2` — all self-evident; a comment on them is noise to delete on sight. A config key earns a comment only when one of these holds:

- **The value is opaque** — a magic number, a cryptic URN, a flag whose effect isn't in its name (`--upstream=static://202`).
- **The setting reads as a mistake** without the reason — a deliberately-permissive toggle, a doubled-looking string, an unusual-but-correct value a reviewer would otherwise "fix" (`enabled: true` on basic-auth that is intentionally kept).
- **A plausible edit would silently break something** — a constraint tying this value to another (`must stay below the token TTL`), or a structural form that must be preserved (`list, not map — repeated keys`).

If none hold, delete it.

```yaml
# Not OK — restates the key
# Enable the service monitor
serviceMonitor:
  enabled: true

# OK — the value is opaque and names a real cross-component constraint
# Must stay below the IdP's access-token TTL.
cookieRefresh: 10m
```

### 2. One short line is the target

When a comment is warranted, one short line. Two if the *why* genuinely needs a second clause. Three is a smell — the code probably needs renaming or restructuring instead.

```python
# Not OK — wall of explanation
# This function takes a list of users and filters out those who haven't
# verified their email, because we need to send the welcome email only
# to verified users. The verification field was added in migration 0042
# and is stored as a boolean column on the users table.
def verified_users(users): ...

# OK — one line; the rest is in the verification migration's commit message
# Filter to email-verified only.
def verified_users(users): ...
```

**Place the one line inline — trailing the code it annotates, not on the line above.** A trailing comment stays bound to its line and survives reordering; a comment parked on the line above drifts from what it describes. Reserve the above-the-line position for a comment that introduces a multi-line block, or that explains something with no line to trail — an *absent* option, a section heading.

```yaml
# Not OK — parked above a single key
# Must stay below the IdP's access-token TTL.
- --cookie-refresh=10m

# OK — trailing, bound to the value
- --cookie-refresh=10m  # Must stay below the IdP's access-token TTL.
```

In YAML, leave **two spaces** before the `#` — yamllint's `min-spaces-from-content` defaults to 2, so a single space lints as a warning.

### 3. Comment the *why*, not the *what*

Code already says what it does. Comments earn their place by saying *why* the code does it that way: the upstream bug being worked around, the timing requirement, the invariant being preserved, the option that was tried and rejected.

```bash
# Not OK — restates the command
# Wait 5 seconds, then check the pod status
sleep 5 && kubectl get pods

# OK — explains the why
# Wait for the operator's reconcile loop (default 5s) before checking.
sleep 5 && kubectl get pods
```

### 4. Don't reference the current task, PR, or fix

Comments are for the long-lived state of the code. They are not commit messages and they are not PR descriptions. Don't write `# added for the X flow`, `# fixes issue #123`, `# part of the auth migration`, or `# used by service Y`. Those facts belong in the commit / PR; in the code they rot the moment the task is forgotten.

### 5. Provenance and decision rationale belong outside the code

A comment block saying where a file came from ("vendored from upstream X"), how it was produced ("re-templated from `kubectl get …` on 2026-05-22"), or why a design was picked ("trade-off: A vs. B, picked A because…") tells the reader nothing they need to *read the code*. Provenance is recoverable from `git log` + the chart's `description:` / module path. Rationale lives in commit messages, PR descriptions, the project's task folder (`kb/tasks/`), and ADRs. In the code these comments rot — the moment the source moves or the decision becomes irrelevant, the comment is wrong.

If a particular line is surprising and a reader needs a hint, annotate *that line*, with only the *why*.

**And don't *point* at those out-of-code locations from a comment either.** A `# see <plan>.md §3` or `# Design: <task-folder>/…` pointer dangles in any repo that doesn't ship those docs — or that is more public than them — and it leaks internal structure. If a line needs a hint, give the *why* inline; never a path to an internal or not-yet-public doc.

```yaml
# Not OK — paraphrases the plan / commit message
spec:
  # spec is re-templated from the LIVE Cluster, including the operator-defaulted fields.
  # Pinning all live fields makes the adopting `helm upgrade --take-ownership` a no-op
  # on `.spec`. Trade-off: future operator default changes won't propagate transparently…
  affinity:
    podAntiAffinityType: preferred

# OK — the spec speaks for itself
spec:
  affinity:
    podAntiAffinityType: preferred
```

This applies even when the comment feels like it's "saving the next reader's time." Most often it isn't — the next reader is reading the code to understand the *current* state, not the migration that produced it; the diff and `git blame` answer "how did this get here?" if they ever need to ask.

### 6. File headers: 1–3 lines max

A file-header comment can describe purpose if the filename doesn't carry it. Cap at three lines. Anything longer becomes a mini-doc that drifts; put it in `README.md` or a doc file. A file header is also a magnet for Rule 5 violations — narrating *why this file exists* in terms of the task that introduced it. Keep the header to *what the file is for*, not the project history that produced it.

### 7. Section dividers are labels, not narration

`# ── helpers ──` is a navigation aid in a long file. Don't follow it with a paragraph explaining what's in the section. If the section needs an explanation, the section is too large or the function names don't carry weight.

### 8. **Don't rewrite existing comments without a substantive reason**

If a comment isn't wrong, stale, or misleading, leave it. Rewording for style — making it match the rules above retroactively — is churn. The original author chose those words; respect that choice unless there is real cause to change them.

Substantive reasons to edit an existing comment:

- The comment **references code that no longer exists** (deleted function, removed branch, renamed variable).
- The comment **contradicts current behavior** (says "returns nil on error" when the code now panics).
- The comment **misleads a fresh reader** (claims an invariant that doesn't hold; describes the *what* in a way that masks a subtle *why*).
- The surrounding code is being **rewritten anyway** and the existing comment doesn't survive the rewrite.

Not substantive:

- "It's too long" → leave it. Rule 2 governs new comments; it isn't a license to retroactively prune.
- "It restates what the code does" → leave it unless you're already touching those lines for another reason.
- "I'd phrase it differently" → strong signal you shouldn't edit it.

This rule trades a small amount of comment-quality drift for stable history. The cost of a stylistic rewrite in an unrelated PR — noisy diff, harder review, lost authorial intent — outweighs the marginal improvement.

### 9. When in doubt

Delete it. If the code becomes unreadable without it, fix the code (rename, extract, reorder) before reaching for a comment again.

## Project-specific overrides

If a project carries its own Comments conventions in `<repo>/kb/conventions/project.md` (or equivalent), read those alongside this skill. Project rules win on conflict; the skill provides the baseline.

## When the executor runs this

Whenever editing source files where a comment is added, removed, or changed. Reviewers ([`task-review` agent](../../agents/task-review.md) and similar) check both new comments and untouched existing comments — flagging gratuitous rewrites of existing comments is part of the rubric.
