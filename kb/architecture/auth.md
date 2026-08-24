# Auth — the owner's Claude subscription

Agents authenticate with the **owner's personal Claude subscription**, not an API key. This is a
deliberate cost choice: subscription billing, not per-token.

## How it works

The `claude-agent-sdk` wheel bundles a self-contained per-architecture `claude` CLI. The SDK spawns
it, and it authenticates with `CLAUDE_CODE_OAUTH_TOKEN` — a long-lived token (~1 year) produced by
running `claude setup-token` once on any machine with a browser.

The token goes in the VM's gitignored `.env.<agent>` file. It **does not auto-refresh**: renew it by
re-running `claude setup-token` and pasting the new value.

## The one thing that silently breaks it

**`ANTHROPIC_API_KEY` takes precedence over the OAuth token.** If it is set anywhere in the
container's environment, the agent quietly switches to per-token API billing and keeps working — no
error, no warning, just a different invoice.

Because the failure is invisible, the check is explicit: `agent/main.py` refuses to start when
`ANTHROPIC_API_KEY` is present, and the committed `*.env.template` carries it commented out with the
reason attached. Do not "fix" a startup refusal by removing that check.

## Consequences worth knowing

- **Rate limits are the subscription's**, shared across every agent and every Claude Code session
  the owner runs. An agent hammering the API degrades the operator's own tooling. The SDK surfaces
  a `RateLimitEvent` in-stream; the reference implementation in `bb-trade-agent` retries with
  backoff, but only when the attempt placed no write.
- **`total_cost_usd` on the `ResultMessage`** is still reported and still worth logging — it is how
  a runaway agent gets noticed.
- **Running SDK code from inside Claude Code** hits a nested-session gotcha. Use
  `env -u CLAUDECODE uv run python -m agent.main` when testing an agent from an agent session.
- **A writable `HOME`** is required: the bundled CLI writes session and cache state to `~/.claude`
  even when auth comes entirely from the token. That is what the `claude-config` volume in each
  compose file is for — it holds no credentials.
