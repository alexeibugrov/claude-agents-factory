# Plan: Telegram job auto-apply agent (`tg-job-applier`)

- **Date:** 2026-08-24
- **Scope:** Critical
- **Status:** Draft for review — 11 of 12 questions resolved by the operator; 1 remains open (Q11)

## 1. Summary

Build the factory's first real agent: it watches the same Telegram source channels `cloud-scraper`
already watches, asks Claude (Sonnet 5) whether each job post matches the operator's criteria, DMs
the poster an application when it does, and forwards every post to the existing destination channel
labelled applied / not-applied.

The biggest risk is not classification accuracy — it is that **every write this agent makes is an
irreversible action taken from the operator's personal Telegram account**. A DM cannot be unsent from
the recipient's notification, and the account is the same identity that runs two live production
scrapers on the shared VM. The plan therefore front-loads a read-only observation phase
(`allow_writes: false`), a contact-verification read tool, and a categorical daily send cap, and it
treats the honesty of the eval labels as a first-class deliverable rather than a step.

## 2. Goal and non-goals

**Goal.** A self-contained agent under `agents/tg-job-applier/` that:

1. Receives new messages from the configured Telegram source channels in near-real time.
2. Classifies each against the operator's vacancy criteria using Claude Sonnet 5 on subscription auth.
3. When it matches, DMs the Telegram contact named in the post with the operator's application text
   plus resume, after a randomised pre-send delay and under a daily send cap.
4. Forwards every post to the destination channel with an applied / not-applied label.
5. Ships through the existing reusable workflow to `/app/tg-job-applier` on `157.90.18.149`.
6. Passes an eval suite whose labels were fixed and operator-approved **before** any prompt tuning.

**Non-goals.**

- Changing `agents/_template/` (a change there would change every future agent —
  [CLAUDE.md](../../../CLAUDE.md) § Agents).
- Changing `.github/workflows/agent-deploy.reusable.yml`.
- Modifying, migrating, or fixing the `alexeibugrov/tg-scraper` repository itself.
- Replying to anything other than a Telegram `@username` contact (no email, no web form, no URL).
- Multi-account or multi-persona sending.
- Retiring `cloud-scraper` in this task — see §18.

## 3. Current state

**`cloud-scraper` is live on the target VM, not just in a repo.** `docker ps` shows
`cloud-scraper` / `cloud-scraper:latest` / `Up 2 months`, alongside `crypto-forwarder` and three
`bb-*` agent stacks. Its directory is `/app/cloud-scraper`, and its stack is built on the VM from a
local `build: .`, not pulled from GHCR — so it is outside the factory's CI/CD entirely.

**Its logic is 20 lines.** `cloud-scraper/cloud-scraper.py:34-43` registers a Telethon
`events.NewMessage(chats=source_chats)` handler, lowercases the message, drops it if any
`exclude_keywords` substring matches, forwards it with `client.forward_messages(target_chat, ...)`
if any `keywords` substring matches, and prints `Forwarded message: <text>` to stdout. There is no
LLM step, no state, no dedupe, and no reply capability.

**Auth is an MTProto user session, as expected.** `cloud-scraper.py:26` constructs
`TelegramClient('anon', int(api_id), api_hash)` — a personal-account login, not a bot token. The
running container bind-mounts `/app/cloud-scraper/telegram_sessions/telegram_session.session` to
`/app/anon.session` read-write, and `/app/crypto-scraper/anon.session` is a *separate* session file
for the sibling stack. **Two concurrent sessions on the operator's account are already in
production**, so a third is an established pattern here rather than a new risk.

**Secrets are handled the opposite way to this factory.** `cloud-scraper.py:17-22` reads `api_id`
and `api_hash` out of a gitignored `config.yaml`. That inverts the factory rule that config is
committed and secret-free ([kb/conventions/agents.md:19-27](../../conventions/agents.md)). The same
repo also commits **real, live Telegram API credentials** in `gpt_config.yaml` and
`crypto_config.yaml` — present in plaintext in `HEAD`. The operator has confirmed the repository is
**private**, so exposure is bounded by its access list rather than open to the world; the credentials
are nonetheless committed in the clear and shared across two live scrapers. See §14 R1. The values
are deliberately not reproduced here.

**Real message traffic is noisy and the keyword filter is weak.** Of the 509 posts the running
container has forwarded since 2026-04-15, the most recent ones include an IT-industry survey
advertisement and an `@AllConfsBot` promotional post — neither is a vacancy. **That promo contains
the literal string `B2B Хаб`**, which is decisive for §6 D3: a keyword rule of the shape
"contains B2B ⇒ reply" would fire on an advertisement.

**Contact strings are structured but adversarial to regexes.** Frequency-counted contact lines
include `Контакты: @sourserXP`, `Telegram: @viktoria_ihr`, `Пишите: @pollid8`, `Отклик: Tg @…` —
but also `Контакты: office@billions` and `Контакты: mrandrsn@protonmail`, which are **email
addresses that a naive `@\w+` match reads as Telegram handles**. Separately, a real DevOps post
carries `Обсуждение: @devops_jobs` — a public discussion *channel*, not the poster's contact — with
the actual application route being an `https://medvidi.com/careers/...` URL.

**Volume is low.** `docker logs -t --since 720h` counts **108 forwarded posts in the last 30 days**,
across 117 active days total, peaking at 10 on one day. That is ~3.6 posts/day *before* criteria
filtering, so realistic DM volume is well under 2/day.

**Salary and location formats vary more than the original criteria assumed.** RUB amounts in the
corpus appear as `90 000₽`, `400 000₽`, `150.000₽`, `320тр`, `340 т.р.`, `220т.р` — the `₽` symbol is
common and was absent from the operator's first list (`руб, р, т.р`). Location terms: `офис` (46),
`гибрид` (20), `hybrid` (13), plus `релокация` / `релокации` / `релокационный` (~22 combined), a
category the original criteria did not mention. Both gaps are now closed by the operator's answers to
Q4 and Q10 (§8 *Resolved*), and the resolved wording is what the eval labels are written against.

**"Crypto" is mostly industry vocabulary, not salary currency.** `crypto` appears 278 times and
`крипто*` ~200 more, overwhelmingly inside company descriptions (`криптоплатформы`,
`криптоиндустрии`, `криптопродуктов`). `usdt` appears only 22 times.

**Original-post links are almost never in the body.** Only 8 of 509 posts contain any `t.me/` URL.
The `{link to vacancy in original channel}` in the operator's reply text must therefore be
*constructed* from the source message's chat and id, not extracted from its text.

**The `telegram` MCP is unavailable, and still is.** `claude mcp list` reports it
`⏸ Pending approval`, no `mcp__telegram__*` tool is exposed, and the credentials file its
[.mcp.json](../../../.mcp.json) command sources is absent from the workspace root. A Claude Code
session restart has been requested and the result is not yet known, so this remains **pending**, not
resolved (Q11). It blocks the MCP route for the eval corpus; §6 D8 proposes the substitute that made
this plan possible anyway.

**The factory scaffold is ready and unused.** `agents/` contains only `_template/`; `kb/tasks/`
contains only `001-agents-factory-setup-2026-08-24`. The VM has persistent journald
(`/var/log/journal` exists), 58G free, and 6.5G available RAM.

## 4. Evidence map

