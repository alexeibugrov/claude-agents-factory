# The standard agent

Every agent in this factory has the same seven pieces. The shape is not style — each piece exists
because its absence caused a specific, hard-to-diagnose failure. Reference implementation:
[agents/_template/](../../agents/_template/).

## The pieces

| Piece | File | Why it is not optional |
|---|---|---|
| Config | `agent_config.yaml` + `agent/config.py` | Prompts and models are versioned and reviewable; loading fails fast, so a bad config stops the container at startup instead of surfacing as a strange failure on the first real request. |
| Per-run context | `agent/context.py` | The loop is async. Module globals let one in-flight run read another's client — silent cross-contamination that is nearly impossible to trace after the fact. |
| Tools | `agent/tools.py` | The agent's entire capability surface, declared explicitly. |
| Guard | `agent/guards.py` | A `PreToolUse` deny hook. The only thing standing between a confused model and a real state change. |
| Loop | `agent/loop.py` | One `query()` per run, reduced to a result dict. Never raises. |
| Entrypoint | `agent/main.py` | The trigger, plus the startup checks that refuse to run misconfigured. |
| Stack | `deploy/docker-compose.yaml` | Image, journald logging, config mount, security posture. |

## Stateless runs

One request → one `query()` → a result dict. No session is carried between runs, and `max_turns`
caps the tool-calling loop inside one run.

This is what makes failure cheap. A run that crashes leaves nothing behind; a run that is retried
starts clean. The alternative — a long-lived session — means a confused model stays confused, and
one poisoned context degrades every subsequent request until someone restarts the container.

`max_turns` is a circuit breaker, not a tuning knob. A model that has not finished in 15 turns is
usually looping, and letting it continue burns budget without converging.

## The options that define the sandbox

Set in [agents/_template/agent/loop.py](../../agents/_template/agent/loop.py):

- **`tools=[]`** — disables every *built-in* tool: file access, bash, web. The agent gets exactly
  the tools it declares and nothing else. Omitting this hands a production agent a shell.
- **`setting_sources=[]`** — ignores `.claude/` config and MCP servers found on disk, so the agent
  can never inherit whatever tooling happens to exist on the machine it runs on. Without it, an
  agent behaves differently in a developer's checkout than in its container.
- **`permission_mode="dontAsk"`** — auto-approves the declared tools. There is no human at the other
  end of a container, so the alternative is a hang. Safety comes from the guard, not from this.
- **`allowed_tools=["mcp__<server>__*"]`** — the explicit allowlist matching the declared server.

## Tools never raise

A raising `@tool` handler tears down the Claude session and loses the whole run. Every handler
catches and returns `{"success": False, "error": ...}` instead. The model can read that and react —
retry, try another approach, or report the failure — which is strictly better than the run vanishing.

## The write gate

The factory's standard answer to "read freely, change nothing until someone says so": a
`PreToolUse` hook that denies the tools named in `WRITE_TOOLS` while `agent.allow_writes` is false,
and is inert when it is true.

Two properties matter. **Enabling writes is a config flip**, so going live is a reviewed config
change and a redeploy, never a code change. And **the gate holds under `permission_mode="dontAsk"`**
— the permission mode auto-approves tools, the hook still vetoes them. That combination was verified
end to end in `bb-trade-agent` rather than assumed.

The gate is sanctioned, not a workaround: it is config-driven, documented, and reversible.
`/task-review` treats guards of this shape as legitimate. A hardcoded `if symbol == "BTC": return`
is not the same thing — see [patterns/prompts-and-evals.md](../patterns/prompts-and-evals.md).

## Startup refusals

`main.py` exits non-zero rather than starting when `ANTHROPIC_API_KEY` is set or
`CLAUDE_CODE_OAUTH_TOKEN` is missing. Both conditions otherwise produce an agent that appears to work
while billing the wrong way or failing on first contact. See [auth.md](auth.md).

## Logging

Stdout only, INFO level, one line per streamed event: assistant text, each tool call with its
arguments, each tool result, and the terminal usage/cost. That trace *is* the debugging artefact —
when an agent does something unexpected, it is the only record of what it was thinking. Compose
sends it to the host journald with a stable tag so it survives the container recreate that every
deploy performs. A non-`COMPLETED` run logs a greppable `AGENT ALERT` line for journald alerting.
