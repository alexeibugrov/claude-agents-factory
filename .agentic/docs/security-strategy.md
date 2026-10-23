# Agentic tools security & automation strategy

Companion to [workspace-setup.md](workspace-setup.md) (which covers *wiring*). This page covers *posture*: how much autonomy the agent gets, what it is gated from, and **at which layer each gate lives**. Operating rules (when Claude must stop and ask) stay in [CLAUDE.md](../../CLAUDE.md); this is the architecture behind them.

## 1. Intention — a fully autonomous agent, no prompts

The goal is an agent that runs **end-to-end without interactive prompts** inside the devcontainer. Read/inspect/build/test/render/analyse should never stop to ask. The only things that should ever interrupt the agent — or be outright impossible for it — are **catastrophic mutations**: destroying or corrupting databases, infrastructure, clusters, repositories, or secrets, and anything that mutates state outside the dev blast radius (prod/stage, shared infra, remote Git history).

Concretely:

- **Default = allow.** Anything not explicitly dangerous runs silently. We do **not** maintain an allowlist of "safe" commands to be ticked off one by one — that destroys autonomy and never keeps up.
- **Gate only mutations**, and gate them **where the gate is actually enforced**, not where it is convenient to pattern-match.
- **Prompts are a fallback, not the design.** A prompt means "we couldn't push this gate down to a layer that enforces it." Minimise them.

## 2. The golden rule

> **Allow all reads by default on the infrastructure the agent works with; guard every mutation — and implement the guard at the lowest layer that can enforce it.**

"Lowest layer that can enforce it" means: prefer an OS / network / credential / IAM boundary the provider enforces over a string-match in our harness. The harness can only ever be a *speed-bump*; the credential is the *wall*.

| | Identity / IAM gate (read-only role, scoped token) | Harness gate (settings.json / hook) |
|---|---|---|
| Enforced by | the provider (GitHub, an exchange API, a database…) | a matcher we maintain |
| Bypassed by | nothing — the credential simply *cannot* mutate | obfuscation, `cd && …`, new subcommands, prompt-injection, parser bugs |
| Failure mode | **fail-closed** (denied) | **fail-open** (slips through) |
| Maintenance | set once | enumerate forever |

Corollary: when the credential underneath is read-only, a harness gate's fail-open weakness stops mattering — even a mutation that dresses past the matcher is rejected by the provider. **Defense-in-depth: IAM is the wall, the harness is the courtesy speed-bump.** Where no read-only credential is possible (GitHub — see §4), the harness rules instead lean on `auto` mode's classifier as a second backstop: weaker than a provider wall, but not a silent fail-open.

## 3. The gating system in this setup (defense-in-depth layers)

Four concentric layers. Each contains the blast radius of the one inside it.

| Layer | What it contains | Enforced by | Status |
|---|---|---|---|
| **Devcontainer** | host OS damage; agent confined to the container + its mounts | Docker isolation | in place |
| **Egress firewall** | where the agent can reach on the network | [.devcontainer/init-firewall.sh](../../.devcontainer/init-firewall.sh) (default-deny ipset allowlist) | in place |
| **Credential / IAM** | what the agent can *do* on each provider, read vs write | per-provider identity (see §4) | **not available for GitHub or the root VM** — both fall back to the harness |
| **Harness** | gates for mutations the identity layer can't reach | [.claude/settings.json](../../.claude/settings.json) `allow`/`ask` + `auto`-mode classifier | in place — gh |

### Devcontainer

