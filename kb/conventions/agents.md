# Agent conventions

Rules specific to code under `agents/`. The generic tool rules live in the skills; these are the
factory's own. Rationale for most of them is in
[kb/architecture/agent-anatomy.md](../architecture/agent-anatomy.md).

## Structure

- **One agent per directory, self-contained.** No imports across agents, no shared library. If two
  agents need the same non-trivial thing, duplicate it and note the duplication; extract only after
  a third agent proves the shape.
- **The Python package is always named `agent`.** Only the directory, image, and config differ
  between agents, so the Dockerfile, tests, and entrypoint stay identical.
- **An agent's documentation is `agents/<name>/README.md` — one page, no more.** Do not create a
  `kb/architecture/<agent>.md`; the KB documents the factory, agents document themselves.

## Config and secrets

- **`agent_config.yaml` is committed and must stay secret-free.** It carries the prompt, model,
  limits, and knobs. gitleaks runs over every diff.
- **Real secrets live only in `.env*` files**, which are gitignored and which Claude never reads —
  including commands that only count or list keys. The rule is "do not open the file", because the
  safe-looking variants are how it erodes.
- **Committed scaffolds are named `*.env.template`**, never `.env.something`, so the gitignore and
  the harness deny rules can be blunt without blocking the template. Same reasoning for any
  committed config that a tool wants to see as `.env`: keep the repo-side name distinct and let the
  bind mount rename it (as `.devcontainer/ssh-manager/servers.conf` does).
- **Each role's prompt is a versioned file, `prompts/<role>/v<N>.md`, and the role's
  `system_prompt_file` in `agent_config.yaml` names the live one.** A prompt change is a new
  `v<N+1>.md` plus a one-line pointer change. A shipped version is never edited, so every stored
  `prompt_sha` maps to a file and a rollback is moving the pointer. A short inline `system_prompt`
  is fine until the prompt needs review history.

## Behaviour

- **Fix behaviour with prompts, models, tools and evals — not hardcoded guardrails.** The narrow
  exception is a config-gated, categorical, logged safety veto. See
  [patterns/prompts-and-evals.md](../patterns/prompts-and-evals.md).
- **Tool handlers never raise**; they return `{"success": False, "error": ...}`.
- **Every state-changing tool appears in `WRITE_TOOLS`.** An omission is a live gap, not a nit.
- **`allow_writes` starts false** and is turned on deliberately, after the agent has been observed.
- **Startup checks are not optional.** An agent refuses to run without `CLAUDE_CODE_OAUTH_TOKEN` or
  with `ANTHROPIC_API_KEY` set. Do not remove them to make a run succeed.

## Container image

- **Build context is `agents/<name>/`**, never the repo root. Self-containment is what stops one
  agent's change from entering or invalidating another's image.
- **Dependencies install from the committed `uv.lock`** with `uv sync --locked`, in their own layer
  before the source is copied, so a source edit rebuilds in seconds.
- **The final stage runs as a non-root user with a writable `HOME`.** The bundled `claude` CLI writes
  session and cache state to `~/.claude` even when auth comes entirely from the token, so a
  read-only home breaks it at runtime rather than at build time. The uid is fixed (10001) so the
  operator can chown the VM's bind-mount deterministically.
- **The build asserts what the runtime needs**: the bundled CLI is present in the wheel, and the
  agent package imports. Both failures are otherwise discovered by the first live request.

## Dependencies

- **uv, with a committed `uv.lock`.** The image builds with `uv sync --locked` and fails on a stale
  lock, so `uv lock` and the lockfile go in the same commit as the dependency change.
- **Pin `claude-agent-sdk` exactly.** The SDK's hook payloads and message types are the agent's
  contract with the model; an unpinned minor bump can change them under a running agent.