| Source | What it tells us |
|---|---|
| `cloud-scraper/cloud-scraper.py:26,34-43` (cloned to scratch) | Telethon user session; `events.NewMessage` trigger; substring keyword/exclude filter; plain `forward_messages` with no label |
| `cloud-scraper/cloud-scraper.py:17-22` | api_id/api_hash read from a gitignored `config.yaml` — inverts this factory's config/secret split |
| `gpt_config.yaml:1-8`, `crypto_config.yaml` (tg-scraper `HEAD`) | Real Telegram API credentials committed in plaintext to the repo — **private**, per the operator, so exposure is bounded by its access list; destination annotated `# cloud jobs`; `-1002486420468` annotated `# Test Channel` |
| `main.py:16-19` (tg-scraper) | Confirms destination/source/keyword shape used in production |
| MCP `ssh_execute pulse: docker ps` | `cloud-scraper` Up 2 months; `crypto-forwarder` Up 4 weeks; three `bb-*` agent stacks Up 9 days — shared, busy production VM |
| MCP `ssh_execute pulse: docker inspect cloud-scraper` | Session bind-mounted RW; log driver `json-file`; `config.yaml` mounted `ro` |
| MCP `ssh_execute pulse: ls -la /app/cloud-scraper /app/crypto-scraper` | Two *separate* session files already in concurrent production use; `tg-auth.py` is the operator's existing session generator |
| MCP `ssh_execute pulse: docker logs cloud-scraper` | 509 posts since 2026-04-15; non-vacancy ads pass the filter; `B2B Хаб` inside a promo; `Обсуждение: @devops_jobs` as a channel-not-contact |
| MCP `ssh_execute pulse: docker logs -t --since 720h \| grep -c` | 108 posts in 30 days — eval corpus size and volume ceiling |
| MCP `ssh_execute pulse: docker logs … \| grep -oiE 'Контакты…@…'` | Contact-line taxonomy, including `office@billions` / `mrandrsn@protonmail` email false positives |
| MCP `ssh_execute pulse: docker logs … \| grep -oiE '…(руб\|₽\|т\.?р\.?)'` | RUB forms incl. `₽`, `320тр`, `340 т.р.` — broader than the stated criteria |
| MCP `ssh_execute pulse: docker logs … \| grep -oiE '(USDT\|крипт…)'` | 278 `crypto` vs 22 `usdt` — "crypto" is industry vocabulary, not currency |
| MCP `ssh_execute pulse: docker logs --since 30d` | Returns *nothing* on stdout with `invalid value for "since"` on stderr — the CLAUDE.md "silence is not success" trap, hit and caught during this exploration |
| `agents/_template/agent/main.py:33-35` | `iter_requests()` is the trigger seam; its docstring names "reading a Telegram chat" as an intended shape |
| `agents/_template/agent/loop.py:64-74` | Sandbox posture: `tools=[]`, `setting_sources=[]`, `permission_mode="dontAsk"`, `PreToolUse` write gate |
| `agents/_template/agent/guards.py:23,45-52` | `WRITE_TOOLS` set and the deny decision the gate returns |
| `agents/_template/agent/tools.py:50-60` | The never-raise `_wrap` contract every handler inherits |
| `agents/_template/agent_config.yaml:12-29` | `agent.*` knobs, `system_prompt`, and the free-form `settings` map |
| `agents/_template/deploy/docker-compose.yaml:6,14-36` | Image ref, journald tag, `env_file`, read-only config mount, `cap_drop: ALL`, `mem_limit` |
| `agents/_template/deploy/workflow-caller.yml.template:6-16` | Caller triggers on `push` to `main` and `v*` tags only — **no `workflow_dispatch`, no `pull_request`** |
| `.github/workflows/agent-deploy.reusable.yml:26-37,101-124` | `deploy_dir` / `compose_file` / `config_file` / `build` / `image_tag` overrides exist — the supported way to run a second stack |
| `.github/workflows/agent-deploy.reusable.yml:110-112,187-193` | Constant `vm-deploy` concurrency group; post-deploy running check |
| `.claude/settings.json` `permissions.deny` | 63 `mcp__telegram__*` mutating tools denied, plus `Read(**/.env)` and `Read(**/.env.*)` |
| `claude mcp list` | `telegram: ⏸ Pending approval` — MCP unavailable this session |
| `.gitignore:7-8,19` | `.env`, `.env.*` and `*.session` already ignored; `*.env.template` deliberately not matched |
| `.devcontainer/init-firewall.sh:126-143` | Telegram MTProto CIDRs already allowlisted — local dev/eval can reach Telegram |
| `kb/patterns/lessons.md:42-47` | Deduplicate before anything expensive; claim the key atomically before the model call |
| `kb/patterns/prompts-and-evals.md:16-22,41-50` | The sanctioned-veto bar, and the mock-backend / data-scenarios / grade-end-state eval shape |

## 5. Patterns to mirror

| Category | Source | Pattern |
|---|---|---|
| Agent scaffold | `agents/_template/` via [.claude/skills/new-agent/SKILL.md:30-37](../../../.claude/skills/new-agent/SKILL.md) | Copy, rename `AGENT_NAME`, move `agent.env.template` → `tg-job-applier.env.template`, move the caller template into `.github/workflows/` |
| Trigger seam | `agents/_template/agent/main.py:33-35` | Replace `iter_requests()`; keep everything below it untouched |
| Telegram ingest | `cloud-scraper/cloud-scraper.py:34-43` | `events.NewMessage(chats=source_chats)` on a Telethon user client — reuse the shape, not the file |
| Tool handler contract | `agents/_template/agent/tools.py:31-47,50-60` | `(ctx, **args) -> dict`, registered in `TOOL_SPECS`, wrapped by the never-raise `_wrap` |
| Per-run binding | `agents/_template/agent/context.py:12-18` | Extend `RunContext` with the Telethon client and the source message — never module globals |
| Write gate | `agents/_template/agent/guards.py:23` + `tests/test_guards.py:14-30` | Fill `WRITE_TOOLS`; the shipped tests already assert deny/inert behaviour |
| Config/secret split | `agents/_template/agent_config.yaml:1-11` + `agent.env.template` | Channel ids, prompt, delays, caps in committed YAML; credentials by name only in the env template |
| CI caller | `agents/_template/deploy/workflow-caller.yml.template` | One path-filtered caller passing `agent:` and `secrets: inherit` |
| Second/preview stack | `.github/workflows/agent-deploy.reusable.yml:26-37` + [kb/architecture/cicd.md:22-25](../../architecture/cicd.md) | A variant stack is `deploy_dir` + `config_file` overrides, never a code fork |
| Dedupe before spend | `kb/patterns/lessons.md:42-47` | Semantic key with a short TTL, claimed atomically before the model call |
| Eval suite | `kb/patterns/prompts-and-evals.md:41-50` | Mock backend, YAML scenarios, grade end state, run the real loop |

No existing agent in this repo demonstrates a long-lived event-driven trigger, a Telethon client, or
an eval suite — `agents/_template/` is a single-shot demo generator. Those three are genuinely new
here and are the parts §10 spends its detail on.

## 6. Architecture and trade-offs

### D1 — Ingest: event-driven Telethon in-process (chosen) vs. polling vs. reading the forwards

The operator's stated problem is latency ("replying first is crucial"). Polling adds exactly the
delay we are trying to remove. Reading the *destination* channel instead of the sources would be
simpler but loses the original message's chat and id, which §6 D6 needs to build the vacancy link,
and adds `cloud-scraper`'s own latency on top.