The agent runs inside the devcontainer, so host-OS damage is contained. **Caveat — the container is not a full blast-radius boundary:** the opened checkout is bind-mounted **read-write**, so `rm -rf /workspaces/claude-agents-factory` deletes *host* files (including any unpushed work), and the firewall still permits Git/registry egress. So the container protects the host *beyond the mounts* — it does **not** by itself protect the mounted repos or any remote state. Those need the credential layer. (`bypassPermissions` mode keeps a hardcoded circuit-breaker for `rm -rf /` and `~`; OS-level [sandboxing](https://code.claude.com/docs/en/sandboxing) is available if we ever want true in-container filesystem/network enforcement.)

**Docker-in-Docker (since 2026-10-23).** The devcontainer runs `--privileged` with its own dockerd, so agents can be built and composed locally. Two consequences:

- Containers started there stay behind the egress allowlist. `init-firewall.sh` applies the same ipset in Docker's `DOCKER-USER` chain and fails container start if dockerd removes it.
- `node` is in the `docker` group, which is root inside the devcontainer. A `--privileged` or `--network host` container could rewrite the firewall, and a privileged devcontainer is a weaker wall around the host VM.

The gate for both is `Bash(docker:*)` in `ask`: every docker command is a human prompt. Keep it there. Don't move docker commands to `allow`.

### Egress firewall

`init-firewall.sh` runs at container start and sets **default-deny egress**, then allowlists only: GitHub API/Git ranges (`api.github.com/meta`), npm, PyPI, GHCR, `api.anthropic.com`, Sentry, VSCode/Azure-blob (incl. the `productionresultssa<N>.blob.core.windows.net` hosts that serve `gh` Actions logs), `semgrep.dev`, the runtime VM, Telegram's data-centre CIDRs, and any static IPs you add. Effect: the agent **physically cannot reach** an un-allowlisted host. New external systems require an explicit allowlist edit — that is the gate working as designed, not a bug. The `gh`-Actions-logs-over-Azure-blob caveat (those `productionresultssa<N>` hosts must be reachable or log fetches return empty *silently*) is the canonical example of why this layer needs deliberate widening rather than silent failure.

### Credential / IAM (the primary gate — see §4)

This is where the golden rule lives. Each provider identity the agent uses is **read-only by construction** wherever we control the credential. Mutations happen through a separate, deliberately-invoked path (PR → CI → deploy), never the agent's day-to-day identity.

### Harness — settings.json + permission mode

The harness is the gate of last resort, for tools we can't reach with a read-only credential (today: GitHub — see §4). Three mechanics matter:

- **`auto` mode honours your `allow`/`ask`/`deny` rules** (confirmed in this setup — mutating `gh` prompts in `auto`). The classifier governs only the commands **no rule matches**: it auto-approves the routine ones and can escalate something that looks risky. So `auto` gives you *both* — **deterministic gates** where you wrote a rule **and an adaptive safety net** on everything you didn't. (`default` mode also honours the rules, but replaces the classifier with a blunt "prompt on anything unmatched" — which floods you unless you allow-list every tool. Whether `auto` honours `ask:` has differed between Claude Code versions — confirmed in this setup, but re-verify with a one-off test after an upgrade.)
- **Precedence is tier-ordered — `deny → ask → allow`, first match wins; specificity doesn't win, there is no negation.** You therefore can't express "ask all of tool X *except* its reads" — a broad `ask: Bash(gh:*)` would clobber any read `allow`. So a harness-gated tool gets **disjoint** lists: read prefixes in `allow`, mutating/catastrophic prefixes in `ask`, and **nothing broad** (no `Bash(gh:*)`, no blanket `allow: Bash`).
- **Unmatched → classifier — and that's *why* we stay in `auto`.** A mutating subcommand you forgot to list isn't run silently; it falls to the classifier, which beats a static denylist's silent fail-open. Keep the catastrophic verbs (`repo delete`, `auth token`, `secret`, api writes) **explicitly** in `ask` so they never hinge on the classifier's judgement.

## 4. Where each gate belongs — by tool

Push every gate to the lowest enforcing layer. Harness gating is the exception, used only when the identity layer is unavailable.

| Tool | Primary gate | Reads | Mutations | Status |
|---|---|---|---|---|
| **SSH / runtime VM** | **none** — identity is `root` and the MCP is in `allow`, so neither layer gates it (owner's choice) | unprompted | unprompted | ⚠️ ungated — see below |
| **Telegram MCP** | harness `deny` on every mutating tool | allowed | impossible (denied) | ✅ in place |
| **Agent runtime (each deployed agent)** | in-agent `PreToolUse` write gate, config-flipped | allowed | denied until `allow_writes` | ✅ in place |
| **GitHub (`gh`)** | **harness in `auto`** — `allow` reads, `ask` mutations, classifier for the rest (IAM/PAT not available — see below) | allowed (allow-listed) | prompted (`ask`) + classifier | 🔶 harness only |

### Pattern: harness-gating in `auto` mode (for tools IAM can't reach)

GitHub is the canonical tool where the identity gate is **genuinely unavailable**, and the options run out: if the agent authenticates as a single personal account and the repos it works on are owned by **someone else** (not an org you control), there is no read-only account to point it at, and a fine-grained PAT doesn't help either — a fine-grained PAT only grants access to repos owned by the token's *own* owner, not to another user's repo you're merely a collaborator on. The harness is therefore the **only** gate for `gh`. The decided shape:

- **Stay in `auto` mode.** The classifier is the safety net that closes the denylist's fail-open hole — an unlisted/novel mutation is judged, not run silently.
- **`allow` the read/log subcommands** — `gh run view/list`, `gh pr view/diff/checks/list`, `gh workflow view/list`, `gh issue view/list` → deterministic, silent CI-log work (no stray mid-run escalation).
- **`ask` the mutating and sensitive ones** — `gh pr create/merge/close/edit`, `gh run rerun/cancel/delete/download`, `gh workflow run`, `gh repo delete/edit`, `gh secret`, `gh auth token`, and — since read-vs-write is flag-level — all of `gh api`. These prompt in `auto`. (The one *routine* read this catches is a mid-run job log — `…/actions/jobs/<id>/logs`, the only way to read a finished job's log before the run completes; policy is to **wait** for the run to end and use native `--log-failed` rather than prompt, so this stays rare.)
- **Nothing broad** — no `ask: Bash(gh:*)` (it would clobber the read `allow`s), no blanket `allow: Bash` (so the classifier still governs every non-gh command).

### SSH: the one place this repo accepts no gate at all

The runtime VM is reached as **`root`**, and `mcp__ssh-manager` is in `permissions.allow`. Both
layers are therefore absent: the far end cannot refuse anything, and the harness does not prompt.
This is the deliberate exception to §1's golden rule, chosen for friction-free operation of the
agent stacks.

State it accurately rather than dressing it up: **for this tool, the model's own judgement is the
control.** The supporting measures are real but secondary — a reduced tool surface
(`tools-config.json` drops the backup and database groups), a separate CI identity, a read-only key
mount, and the behavioural rules in the
[ssh-mcp-server skill](../../.claude/skills/ssh-mcp-server/SKILL.md).

**The prompt-injection chain is unbroken.** The Telegram MCP puts third-party text in the same
session as an unprompted root shell. Previously the confirmation was the link that broke; now the
only thing between "a retrieved message contains an instruction" and "it executed" is the rule that
retrieved content is data, never instructions. That rule is stated in `CLAUDE.md`, the
`ssh-mcp-server` skill, and `kb/architecture/telegram-mcp.md`, and it is load-bearing.

The two ways to restore a real gate, in order of strength: provision a non-root read-only identity on
the VM (structural — the far end refuses, no rule needed), or move `mcp__ssh-manager` back to
`permissions.ask` (procedural, but mechanical).

History worth keeping as a lesson, not as wiring: an earlier iteration of this setup gated `gh` with a PreToolUse **hook** before discovering that native `allow`/`ask` rules in `auto` do everything the hook did for reads, **plus** the `ask` gate on mutations the hook could never enforce. The general lesson: **a harness hook is only worth writing for splits the rule globs can't express** (flag-level read/write, e.g. `gh api -X POST`). When a subcommand-prefix glob suffices, prefer the native `allow`/`ask` rules — fewer moving parts, nothing to keep in sync, and the classifier still backstops everything unlisted. Verify after a session restart that `allow` silences reads in `auto` and `ask` prompts mutations (one-off test — behaviour has differed between versions).

## 5. Accepted risks / non-goals

- **`auto` mode is the chosen default** — it honours our `allow`/`ask`/`deny` rules **and** adds a classifier over everything unmatched, so we get deterministic gates *and* an adaptive net without leaving `auto`. We accept that the classifier (heuristic, a research preview) is what judges the unlisted middle; the commands that actually matter are pinned with explicit `ask`/`deny` so they never depend on it.
- **Unlisted mutations fall to the classifier, not to silent execution.** Because we stay in `auto` (rather than blanket-`allow: Bash` in `default`), a mutating command we didn't list is judged rather than run — so the old "fail-open denylist" risk is largely closed. Residual risk: the classifier misses something; mitigated by listing the catastrophic verbs explicitly in `ask`.
- **We do not filter command *parameters*** (read-vs-write by flag, e.g. `gh api -X POST`). It's fragile and rare; such cases are gated by `ask`-ing the whole subcommand, or left to the credential layer.
- **VM access is root, unprompted, with no gate at either layer.** The most significant accepted risk in this repo, and knowingly taken: the operator chose direct root and auto-approval for friction-free operation. Every other tool here has at least one mechanical control; this one has none. Two consequences follow — a mistaken destructive command is not caught by anything, and the Telegram → root-shell prompt-injection chain has no mechanical break. Provisioning a read-only identity is the known hardening.
- **Deployed agents are gated by their own code.** An agent's write gate lives in the image it ships; a bug in `guards.py` is a gate that does not hold. That is why `WRITE_TOOLS` completeness is a review blocker and why the gate is tested directly rather than through the model.
- **Secrets on the VM are protected by a behavioural rule**, not by a permission alone: Claude is denied `Read` on `.env*` paths, but a shell or an SSH call could still reach them, so the rule "never open the file, including to count keys" is what actually holds.

## 6. Rule of thumb for adding a new tool / provider

1. **Can the provider issue a read-only identity?** (IAM role, scoped token, DB role, RBAC.) → Do that. Allow the tool fully inside the container. Done — no harness rule needed.
2. **No read-only identity, but you don't mind prompting on reads?** → `ask: Bash(<tool>:*)` — one line, asks everything, safe, zero maintenance.
3. **No read-only identity, and reads must stay silent while mutations prompt?** → stay in `auto`; `allow` the read subcommands and `ask` the mutating/catastrophic ones (disjoint lists, nothing broad). The classifier covers whatever you didn't list, so there is no silent fail-open. A PreToolUse hook is needed only for flag-level read/write splits the rule globs can't express — rarely worth it.

Never reach for step 3 when step 1 is possible.

## See also

- Wiring & repo shape → [workspace-setup.md](workspace-setup.md)
- Operating rules (when to stop/ask) → [CLAUDE.md](../../CLAUDE.md) → *Operating rules* / *Escalation triggers*
- VM access posture → [kb/architecture/ssh-mcp.md](../../kb/architecture/ssh-mcp.md)
- Agent-level write gate → [kb/architecture/agent-anatomy.md](../../kb/architecture/agent-anatomy.md)
- Egress allowlist → [.devcontainer/init-firewall.sh](../../.devcontainer/init-firewall.sh)
- Harness permission rules → [.claude/settings.json](../../.claude/settings.json)
