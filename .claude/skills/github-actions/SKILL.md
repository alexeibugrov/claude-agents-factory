---
name: github-actions
description: Use when authoring or modifying GitHub Actions workflows in this repo (`.github/workflows/`) — the reusable agent build/deploy pipeline or a per-agent caller. Enforces the reusable-plus-callers shape, pinning, and secret hygiene. Project-specific overrides live in `kb/conventions/project.md`.
---

# github-actions

Workflows live in [.github/workflows/](../../../.github/workflows/). There are exactly two kinds,
and the distinction is the whole design:

- **[agent-deploy.reusable.yml](../../../.github/workflows/agent-deploy.reusable.yml)** — the one
  pipeline. All build and deploy logic lives here.
- **`<agent>.yml`** — one caller per agent. A caller says *which* agent and *when*, and nothing else.

Rationale and the failure each design choice prevents:
[kb/architecture/cicd.md](../../../kb/architecture/cicd.md).

## Rules

1. **Logic goes in the reusable, never in a caller.** A caller that grows a `run:` step is a fix
   that will not reach the other agents. Move it into the reusable behind an input.
2. **Convention over inputs.** The reusable derives image name, build context, VM directory, compose
   file, and config path from `inputs.agent`. Add an input only when a real variant needs it, and
   give it an empty default that falls back to the convention:
   `${{ inputs.deploy_dir || format('/app/{0}', inputs.agent) }}`.
3. **Callers are path-filtered** to `agents/<name>/**`, their own file, and the reusable. Without
   this every agent rebuilds on every push.
4. **Pin third-party actions to a full commit SHA**, with the version in a trailing comment. A
   mutable tag is an unreviewed code path with repository access. `zizmor` flags unpinned uses.
5. **`persist-credentials: false` on every `actions/checkout`.** The default leaves a usable token in
   `.git/config` for every later step.
6. **Least-privilege `permissions`, declared explicitly.** A caller must grant `packages: write`
   because it sets the `GITHUB_TOKEN` ceiling for the reusable — a nested job cannot exceed its
   caller's grant, and the failure is a validation-time rejection, not a runtime error.
7. **Secrets never reach argv or logs.** Pipe them on stdin (`<<< "$TOKEN"`), pass them through
   `env:`, never interpolate `${{ secrets.* }}` directly into a `run:` script body — that inlines the
   value into the shell command, where any `set -x` or error trace prints it.
8. **Concurrency at two levels.** The caller groups per ref (`${{ github.workflow }}-${{ github.ref }}`,
   `cancel-in-progress: false`) so a queued run never interrupts an in-flight deploy. The reusable's
   deploy job carries a **constant** group, because the VM is one shared resource across all callers.
9. **Anything consequential is `workflow_dispatch`, not a push trigger.** Promoting an image to a
   production stack is a deliberate act, never a side effect of merging.
10. **Verify, don't assume.** A deploy step that cannot fail is a deploy step that hides failures —
    the pipeline ends with a running-container check for exactly this reason.

## Linters

Both run in the devcontainer, over the workflow files you changed.

### actionlint — workflow schema, expressions, shell

```bash
actionlint -config-file ${LINT_CONFIGS}/actionlint.yaml .github/workflows/<file>.yml
```

It shellchecks `run:` bodies too. `# shellcheck disable=SCxxxx` comments inside a `run:` block work
and need a reason — the reusable uses `SC2029` where remote-command expansion on the runner is
deliberate.

### zizmor — Actions-specific security audit

```bash
zizmor --config ${LINT_CONFIGS}/zizmor.yml .github/workflows/<file>.yml
```

Catches unpinned actions, credential persistence, template-injection sinks, and over-broad
permissions. Findings at `high` are blockers.

## When the executor runs this

After editing any workflow, and always before proposing a merge — a broken workflow is only
discovered by pushing it, which is the slowest possible feedback loop. The
[`task-review` agent](../../agents/task-review.md) re-runs both over the diff.
