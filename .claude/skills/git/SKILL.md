---
name: git
description: Use whenever doing git work in this project — staging, committing, pushing, force-push attempts, opening or updating PRs, or watching a CI run and fixing forward. Encodes project-specific overrides of harness defaults (most notably: NO Co-Authored-By trailer) and the fix-forward / no-reset / no-amend discipline.
---

# git

Project rules for git operations in this repo. Operating rules (what Claude can/can't do) live in [`CLAUDE.md`](../../../CLAUDE.md) § Git; commit-message and trailer conventions in [`kb/conventions/git.md`](../../../kb/conventions/git.md). This skill restates them with the rationale Claude needs when the rule is actually about to be violated, plus the auth quirks specific to the dev environment.

## Hard rules — override harness defaults

1. **No `Co-Authored-By: Claude` trailer.** The Claude Code harness's default git-commit flow ends every message with a `Co-Authored-By: Claude Opus <noreply@anthropic.com>` line. **Omit it.** The user does not want AI co-author attribution on commits in this project. Write commit messages without the trailer; ignore the harness's suggested template on this one specific point.
   ```
   # CORRECT
   git commit -m "price-watcher-agent"

   # WRONG (do not include this trailer)
   git commit -m "$(cat <<'EOF'
   ...
   Co-Authored-By: Claude <noreply@anthropic.com>
   EOF
   )"
   ```

2. **Same commit message for every commit on a branch.** Use the branch name minus its prefix (`feat/`, `chore/`, `fix/`, `bugfix/`, etc.) as the commit message. *Every* commit on that branch — initial, follow-up fixes, reverts of TEMP changes — uses the same message. Example: on `feat/price-watcher-agent`, every `git commit -m "..."` is `git commit -m "price-watcher-agent"`. The PR is squash-merged, so individual messages collapse anyway; uniform messages make the in-progress branch history readable as "work on X" rather than a noisy conventional-commits trail that no one reads after squash.

3. **Fix-forward, don't reset or amend pushed commits.** When a pushed commit needs a fix (broken YAML, typo, wrong indent), add a NEW commit on top. Never:
   - `git commit --amend` + force-push, or
   - `git reset --soft HEAD~1` to redo the previous commit.
   This holds even on a solo `feat/*` PR branch with one commit. Reason: the auto-classifier blocks force-pushes anyway, and amend/reset workflows create stale-info failures with `--force-with-lease`. The fix-forward path is faster, simpler, and preserves real history.

4. **Force-push: never, unless the user explicitly authorizes the specific case.** Includes `--force` and `--force-with-lease`. Never on `dev`/`main`. Never on shared branches. Even on solo branches, prefer additive commits per rule 3.

5. **Never push directly to `main`.** Open a PR.

6. **Pull base into branch before every push.** Fetch + merge `origin/main`, resolve any conflicts, commit the merge with the same branch-minus-prefix message, *then* push. Don't `git pull --rebase` — rebase rewrites local history and collides with rule 3.

   ```
   git fetch origin main
   git merge origin/main --no-edit
   # if conflicts: edit, `git add` the fixed files, then `git commit -m "<branch-minus-prefix>"`
   git push origin <branch>
   ```

   Skipping this means CI runs against a stale base, and conflicts with sibling PRs surface only at merge time, after the reviewer has already approved.

## Bash cwd does not persist

The Bash tool **does not preserve cwd between invocations**. A `cd` at the start of one call is gone
by the next, and a later `git commit` runs against whatever the harness's default cwd happens to be.

For any git command whose result depends on location, chain the `cd` into the same invocation
(`cd ${AGENTS_FACTORY} && git status`) or pass `-C` explicitly. For destructive operations (commit,
push, reset, branch ops) include `pwd && git status` in the same invocation. The failure mode is
silent, so verifying after the fact is painful.

## Finalizing a feature branch (PR to main)

Task branches finalize the same way every time: push the `feat/*` branch and open a PR against `main`, squash-merged after review — see [`task-flow` skill](../task-flow/SKILL.md) § At finalize. `main` advances when GitHub merges the PR, not by a host-side merge.

Before pushing, reconcile the branch with its base per § *Pull base into branch before every push* (fetch + merge `origin/main`, same branch-minus-prefix commit message). Then push and open the PR per § *PR creation via gh* — base `main`, the present-and-wait gate applies.

**The old local "merge into `main` on the host" flow is retired.** Now that there is a remote, do **not** advance `main` by hand: no host-side `git merge feat/<slug>` into `main`, no `git update-ref`, no `git fetch . feat/<slug>:main`, and no scratch checkout added just to merge from inside the devcontainer. Each of those bypasses review and can leave the host checkout's index silently desynced from the new HEAD. The PR is the only path that advances `main`.

## HTTPS push

`git push -u origin <branch>` works directly. The system-level `gh auth git-credential` helper handles GitHub HTTPS auth.

**Do not prefix any git or gh command with `GIT_CONFIG_GLOBAL=/dev/null`** — the harness classifier blocks it as a credential-config bypass, and it doesn't fix anything (no `insteadOf` rule is in play).

## PR creation via gh

**Mandatory pre-flight: present the title and body to the user, wait for explicit approval, then invoke `gh pr create`.** This gate is *behavioural*, not settings-driven: it holds in **every** permission mode, independent of the `ask` rule on `gh pr create` in [`.claude/settings.json`](../../settings.json) (a classifier could clear that rule in `auto` mode; the behavioural gate must not depend on it). Quote the exact `--title` and `--body` you intend to pass; wait for "ship it" / "approved" / equivalent; only then run the command. Never infer approval from upstream context (e.g. "the PR description was discussed earlier"). The user reads the description in chat and signs off explicitly. This rule exists because `gh pr create` is the visible artefact of the work — title and body land in `git log` after squash-merge and read poorly when AI-generated phrasing isn't checked by a human first.

- `gh pr create --base <base> --head <branch> --title "<title>" --body "<one-line idea>"`.
- The base is always `main`.
- After push, give it ~5-10s before listing runs (`gh run list --branch <branch>`); the run may not appear instantly.
- `gh run view <id>` shows summary; `gh api repos/<owner>/<repo>/actions/jobs/<job_id>` shows step-by-step status when the `--log` flag returns "log not found" (which happens on quickly-failed runs).

### PR title and description style

**Title** — the branch name minus its prefix, same as the commit message. On `feat/price-watcher-agent` the title is `price-watcher-agent`.

**Description** — *one sentence* describing the main idea of the PR. Not a story of the work, not a per-file recap, not a test plan, not an adoption-strategy explainer. If the PR has several genuinely distinct major changes, a short bulleted list — one line per change, no detail under each. Reviewers read the diff and the linked task plan for specifics; the description points at "what is this PR about", nothing else.

```
# Good (single idea):
gh pr create --title "price-watcher-agent" \
  --body "Add the price-watcher agent and its CI caller."

# Good (multi-change, short list — only when the PR really has multiple ideas):
gh pr create --title "price-watcher-agent" --body "$(cat <<'EOF'
- Add the price-watcher agent and its CI caller.
- Add a running-container check to the reusable deploy job.
EOF
)"

# Bad — story / per-file recap / test plan / adoption strategy:
gh pr create --title "price-watcher-agent" --body "$(cat <<'EOF'
## Summary
- New caller workflow...
- Config bind-mounted rather than baked...
## Adoption strategy
Straight redeploy — stack name unchanged...
## Test plan
- [ ] CI builds the image...
EOF
)"
```

Rationale: PRs in this repo squash-merge. The title becomes the squashed commit subject; the description becomes its body. Long descriptions become noise in `git log`. The detailed reasoning lives in the diff and in `kb/tasks/NNN-<slug>-YYYY-MM-DD/plan.md` — link the plan from the PR description only if a reviewer truly needs it.

## CI watch & fix-forward loop

After pushing a branch and opening the PR, the loop is: wait for CI → inspect the result → either declare done or fix-forward. Concrete commands:

### 1. Wait for the matching run to complete

`gh run list` returns runs in order of recency. Don't assume the first row is yours — multiple PRs on the same branch family can run concurrently. Match by your HEAD SHA:

```bash
SHA=$(git rev-parse HEAD)
until gh run list --branch <branch> --limit 5 \
    --json status,headSha,databaseId --repo <owner>/<repo> 2>/dev/null \
  | jq -e ".[] | select(.headSha==\"$SHA\" and .status==\"completed\")" >/dev/null; do
  sleep 10
done
```

Run this with `run_in_background: true` so the rest of the work continues while CI runs. The harness notifies you when the `until` loop exits.

### 2. Read the conclusion *and* annotations — success isn't always success

```bash
RUN_ID=$(gh run list --branch <branch> --limit 5 \
   --json headSha,databaseId,conclusion --repo <owner>/<repo> \
  | jq -r ".[] | select(.headSha==\"$SHA\") | \"\\(.databaseId) \\(.conclusion)\"")
gh run view "${RUN_ID% *}" --repo <owner>/<repo>
```

Specifically check the **ANNOTATIONS** block in `gh run view`. Steps marked `continue-on-error: true` show `success` in the JSON even when their action errored; the annotation is the only signal. Common offenders: PR-comment posters that hit argv-size limits, retry-wrapped curls that exhausted attempts.

### 3. Read the log content of the step that matters — every time

**CI status `success` is necessary, never sufficient.** A step with `continue-on-error: true` can fail silently. A step can be skipped without you noticing. A workflow can complete with empty step logs if a tool errored on stdout-redirect setup. The only way to know what actually happened is to read the relevant step's log content and grep for the expected markers of the operation.

The reliable method: `gh api repos/<owner>/<repo>/actions/jobs/<job-id>/logs`. `gh` follows the 302 redirect into Azure Blob Storage internally and streams the raw log content to stdout. Two steps — list jobs of the run, then pull the matching job's log:

```bash
# 1. Find the job ID(s) for the run.
RUN_ID=<run-id>
gh api "repos/<owner>/<repo>/actions/runs/$RUN_ID/jobs" \
  --jq '.jobs[] | "\(.id)\t\(.name)\t\(.conclusion)"'

# 2. Pull a specific job's log content. Writes raw text — no zip, no JSON.
JOB_ID=<job-id>
gh api "repos/<owner>/<repo>/actions/jobs/$JOB_ID/logs" > /tmp/job.log

# 3. Grep for what the task expected to see. Examples:
grep -E "Successfully pushed|digest: sha256" /tmp/job.log     # image build+push
grep -E "No running container after deploy" /tmp/job.log      # the deploy verification gate
grep -E "PASS|FAIL|FAILED|Error:" /tmp/job.log                # test markers
```

The log lines are prefixed with `<RFC3339-timestamp>Z `; strip it with `cut -d' ' -f2-` when the prefix gets in the way.

**Don't use `gh run view <id> --log`.** Empirically it returns exit 0 with zero output in this devcontainer even when the underlying log is reachable. Use the `gh api .../jobs/<id>/logs` path above. (If a future gh release fixes this, the convenience command can come back.)

If `gh api` returns empty too, the redirect target is firewall-blocked — see § Environment limits / blocked tools in [`CLAUDE.md`](../../../CLAUDE.md). **Stop and ask; don't conclude "no logs" from silence.**

### 4. Verify the side effects, not just the logs

Logs prove the workflow did what it logged. Side effects prove reality matches:

```bash
# PR comment posted?
gh api repos/<owner>/<repo>/issues/<pr-number>/comments | jq 'length, .[0].body[0:200]'

# Deploy actually landed? Check the stack and its log trace on the VM.
# See the ssh-mcp-server skill — every call prompts, by design.
```

### 5. If something failed: fix-forward, same commit message, push

```bash
# Edit the offending file.
git add <files>
gitleaks protect --staged --config=$LINT_CONFIGS/gitleaks.toml --exit-code=1
git commit -m "<branch-minus-prefix>"
git push origin <branch>
```

Two things to know about the re-trigger:

- **Reusable-workflow edits do re-trigger callers, even though the caller's `paths:` filter doesn't list the reusable.** GitHub re-evaluates path filters against the cumulative PR diff (not just the head commit); any PR that already contains a matching file keeps running its caller on every push. Useful for fix-forward; surprising in isolation.
- **A failed deploy leaves the previous container running.** `docker compose up -d` only replaces a container once the new image is pulled, so a pull failure is a no-op rather than an outage. A container that starts and then crash-loops is the dangerous case — that is what the pipeline's running-container check exists to catch.

### 6. Loop, then continue — pre-merge done ≠ task done

Re-enter step 1 with the new SHA. The **pre-merge** PR-CI is done when its run is green and the relevant step's log content matches expectations.

**After merge, repeat steps 1-4 for the deploy run.** The merge to `main` triggers the agent's caller, and *that* run is what builds the image and mutates the VM. Its log content — plus the running-container check at the end — is what proves the deploy succeeded. Pre-merge green is not deploy green. Verify both.

When *both* the PR-CI run and the post-merge apply run are green, their log contents confirm the expected outcome, and the cluster side effects match the plan's *Validation* table, then the work is done. Update the task's `ci-loop-observations.md` with anything that tripped up the loop; finalize per the [`task-flow` skill](../task-flow/SKILL.md).

## When in doubt

- Verify cwd (`pwd && git status`) before any destructive op.
- Verify the commit message has no Co-Authored-By trailer before invoking `git commit`.
- Read the existing remote state (`git log <remote>/<branch> --oneline`) before deciding between fix-forward and amend — and even then, choose fix-forward.

## Pre-commit secret scan

Before every commit, scan staged changes for accidentally-staged credentials. See the [`secrets` skill](../secrets/SKILL.md) for full guidance; the one-liner is:

```bash
gitleaks protect --staged \
  --config=${LINT_CONFIGS}/gitleaks.toml \
  --report-format=sarif --report-path=/tmp/gitleaks.sarif --exit-code=1
```

Non-zero exit = a finding. **Do not commit until investigated.** Real leak → rotate the credential first (secret-store entries propagate to consumers — coordinate per [`CLAUDE.md`](../../../CLAUDE.md) § Secrets); false positive → add an allowlist entry to [`.agentic/linter-configs/gitleaks.toml`](../../../.agentic/linter-configs/gitleaks.toml) with a reason.

## Project-specific conventions

Read [`kb/conventions/git.md`](../../../kb/conventions/git.md) for the commit-message conventions (no `Co-Authored-By` trailer, same message per branch, no committed secrets). The [`task-review` agent](../../agents/task-review.md) consults both this skill and the conventions file when reviewing commits.