**Chosen:** a Telethon client started in `agent/main.py`, with an `events.NewMessage` handler that
pushes `(run_id, message)` onto an `asyncio.Queue`; `iter_requests()` drains that queue and yields
one prompt per message. This keeps the factory's one-message-one-`query()` statelessness
(`kb/architecture/agent-anatomy.md:19-30`) while the client itself is long-lived, and it puts the
Telethon client on `RunContext` so each run's tools act on that run's message only.

Trade-off: the process now has two failure domains (the Telethon connection and the agent loop). A
dropped Telethon connection must not kill the container silently — see §14 R7.

### D2 — Credential shape: `StringSession` in the env file (chosen) vs. a bind-mounted `.session`

`cloud-scraper` bind-mounts a binary SQLite session read-write. The factory's compose template
mounts only `agent_config.yaml` (read-only) and takes every secret from `env_file`
(`agents/_template/deploy/docker-compose.yaml:19-36`). A Telethon `StringSession` fits that shape
with no extra mount, survives the container recreate every deploy performs, and matches how the
`telegram-mcp` server is credentialed.

**Chosen:** `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION_STRING` in
`/app/tg-job-applier/.env.tg-job-applier`, operator-provisioned. Trade-off: the string is a
full-account credential in an env file; rotation means re-running the generator and re-pasting.
Accepted — it is the same trust level as the session file already on that VM, with better handling.

**Identity, resolved (Q8):** the **same Telegram account** as the existing scrapers — so this is the
third concurrent session on one account (A2) — but with a **freshly registered `api_id`/`api_hash`**,
not the pair committed in `tg-scraper`'s configs. Same-account keeps the operator's real identity on
the application, which is the point of the agent; the fresh app pair keeps this agent off a
credential that is committed in the clear and shared with two other stacks (§14 R1). The operator is
separately rotating the old pair.

### D3 — Classification: entirely in the prompt (chosen) vs. hardcoded pre-filters

[kb/patterns/prompts-and-evals.md:1-22](../../patterns/prompts-and-evals.md) requires prompts, not
guardrails, unless a veto is config-gated, categorical and logged. The corpus makes the case
empirically rather than on principle:

- `B2B Хаб` appears inside a **non-vacancy advertisement** — a `B2B ⇒ reply` rule fires on an ad.
- `office@billions` and `mrandrsn@protonmail` are **emails**, not handles — an `@\w+` extractor DMs
  users that do not exist.
- `@devops_jobs` is a **channel**, not the poster.
- 278 `crypto` hits are company vocabulary; only 22 are `usdt`.
- RUB appears as `₽`, `320тр`, `340 т.р.` — a literal `руб|р|т.р` match misses the most common form
  and, on `р`, matches most Russian words.

Every one of those is a semantic judgement. **Chosen:** all criteria live in `system_prompt` in
`agent_config.yaml`.

The operator's resolutions to Q2, Q3, Q4 and Q10 sharpen the criteria but do **not** change this
decision — each is still a judgement the model makes, and each is now precise enough to label
against. The prompt must encode, verbatim in effect:

- **Russia (Q2):** skip when the post explicitly states employment must be **in** Russia, the role is
  **based in** Russia, or eligibility is "Russia only". **No inference from the language the post is
  written in** — the corpus contains a US employer posting in Russian. RUB salary is disqualifying
  under its own criterion regardless.
- **Crypto (Q3):** the crypto trigger fires only when **salary or payment itself** is in
  USDT/USDC/other crypto. A crypto-industry employer paying in fiat does not qualify — which is what
  makes the 278 `crypto` mentions in the corpus mostly irrelevant.
- **RUB (Q4):** `₽`, `тр`, `т.р.` count as RUB alongside the spelled-out forms. Additionally, **a
  bare figure in thousands shorthand** (`тыс`, `тысяч`, `к`, `тр`, `т.р.`) with **no other currency
  marker** counts as RUB. **A post with no salary at all is skipped** — disqualifying, not neutral.
- **Relocation (Q10):** relocation-required is non-remote and is skipped, **regardless of
  destination**.

Two vetoes remain, and both clear the sanctioned bar:

1. **The write gate** (`agent/guards.py`) — already the factory's canonical example.
2. **A daily send cap** in `settings` — categorical ("no more than N sends per calendar day, ever"),
   config-gated, and it logs an `AGENT ALERT`-style line when it fires. It is not case-specific and
   removes no classification decision from the model.

The randomised pre-send delay is not a behaviour guardrail at all — it is anti-flood plumbing inside
the send tool, the "infrastructure reliability" carve-out at
`kb/patterns/prompts-and-evals.md:26-28`. It must **not** be a prompt instruction: a model cannot be
trusted to sleep, and asking it to burns turns.

### D4 — Tool surface

Per [kb/patterns/tool-design.md:7-12](../../patterns/tool-design.md), expose the operation, not the
primitives.

| Tool | Kind | Purpose |
|---|---|---|
| `lookup_contact` | read | Resolve a candidate `@handle` and report whether it is a real **user** (vs. bot, channel, or not found). This is the structural answer to the `office@billions` / `@devops_jobs` problem — the model verifies instead of us regexing. Resolves Q5 by design. |
| `send_application` | **write** | The whole unit: enforce delay + cap, verify the stored resume message still resolves, DM the verified user the application text, forward the resume from the storage channel, return the sent message ids and today's send count. |
| `report_to_channel` | **write** | Forward the original to the destination channel, then post the applied / not-applied label as a reply to that forward. Runs on **every** post, applied or not (AC #2). |

`WRITE_TOOLS = {"send_application", "report_to_channel"}`. Consequence worth stating plainly: with
`allow_writes: false` the agent posts nothing at all, including labels — the decision trace lives
only in journald. That is exactly what the observation phase in §10 Phase 4 wants, and it is why
`cloud-scraper` keeps running through it (D7).

**Resume delivery, resolved (Q1): forward from a storage channel.** The operator chose this over the
VM-mounted file this plan originally recommended, knowing the trade-off. Consequences that propagate
through the rest of the plan:

- **No resume file on the VM and no extra compose mount.** The image and the VM stay free of the
  operator's personal document, which is the upside of this choice.
- `agent_config.yaml` gains a `settings` entry naming the stored resume as a
  **`(storage_chat, message_id)` pair** — an id, not a file path. It is a channel reference, not a
  secret, so it belongs in the committed config.
- `send_application` **must resolve that stored message immediately before sending** and, if it does
  not resolve, **fail the run loudly** — an `AGENT ALERT` line, no retry, and **no DM sent without
  the resume**. A half-application (text, no resume) is worse than none; it burns the contact.
- The recipient sees the resume as *forwarded from* the storage channel rather than as a clean
  attachment, and the filename cannot be changed. Accepted.

This is the mitigation R10 already specified for the storage-channel path, now promoted from
contingency to the implemented design. R10 stays in §14 as an **accepted, mitigated** risk.

### D5 — Label mechanism: forward, then reply to the forward (chosen)

Telethon cannot attach a caption to a forwarded **text** message. Three options:

- **A. Forward + a following label message.** Simple, preserves attribution. But two concurrent runs
  interleave, and a label can end up under the wrong post.
- **B. Repost as new text with a label header.** One message, but loses "forwarded from", risks the
  4096-character limit on long posts, and drops formatting entities.
- **C. Forward, capture the resulting message id, send the label as a *reply* to it.** (chosen)

C costs one extra message but ties the label to a specific message id, so interleaving is
structurally harmless rather than merely unlikely. The destination in `gpt_config.yaml:4` is a basic
group, where replies work normally.

### D6 — The vacancy link

Only 8 of 509 posts carry a `t.me/` URL, so the link must be built rather than extracted:
`https://t.me/<source_channel_username>/<message_id>`.

The operator has confirmed (Q6) that **all monitored source channels are public**, so this form
applies uniformly and every link resolves for the recruiter receiving the DM. The private-channel
case — where the only available form is the member-only `https://t.me/c/<internal_id>/<id>` — does
not arise and needs no fallback.

One consequence to keep: this makes a public `username` on the source channel a **hard runtime
dependency**. If a source channel is ever made private, link construction degrades silently to a dead
link. `send_application` should therefore treat a missing channel username as a run failure rather
than sending a broken link — cheap to implement now, and the same failure shape as the resume check.

### D7 — Coexistence with `cloud-scraper`

AC #2 says the destination channel keeps receiving posts, now labelled. If both stacks run with
`allow_writes: true`, the destination receives every post **twice** — once plain from
`cloud-scraper`, once labelled from the new agent.

**Chosen sequencing**, which turns that conflict into the safety net:

1. Deploy `tg-job-applier` with `allow_writes: false`. It writes nothing; `cloud-scraper` continues
   to serve the destination channel exactly as today. The operator reads journald and compares the
   agent's decisions against posts they can see.
2. Flip `allow_writes: true` (a config-only redeploy) **and** stop `cloud-scraper` in the same
   window, so the destination channel never receives duplicates.

The operator has confirmed this sequencing (Q12) and confirmed the destination channel is the one
annotated `# cloud jobs`. Retiring `cloud-scraper` permanently is §18, not this task.

### D8 — Eval corpus source: the running container's log (chosen), MCP as a supplement

The `telegram` MCP is unavailable this session (§3). The `cloud-scraper` container's `json-file` log
already holds **108 posts from the last 30 days** in exactly the form the classifier sees — the post
text. That is the operator's requested window, obtainable read-only, today.

Its limitation is real: the log carries **text only** — no message id, no source chat, no timestamp
per post beyond the docker timestamp, and no `fwd_from`. So it grades **classification** completely
and grades **link construction** not at all. Link construction gets covered by unit tests over
synthetic message objects plus the Phase 5 live smoke test.

Caveat to respect: that log is `json-file` on a container `Up 2 months`
(`kb/patterns/lessons.md:9-13` — this data dies with the next `docker rm`). **Extract it to the task
folder before anything else.**

### D9 — Model and fallback

Sonnet 5 as primary, per step 4 / AC #4. The template ships `fallback_model: claude-sonnet-5` under
an Opus primary (`agents/_template/agent_config.yaml:13-14`); inverting that would silently run
**unvalidated** classification behaviour on a model the eval suite never graded. **Chosen:**
`fallback_model: null`, and a rate-limited run fails loudly and is retried by the queue instead.

### D10 — Deduplication

The same vacancy is routinely cross-posted to several channels. Without a dedupe key the agent DMs
the same recruiter twice for one job — a reputational failure, and precisely the incident behind
`kb/patterns/lessons.md:42-47`. **Chosen:** an in-process TTL cache keyed on
`<normalised contact handle>:<normalised title>`, claimed **before** the `query()` call, TTL from
`settings`. In-process (not persisted) is a deliberate simplification: a container restart re-opens
the window, which at ~3.6 posts/day is an acceptable trade against adding a state volume.

## 7. Assumptions

- **A1:** The agent monitors the same source channels `cloud-scraper` does, read from
  `agent_config.yaml`, not the destination channel — *required by D6 to build the vacancy link, and
  it removes `cloud-scraper` from the latency path.*
- **A2:** The operator's account holds a third concurrent MTProto session — *two already run
  concurrently on this VM (`/app/cloud-scraper/telegram_sessions/`, `/app/crypto-scraper/`), and Q8
  confirmed the same account is used for sending.*
- **A3:** Realistic send volume is under 2 DMs/day — *108 posts/30 days before criteria filtering,
  and Q4's "no salary stated ⇒ skip" removes a further slice.* If this ever proves wrong the daily
  cap catches it.
- **A4:** ~~The destination channel is the one annotated `# cloud jobs`~~ — **confirmed by the
  operator (Q12)**; no longer an assumption. The live value still lives in
  `/app/cloud-scraper/config.yaml`, which is not opened because it also holds api_id/api_hash, so the
  id is transcribed into `agent_config.yaml` from the operator's confirmation rather than read off
  the VM.
- **A4b:** The resume storage channel is readable by the sending session and its stored message is
  stable — *Q1 chose the storage-channel path; `send_application` verifies resolution before every
  send precisely because this assumption can lapse silently (§14 R10).*
- **A5:** `-1002486420468` is used **only** as a test *source* channel in Phase 5 — *the operator's
  step 7; it already appears annotated `# Test Channel` in `gpt_config.yaml:7`.*
- **A6:** Evals run locally in the devcontainer against a mock Telegram backend, so no eval run ever
  touches Telegram — *`kb/patterns/prompts-and-evals.md:43-45`, and it makes the suite safe to
  re-run on every prompt change.*
- **A7:** Eval model calls bill the operator's subscription — *`kb/architecture/auth.md:27-29`*. ~108
  scenarios per full run; budget accordingly and run the full suite deliberately, not per-commit.
- **A8:** `python -m agent.main` run from inside a Claude Code session needs
  `env -u CLAUDECODE` — *`kb/architecture/auth.md:33-34`.*

## 8. Open questions (blocking)

### Resolved by the operator

Recorded here so the eval labels have a citable source of truth. Each answer is reflected in the
decision named alongside it.

| # | Question | Operator's answer | Lands in |
|---|---|---|---|
| Q1 | Resume attachment mechanism | **Forward from a storage channel** — chosen against this plan's recommendation, knowingly. No VM file, no image-baked document. `send_application` verifies the stored message resolves immediately before sending and fails loudly if it does not | D4, §9, §10 Phase 3/5, R10 |
| Q2 | How to determine a "Russian company" | Skip when the post **explicitly** states employment must be in Russia, the role is based in Russia, or eligibility is "Russia only" — **or** salary is RUB (covered separately). **No inference from post language** | D3 |
| Q3 | What "says USDT/crypto" means | **Narrow:** only when salary or payment itself is in USDT/USDC/crypto. A crypto-industry employer paying fiat does not qualify | D3 |
| Q4 | Salary edge cases | `₽`, `тр`, `т.р.` count as RUB alongside spelled-out forms. A bare figure in thousands shorthand (`тыс`/`тысяч`/`к`/`тр`/`т.р.`) with no other currency marker also counts as RUB. **No salary stated at all ⇒ skip** (disqualifying, not neutral) | D3 |
| Q5 | Contact resolution for channels and emails | **Adopted as designed** — `lookup_contact` gates on real-user verification; channels, bots and email-shaped strings are skipped | D4 |
| Q6 | Public vs. private source channels | **All public.** Uniform `t.me/<channel>/<id>` link construction; no private-channel fallback needed | D6 |
| Q8 | Send identity | **Same Telegram account** as the existing scrapers, with a **freshly registered `api_id`/`api_hash`** — not the pair committed in `tg-scraper` | D2, A2 |
| Q10 | Relocation-required roles | Treated as **non-remote and skipped**, regardless of destination | D3 |
| Q12 | Destination channel and cutover | Destination confirmed as the one annotated `# cloud jobs`; the D7 cutover sequencing (stop `cloud-scraper` in the same window writes flip on) confirmed correct | D7, A4 |
| Q7 | Label wording | **Confirmed the proposed default**: applied → `✅ Откликнулся → @handle`; skipped → `⏭ Не откликнулся — <reason>`, `<reason>` naming the single deciding criterion (`зарплата в рублях`, `офис/гибрид`, `нет Telegram-контакта`, `зарплата не указана`, etc.) | D5, `settings.labels` |
| Q9 | PR test deploy | **Option (a):** a label-gated `pull_request` trigger deploying to a separate `/app/tg-job-applier-preview` stack via the reusable workflow's existing `deploy_dir` override — a real pre-merge deploy, isolated from the eventual production stack | Phase 3 `.github/workflows/tg-job-applier.yml` |

### Still open

`AskUserQuestion` is not available to the planning subagent, so this one is raised here and in chat.

| # | Question | Why it matters |
|---|---|---|
| Q11 | **`telegram` MCP** — still `⏸ Pending approval` with its credentials file absent. A Claude Code session restart has been requested; the result is not yet known. Pending, not resolved. | If it returns, the eval corpus can carry message metadata (ids, source chats) and grade link construction too. If it does not, D8's container-log corpus stands and link construction is covered by unit tests plus the Phase 5 smoke test. |

Q7 and Q9 no longer block anything: Phase 2 label sign-off can proceed with the confirmed skip-reason
vocabulary, and Phase 3's caller workflow has a concrete target (the labeled-PR preview stack).

## 9. Target state

- `agents/tg-job-applier/` exists, self-contained, package named `agent`, `grep -rn TEMPLATE` silent.
- `agent_config.yaml` is committed and secret-free: source channel ids, destination channel id, the
  full criteria prompt (encoding the Q2/Q3/Q4/Q10 resolutions), model `claude-sonnet-5`,
  `allow_writes: false`, and `settings` carrying the delay range, daily cap, dedupe TTL, the resume
  **`(storage_chat, message_id)` reference**, and label strings.
- **No resume file and no resume mount anywhere** — not in the image, not on the VM. The resume is a
  message in a Telegram storage channel, referenced by id.
- `tg-job-applier.env.template` is committed with **names only**: `CLAUDE_CODE_OAUTH_TOKEN`,
  `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION_STRING`.
- `WRITE_TOOLS == {"send_application", "report_to_channel"}`; `lookup_contact` is a read tool.
- `agents/tg-job-applier/evals/` holds the frozen, operator-approved dataset and a harness that runs
  the real `agent.loop.run_once` against a mock Telegram backend.
- `.github/workflows/tg-job-applier.yml` exists, path-filtered, calling the reusable workflow.
- The stack runs at `/app/tg-job-applier` on `157.90.18.149`, journald tag `tg-job-applier`.
- `agents/tg-job-applier/README.md` is the agent's only documentation page.
- The Phase 5 smoke test shows one post to `-1002486420468` producing a labelled destination entry
  and, if it matches, one DM.

## 10. Implementation steps

### Phase 0 — Preserve the corpus (do first; it is perishable)

- [ ] Extract all 509 posts, and the last-30-day slice, from the `cloud-scraper` container log to the
      task folder as newline-delimited JSON. This log is `json-file` on a container `Up 2 months` and
      dies with the next `docker rm` (`kb/patterns/lessons.md:9-13`).
- [ ] Verify the extraction script per the [python skill](../../../.claude/skills/python/SKILL.md)
      before trusting its counts (`CLAUDE.md` § Working style).
- [ ] Expected: a file whose post count matches `grep -c 'Forwarded message:'` exactly.

### Phase 1 — Scaffold (unblocked: the criteria questions are answered)

- [x] Q2, Q3, Q4, Q10 answered — the four that define the criteria the eval labels are written
      against. Labelling may now begin; relabelling *after* prompt iteration is what AC #5 forbids.
- [ ] Q7 still open and blocks the **label strings** in `settings` and any eval expectation that
      references a skip reason. Q9 blocks only the caller workflow. Neither blocks scaffolding.
- [ ] Scaffold with the commands in
      [.claude/skills/new-agent/SKILL.md:30-37](../../../.claude/skills/new-agent/SKILL.md); confirm
      the agent name.
- [ ] `agents/tg-job-applier/agent_config.yaml` — criteria prompt encoding the Q2/Q3/Q4/Q10
      resolutions verbatim in effect, model, `allow_writes: false`, `settings` including the resume
      `(storage_chat, message_id)` reference.
- [ ] `agents/tg-job-applier/tg-job-applier.env.template` — the four names above, values never.

### Phase 2 — Evals before the agent (operator's explicit ordering)

- [ ] `evals/dataset.yaml` — one scenario per corpus post: the post text, an expected
      `applied: true|false`, an expected `contact` when applied, and a one-line reason citing the
      criterion that decided it.
- [ ] Label **strictly against the resolved criteria in §8 *Resolved*** (Q2, Q3, Q4, Q10), before any
      prompt exists to test against. Those answers are now the source of truth for every label.
- [ ] **Operator sign-off gate (step 3).** Present the labelled set. Do not proceed without approval.
- [ ] On approval, record a checksum of `dataset.yaml` in the task folder and split it into a
      **dev slice** (iterate freely) and a **held-out slice** (run only at the end).
- [ ] `evals/run_evals.py` — mock Telegram backend, real `agent.loop.run_once`, real tool handlers,
      real guards; grade the **end state** (`applied`, `contact`), never the transcript
      (`kb/patterns/prompts-and-evals.md:43-50`).

### Phase 3 — Implementation

- [ ] `agent/context.py` — add the Telethon client and the source message to `RunContext`.
- [ ] `agent/tools.py` — `lookup_contact`, `send_application`, `report_to_channel`; delay, daily cap
      and dedupe live inside the handlers, driven by `settings`; every handler returns a dict.
      `send_application` **resolves the stored resume message and the source channel's public
      username before sending**, and fails the run loudly if either is missing — no partial
      application, no retry.
- [ ] `agent/guards.py` — `WRITE_TOOLS = {"send_application", "report_to_channel"}`.
- [ ] `agent/main.py` — Telethon client startup, `events.NewMessage` handler feeding an
      `asyncio.Queue`, `iter_requests()` draining it; dedupe key claimed **before** `run_once`;
      disconnect detection (§14 R7). Keep the existing `ANTHROPIC_API_KEY` /
      `CLAUDE_CODE_OAUTH_TOKEN` refusals untouched.
- [ ] `deploy/docker-compose.yaml` — rename tags/paths only. **No resume mount** (Q1 chose the
      storage-channel path), so the template's mount set is unchanged.
- [ ] `tests/` — keep the shipped config and guard tests; add unit tests for vacancy-link
      construction, contact classification (user vs. bot vs. channel vs. email), the cap, dedupe, and
      the **resume-unresolvable path failing without sending**.
- [ ] `README.md` — rewritten; the agent's only documentation page.
- [ ] `.github/workflows/tg-job-applier.yml` — per Q9.

### Phase 4 — Validation

- [ ] `cd agents/tg-job-applier && uv lock && uv sync && uv run pytest -q`
- [ ] `ruff check . && ruff format --check .`
- [ ] `docker build -t tg-job-applier:local .` — proves the bundled `claude` CLI assertion passes.
- [ ] Run the eval suite on the **dev slice**; iterate the **prompt** only. If a case cannot be
      fixed by prompting, that is a finding to report — not a licence to edit the label.
- [ ] Run the **held-out slice** once. Report both numbers honestly, per AC #3 and AC #5.
- [ ] `/task-review` over the full diff; resolve block-tier findings.
- [ ] Human review gate, then present the PR title and body and **wait for explicit approval**
      before `gh pr create` (`CLAUDE.md` § Git).

### Phase 5 — Rollout

- [ ] Operator provisions the VM per
      [kb/runbooks/new-agent-vm-setup.md](../../runbooks/new-agent-vm-setup.md): `/app/tg-job-applier`,
      `claude-config` chowned `10001:10001`, and the `.env.tg-job-applier` file. **No resume file** —
      Q1 chose the storage-channel path. Claude supplies the exact lines and applies none of them.
- [ ] Operator registers a **fresh** `api_id`/`api_hash` and generates the session string for the
      send identity on the **same account** as the existing scrapers (Q8).
- [ ] Operator posts the resume to the storage channel and gives its `(chat, message_id)` for
      `agent_config.yaml`. Verify it resolves from the sending session **before** the first deploy —
      an unresolvable reference means every matching post fails loudly rather than applying.
- [ ] Deploy with `allow_writes: false`. Confirm `docker compose ps` and a clean
      `journalctl CONTAINER_TAG=tg-job-applier` start line.
- [ ] **Observation phase.** Watch decisions in journald with nothing written. `cloud-scraper` keeps
      serving the destination channel throughout (D7).
- [ ] Operator posts a test message to `-1002486420468` (step 7); confirm the decision trace.
- [ ] On the operator's word: flip `allow_writes: true` (config-only redeploy) **and** stop
      `cloud-scraper` in the same window, to avoid duplicate destination posts.
- [ ] Re-run the step-7 smoke test with writes on; confirm the labelled destination entry and, if it
      matched, the DM.

## 11. Dependencies and sequencing

- Phase 0 is first and is time-sensitive: the corpus lives in a container log that any recreate
  destroys.
- Q2, Q3, Q4 and Q10 are **answered**, so Phase 2 labelling is unblocked — and it is still the
  critical path, because the operator sign-off on the labels gates all prompt iteration.
- Q7 and Q9 are now resolved (label wording confirmed; the labeled-PR preview stack chosen for Q9),
  so neither blocks anything further. Of everything left, only **Q11** remains open, and it is not on
  the critical path: it only changes how rich the eval corpus can be (message metadata vs. text
  only), and D8's container-log fallback already works without it.
- Q1's resolution removes a dependency rather than adding one: no resume file means the compose file
  is a pure rename, and the VM provisioning list is one item shorter.
- Phase 3 tool work and Phase 2 harness work can proceed in parallel once Phase 1 lands, because the
  harness targets the mock backend.
- The VM secrets file must exist **before** the first deploy — a deploy against a missing env file
  fails at `docker compose up`, by design (`kb/architecture/cicd.md:58-62`).
- Deploys serialise on the reusable workflow's constant `vm-deploy` concurrency group
  (`agent-deploy.reusable.yml:110-112`); the four `bb-*`/scraper stacks are unaffected.
- `allow_writes: true` and stopping `cloud-scraper` are one coordinated step, not two.

## 12. Validation

| Check | Command | Expected |
|---|---|---|
| Corpus complete | compare extracted count to `docker logs cloud-scraper \| grep -c 'Forwarded message:'` | Equal; 30-day slice ≈ 108 |
| Scaffold fully specified | `grep -rn TEMPLATE agents/tg-job-applier` | No output |
| No secret committed | `gitleaks` via the [secrets skill](../../../.claude/skills/secrets/SKILL.md) over the diff | Clean |
| Config secret-free | read `agents/tg-job-applier/agent_config.yaml` | Channel ids and prompt only; no api_id/api_hash/session |
| Write set complete | `agents/tg-job-applier/tests/test_guards.py` | Both write tools denied at `allow_writes: false`; gate inert at true |
| Unit tests | `uv run pytest -q` | Green, incl. link construction, contact classification, cap, dedupe, and resume-unresolvable |
| Resume reference live | resolve the configured `(storage_chat, message_id)` from the sending session | Resolves to the expected document; a failure here must block the first deploy |
| Lint | `ruff check . && ruff format --check .` | Clean |
| Image | `docker build -t tg-job-applier:local .` | Bundled-CLI and import assertions pass (`Dockerfile:39-40`) |
| Classification (dev slice) | `uv run python evals/run_evals.py --slice dev` | 100%, reached by prompt changes only |
| Classification (held-out) | `uv run python evals/run_evals.py --slice holdout` | 100% (AC #3); any gap reported, never relabelled |
| Labels unmodified | re-checksum `evals/dataset.yaml` against the signed-off value | Identical |
| Deploy green | the caller's run, per the [gh-logs-analyst](../../../.claude/agents/gh-logs-analyst.md) subagent | Image pushed; post-deploy running check green; no `Error:` lines |
| Stack live | MCP `ssh_execute pulse: cd /app/tg-job-applier && docker compose ps` | One running container |
| Clean start | MCP `ssh_execute pulse: journalctl CONTAINER_TAG=tg-job-applier --since '10 minutes ago'` | `agent starting: model=claude-sonnet-5 allow_writes=false`; no `AGENT ALERT` |
| No writes while gated | same journald trace after a real post | Write-gate deny line; destination channel unchanged |
| Smoke test | operator posts to `-1002486420468` | Decision trace, then (writes on) one labelled destination entry |

Do not read `gh run view --log` directly — a blocked Azure Blob host returns **empty, not an error**
(`CLAUDE.md` § Environment limits). This plan already hit the same class of trap once: `docker logs
--since 30d` printed nothing to stdout while erroring on stderr.

## 13. Rollback

- **Phase 0–3 (pre-merge).** Nothing outside the repo changed; abandon the branch.
- **Phase 4.** Local only. `docker rmi tg-job-applier:local`.
- **Phase 5, deployed with `allow_writes: false`.** No external effect by construction. Stop with
  `cd /app/tg-job-applier && docker compose down` (`kb/runbooks/new-agent-vm-setup.md:69-72`).
- **Phase 5, writes enabled — the only phase with irreversible effects.**
  - *Immediate stop:* `docker compose down` on the VM. Fastest; the operator does not need CI.
  - *Revert behaviour, keep it running:* set `allow_writes: false` in `agent_config.yaml`, merge, and
    redeploy. Config-only — seconds, no rebuild (`kb/architecture/overview.md:33-36`).
  - *Bad image:* redeploy the previous `type=sha` tag with `build: false` + `image_tag`
    (`kb/architecture/cicd.md:29-34`). **Untracked procedure** — `cicd.md:74-75` records that
    rollback has never been exercised. Phase 5 is where it first might be.
  - *Restore the old pipeline:* `cd /app/cloud-scraper && docker compose up -d`. It is a local
    `build: .` stack, so it comes back without CI or a registry.
  - **A sent DM cannot be rolled back.** Deleting it removes the message, not the recipient's
    notification. This is why the daily cap and the observation phase exist.

## 14. Risks and challenges

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **R1 — Live Telegram API credentials committed in plaintext in `alexeibugrov/tg-scraper`** (`gpt_config.yaml`, `crypto_config.yaml`, present in `HEAD`). The repo is **private** — confirmed by the operator | Certain (verified) | **Medium**, down from High: a private repo bounds exposure to its access list rather than the public internet. Still a plaintext credential shared across two live scrapers, so anyone with repo access holds a working app pair, and the exposure would become public the moment the repo's visibility changed | The operator is **rotating the pair themselves** (registering fresh credentials). This agent uses a freshly registered `api_id`/`api_hash` regardless (Q8), so it never inherits the exposure. Git-history purging is a **nice-to-have**, not urgent, unless the repo is ever made public — tracked in §18 |
| **R2 — DMs to the wrong person** (channel handle, email-shaped string, stale contact) | Medium | High — reputational, from the operator's real account | `lookup_contact` must confirm a real **user** before `send_application`; eval cases built from the actual `office@billions` / `@devops_jobs` corpus strings; observation phase first |
| **R3 — Duplicate DMs from cross-posted vacancies** | Medium | Medium — looks like spam to one recruiter | D10 dedupe key claimed before the model call (`kb/patterns/lessons.md:42-47`) |
| **R4 — Telegram anti-spam (`PeerFloodError`, account limitation)** | Low | High — could restrict the account that also runs two live scrapers | Volume is ~3.6 posts/day *before* filtering, so DMs land under 2/day; randomised delay plus a categorical daily cap; `send_application` must surface `PeerFloodError` as an `AGENT ALERT`, never retry it |
| **R5 — Eval labels quietly bent to reach 100%** | Medium — AC #3 creates exactly this pressure | High — a green suite that proves nothing (AC #5) | Labels written before the prompt; operator signs off; checksum recorded; held-out slice run once at the end; an unfixable case is reported, not relabelled |
| **R6 — Duplicate destination posts during cutover** | Medium if unsequenced | Low but visible | D7: `allow_writes: true` and stopping `cloud-scraper` happen in the same window |
| **R7 — Telethon disconnects and the container keeps running** | Medium over weeks | High — silent total failure; posts stop arriving and nothing alerts | Treat a lost connection as fatal: log an `AGENT ALERT` line and exit non-zero so `restart: unless-stopped` recreates the container. `kb/patterns/lessons.md:15-18` — silence is not success |
| **R8 — Partial failure: DM sent, label forward fails** | Low | Medium — the operator believes no application was sent | `send_application` returns the sent message id; that id appears in the journald trace regardless of what `report_to_channel` does. Never retry a `send_application` that already sent (`kb/patterns/lessons.md:20-22`) |
| **R9 — Prompt-injection from post text** (posts are third-party content, and this agent holds send-capable credentials) | Low | High | `tools=[]` and `setting_sources=[]` (`agent/loop.py:66-72`) leave only the three declared tools; the post text is data in the prompt; `lookup_contact` bounds who can be messaged; the daily cap bounds how many |
| **R10 — Resume storage-channel message edited or deleted.** Now an **active, accepted** risk: Q1 chose this path knowingly over the VM-mounted file | Medium over time — a stored message is easy to tidy away months later | Medium — every matching post fails to apply until it is fixed. Bounded to *missed* applications, never *wrong* ones | `send_application` resolves the stored message immediately before every send and **fails the run loudly** (`AGENT ALERT`, no retry, no DM without the resume), so the failure is visible in journald within one post rather than discovered weeks later. Verified once more at provisioning time (§10 Phase 5) and covered by a unit test |
| **R11 — Session string leaks** (full-account credential) | Low | High — full account takeover | Env file only, `chmod 600`, never in `agent_config.yaml`, never in a log line, never read by Claude; `.gitignore:7-8` already covers `.env*` |
| **R12 — Eval runs consume subscription rate limit** shared with the operator's own Claude Code sessions | Medium | Low–Medium — degrades the operator's tooling mid-task | ~108 scenarios per full run; iterate on the dev slice, run the full suite deliberately (`kb/architecture/auth.md:27-29`) |
| **R13 — Adding a stack to a busy shared VM** (5 running containers) | Low | Medium | 58G disk and 6.5G RAM free; `mem_limit: 1g` in the compose template caps it; deploys serialise on `vm-deploy` |

**Blast radius, stated plainly.** Worst realistic bad run: the agent DMs a stranger, from the
operator's personal Telegram account, attaching the operator's real resume, about a job the operator
did not want. Four independent things must all fail for that: the classifier, `lookup_contact`, the
daily cap, and the operator's observation phase. Three of the four hold even with `allow_writes:
true`.

## 15. Escalation triggers hit

This plan crosses several `CLAUDE.md` gates. None is a reason not to proceed; each is a place the
operator must act rather than Claude.

1. **Shared production VM.** `157.90.18.149` runs five live containers including `bb-sdk-agent-prod`.
   A new stack is added and a live one (`cloud-scraper`) is eventually stopped.
2. **Live production service handover.** `cloud-scraper` has been up 2 months and currently serves the
   destination channel. D7 sequences the cutover; nothing is stopped in this task without the
   operator's explicit word.
3. **New secrets provisioning.** Four env names, including a full-account Telegram session string.
   Operator-provisioned only — Claude writes the empty scaffold, supplies the exact lines to paste,
   and never applies them or reads the result (`CLAUDE.md` § Secrets).
4. **A committed real secret found in a private repo (R1).** Reported, not touched. Private
   visibility lowers the severity but not the fact; the operator is rotating the pair themselves.
5. **PR-only, with the present-and-wait gate.** No push to `main`; the PR title and body are quoted
   and approved before `gh pr create`, in every permission mode.
6. **A CI caller change for the PR deploy (Q9).** Confined to the caller; the reusable workflow is
   not touched.
7. **An MCP-shaped permission gap.** The `telegram` MCP is unavailable this session (Q11) — reported
   rather than routed around (`CLAUDE.md` § Environment limits, § Permission gaps).
8. **A new outbound-messaging capability from a personal identity.** No existing agent in this
   factory sends anything as the operator. `/task-review` should weigh the tool surface in §6 D4 on
   that basis.

## 16. Observability and security impact

**Observability.**

- New journald tag `tg-job-applier`, per the compose template's `logging.driver: journald`. Unlike
  `cloud-scraper` (still on `json-file`, so its history dies with the container), this agent's
  decision trace survives redeploys and reboots.
- Every run logs the classification, each tool call with arguments, each tool result, and terminal
  cost/turns (`agent/loop.py:87-133`). That trace is the only record of *why* an application was or
  was not sent.
- `AGENT ALERT` on any non-`COMPLETED` run (`agent/loop.py:120-122`), plus new alert lines for: daily
  cap reached, `PeerFloodError`, `lookup_contact` rejecting a handle, and Telethon disconnect (R7).
- Blind spots to accept: the eval suite's honesty is not machine-checkable beyond the checksum, and
  dedupe state is in-process, so a restart is invisible in the log unless it is logged explicitly.

**Security.**

- Adds three env names to the VM, one of which (`TELEGRAM_SESSION_STRING`) is a **full-account**
  credential — a materially higher-value secret than any other agent in this factory holds.
- Container posture is inherited unchanged: `cap_drop: ALL`, `no-new-privileges`, `mem_limit`,
  non-root uid 10001, read-only config mount.
- No IAM, RBAC, or repository-secret change. `SSH_PRIVATE_KEY` is reused as-is.
- The agent gains the ability to message arbitrary Telegram users. That is the point of the task, and
  it is the single largest security delta — bounded by the write gate, `lookup_contact`, and the cap.
- **No personal resume document exists on the VM, in the image, or in git** (Q1). The resume lives
  only as a Telegram message in the operator's storage channel; the config carries an id, not a file.
  That is a genuine security win of the storage-channel choice, and it offsets the reliability cost
  recorded in R10.
- The agent also gains **read** access to the resume storage channel via the shared account session.
  Nothing narrows the session to specific chats — an MTProto user session is all-or-nothing, which is
  the same exposure the two existing scrapers already carry.

## 17. Approval checklist

- [ ] Scope confirmed (Critical — shared VM, live service handover, personal-identity sending)
- [ ] Assumptions A1–A8 accepted (A4 now confirmed rather than assumed; A4b added for the resume
      storage channel)
- [x] Q1–Q10, Q12 resolved by the operator and recorded in §8 *Resolved*
- [ ] Q11 rechecked after the Claude Code restart; D8's corpus stands either way
- [ ] Rollback accepted, including that a sent DM is not reversible
- [ ] Escalation triggers acknowledged
- [ ] Eval honesty protocol accepted (labels frozen and checksummed before prompt iteration)

## 18. Out of scope / follow-ups

- **Rotate the committed Telegram API credentials in `alexeibugrov/tg-scraper`** (R1) — **tracked,
  operator-owned, in progress.** The repo is private, so this is a hygiene fix rather than an
  incident: the pair is still in plaintext in `HEAD` and shared by `cloud-scraper` and
  `crypto-scraper`, both of which need their configs updated when the new pair lands. **Purging git
  history is a nice-to-have**, not urgent — it becomes urgent only if the repo is ever made public.
- **Retire `cloud-scraper`** once this agent has run with writes enabled for a sustained period.
- **Move `crypto-scraper` into the factory**, or decide deliberately that it stays a hand-built VM
  stack.
- **Persist dedupe state** across restarts if cross-posting proves more frequent than assumed (D10).
- **Exercise the rollback procedure** — `kb/architecture/cicd.md:74-75` records it as never tested.
- **Restore the `telegram` MCP** so future eval corpora can be pulled with message metadata (Q11).
- **Switch `cloud-scraper` to journald** if it survives, so its history stops dying with the
  container.
- **Reply-quality evals.** This plan grades the *decision*, not the wording of the sent message.

---

## Appendix A — The ask, verbatim (source of truth)

Reproduced unedited. Where §1–§18 and this appendix disagree, **this appendix wins** and the plan is
wrong and must be corrected.

### Context

> Operator has a parser of Telegram channels with job offers
> (https://github.com/alexeibugrov/tg-scraper — "cloud-scraper"). Problem: sees messages too late
> sometimes, but replying first is crucial since competition is huge. Idea: build an agent that reads
> messages from the parser (already filtered) and if the offer fits expectations, sends an automatic
> message to apply.
>
> Operator's mental model: take the cloud-scraper logic, but at the end, instead of just sending to
> the dedicated channel, send to an LLM and ask if the offer meets certain criteria. If yes, reply to
> the author. If not, ignore. Then forward the message to the operator's channel with a mark: reply
> sent / not sent. Evals should be built first and the agent tested locally before anything else.

### Vacancy criteria for the prompt

> - Never reply to Russian companies
> - Never reply to hybrid/office vacancies
> - Reply only when a Telegram contact is specified — never reply via URL or other methods
> - Never reply if salary is specified in Russian rubles (руб, р, т.р)
> - Reply always if the job offer says USDT(C) or other crypto
> - Reply always if the offer says salary in $, USD, EUR, or B2B
> - Reply for full-time and part-time positions

### Reply text

> "Добрый день, могу предложить свою кандидатуру по вакансии {link to vacancy in original channel}
> Мое резюме: {attached files with resume}"
>
> Operator explicitly wants to discuss how best to attach the file: direct send vs. forwarding from
> another Telegram channel where the file is stored, or better ideas — open question, not decided.

### Task steps as given (0-7)

> 0. Clone and explore the cloud-scraper repo.
> 1. Ask any question before proceeding.
> 2. Use the scraper as foundation and build the agent based on requirements.
> 3. Use MCP to access the channel where messages are currently forwarded to, take messages from the
>    last month, build an evals dataset, label true/false based on operator's criteria, and get the
>    operator's approval on the labeled dataset.
> 4. Test the agent against evals. Use the Sonnet 5 model.
> 5. Add a CI/CD workflow.
> 6. Get explicit operator approval on code quality, then file the PR, and allow a test deploy from
>    the PR.
> 7. Confirm the deployment, then ask the operator to send a test message. A new test-SOURCE channel
>    has been created for this: `-1002486420468`.

### Acceptance criteria

> 1. Agent gathers job offers and automatically replies to them based on criteria.
> 2. The offer can still be tracked in the same destination channel as today, but forwarded messages
>    are now labeled (applied / not-applied).
> 3. Evals are honest and the bot passes 100% of them.
> 4. Bot and evals run using the operator's Claude Code subscription (never a raw API key) — this is
>    already this factory's standing convention for every agent, not new.
> 5. Claude Code (i.e., you / me) must not cheat on evals — label and evaluate honestly.
> 6. Agent is deployed, CI/CD workflow is tested end-to-end.
> 7. The prompt covers all the criteria correctly.

### Where this plan deviates from the ask, and why

Every row below has been put to the operator. Nine are now settled; the reasons are kept because they
are why the question was worth asking.

| Ask | Plan | Reason | Status |
|---|---|---|---|
| Criteria: "never reply to Russian companies" | Skip only on an **explicit** Russia-employment / Russia-based / Russia-only statement, or RUB salary. No inference from post language | Post language is not company nationality; the corpus contains a US employer posting in Russian | **Resolved (Q2)** |
| Criteria: "reply always if the offer says USDT(C) or other crypto" | Fires only when **salary or payment itself** is in crypto | 278 `crypto` mentions are mostly company vocabulary, not salary currency | **Resolved (Q3)** |
| Criteria: "salary in Russian rubles (руб, р, т.р)" | Adds `₽`, `тр`, `т.р.`, and bare thousands-shorthand with no other currency marker. **No salary stated ⇒ skip** | `₽` is the most common RUB form in the corpus and was absent from the stated list; the silent case was undecided | **Resolved (Q4)** |
| Criteria (unstated): relocation-required roles | Treated as non-remote and skipped, regardless of destination | ~22 corpus mentions; not covered by the original criteria | **Resolved (Q10)** |
| Reply text: `{attached files with resume}` | Forward from a storage channel, with a resolve-or-fail check before every send | The operator chose this over the plan's VM-mounted-file recommendation, knowing the reliability trade (R10) | **Resolved (Q1), against recommendation** |
| Reply text: `{link to vacancy in original channel}` | §6 D6 constructs `t.me/<channel>/<id>` uniformly | Only 8 of 509 posts contain a `t.me/` link; all source channels are public, so no fallback is needed | **Resolved (Q6)** |
| AC #2: destination channel keeps receiving posts | §6 D7 sequences the `cloud-scraper` cutover | Both stacks writing at once would double-post every message | **Resolved (Q12)** |
| Step 3: "Use MCP to access the channel where messages are currently forwarded to" | §6 D8 uses the `cloud-scraper` container log instead | The `telegram` MCP is `⏸ Pending approval` and its credentials file is absent; a session restart is pending | **Open (Q11)** — corpus works either way |
| Step 6: "allow a test deploy from the PR" | Q9: labeled-PR preview stack at `/app/tg-job-applier-preview` via `deploy_dir` override | The caller template triggers only on `push` to `main`/tags, and `workflow_dispatch` is not dispatchable from a branch until the workflow exists on the default branch | **Resolved (Q9)** |
| AC #2: "labeled (applied / not-applied)" | §6 D5 forwards then replies with the label; exact wording confirmed in Q7 | Telethon cannot caption a forwarded text message, and the skip-reason vocabulary feeds the eval labels | **Resolved (Q7)** |
