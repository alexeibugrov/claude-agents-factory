# upwork-scout

Every 30 minutes upwork-scout scrapes recent Upwork job postings through Apify and stores every
posting in Postgres. Each job it has never seen before that passes the code prefilters is posted
to a private Telegram group as **one message per offer**, from a separate agent account. When a
member replies to an offer with a trigger word or sign (`+` or `go` by default), a **writer**
agent drafts a proposal, and the agent replies in the same chat with plain text: the vacancy link
and the proposal. It never applies on Upwork: the human reads the draft and sends it. The stored
postings are also a market-data corpus for later analysis of demand trends (not built yet).

A **screener** agent that triages jobs before they are offered is built but parked
(`settings.pipeline.screening_enabled: false`).

Design and decisions: [plan.md](../../kb/tasks/003-upwork-agent-2026-10-22/plan.md), and for the
offer and reply flow, [plan-reply-flow-and-dind.md](../../kb/tasks/003-upwork-agent-2026-10-22/plan-reply-flow-and-dind.md).

## Architecture

```text
agent container (python -m agent.main; one long-lived process, two loops)
 cycle, every interval:
  1 SCRAPE    for each settings.apify.searches: one Apify actor run   → scrape_runs row
  2 INGEST    INSERT jobs ON CONFLICT (job_id) DO NOTHING             ← DEDUP on jobId
                first sighting → pipeline row (pending | skipped_repost | skipped_stale)
                known          → refresh jobs, add job_versions, never re-queued
  3 PREFILTER pending → config thresholds → prefiltered (reason logged)
  4 SCREEN    parked; when enabled: pending → screener → suitable | unsuitable
  5 OFFER     ≤ N pending (or suitable) → one group message each      → offers row, offered
 poll, on a reply event or every poll_interval_s (only with allow_writes):
  6 READ      group messages after the stored cursor; a reply to an offer with a trigger
                token, not from the agent itself                      → requested
  7 DRAFT     claim ≤ N requested → writer run → submit_proposal     → proposals row
  8 DELIVER   plain-text reply to the trigger: link + proposal        → delivered
        │
  db (postgres:16.15, volume upwork-scout-pgdata) ── backup (nightly pg_dump → ./backups)
```

**Dedup is the database's job.** `jobs.job_id` is the primary key. Only a job's first-ever insert
creates its `pipeline` row, and the agents read only from `pipeline`. So a job is screened once,
whatever happens later: an UPDATED or REAPPEARED record, the same job from another search, or a
repost. The actor's incremental mode only saves Apify cost; it is never trusted for dedup.

**`pipeline` is the ledger of what the agents processed:** one row per job, with its status,
attempts and last reason. Nothing re-queues a job automatically.

| File | Role |
| --- | --- |
| [agent_config.yaml](agent_config.yaml) | **Committed, secret-free.** Models, prompt file pointers, searches, Apify caps, pipeline caps, prefilters, Telegram target. Bind-mounted at deploy. |
| [prompts/](prompts/) | The role prompts, one plain-text file each (`writer.txt`: wrapper + the operator's proposal metaprompt + About me). Shipped and bind-mounted like the config. |
| [agent/config.py](agent/config.py) | Typed load + fail-fast validation (`maxResults` ≤ 10, query ≤ 80 words, unique search slugs, `chat_id` when `allow_writes`). |
| [agent/scrape.py](agent/scrape.py) | One actor run per search; cost from charged events; Upwork's total from the run log; failures returned, never raised. |
| [agent/store.py](agent/store.py) | Ingest + dedup, the pipeline ledger, claims, the Telegram outbox. |
| [agent/migrations/](agent/migrations/) | Forward-only SQL, applied at startup under an advisory lock (004 adds `offers.request_text`). |
| [agent/prefilter.py](agent/prefilter.py) | Config-driven rules on structured fields; null = off. |
| [agent/render.py](agent/render.py) | Job → prompts (job text delimited as untrusted data) and → Telegram HTML. |
| [agent/tools.py](agent/tools.py) | `submit_screening` / `submit_proposal`: pure, record on `RunContext`. |
| [agent/guards.py](agent/guards.py) | Write gate (empty `WRITE_TOOLS`) and `delivery_allowed()`, the Telegram veto. |
| [agent/loop.py](agent/loop.py) | `run_once()`: one job through one role. |
| [agent/pipeline.py](agent/pipeline.py) | `cycle()` (stages 1-5) and `poll()` (stages 6-8), with injectable dependencies. |
| [agent/telegram.py](agent/telegram.py) | Telethon client of the agent account: post offers, read the group after a cursor, reply. |
| [agent/telegram_login.py](agent/telegram_login.py) | Operator-only interactive login that creates the session file. |
| [agent/main.py](agent/main.py) | Startup refusals, migrations, the cycle and poll loops, `--once`, SIGTERM. |
| [deploy/docker-compose.yaml](deploy/docker-compose.yaml) | `agent` + `db` + `backup`. |
| [deploy/docker-compose.local.yaml](deploy/docker-compose.local.yaml) | Override for a local run in the devcontainer. |

## Configuration

- **Searches:** `settings.apify.searches` is a list of `{name, run_input}` entries, using `query`
  or an Upwork `searchUrl`. `defaults_input` is merged under each. Each search gets its own Apify
  run and incremental state (`stateKey = upwork-scout-<name>`). **Renaming a search resets its
  state.**
- **Three searches**, tuned 2026-10-23 against the logged-in Upwork UI
  ([report](../../kb/tasks/003-upwork-agent-2026-10-22/search-tuning-report.md)):
  `ai-agents-automation`, `ai-llm-claude`, `devops-cloud`. Each is one Upwork `searchUrl` with a
  pure OR list of quoted phrases, `t=0,1` (hourly and fixed) and `amount=1000-` (fixed price only).
  - **No `location`, `hourly_rate` or `contractor_tier` in the URLs.** The actor's location filter
    loses clients stored as country codes (FRA, NLD, DEU; about 4% of in-region jobs), and
    `hourly_rate` drops every hourly job that states no rate. Regions and rates are prefilters
    instead.
  - **Query rules:** at most 80 words per query, counting `-` and `/` parts (validated at load:
    Upwork answers a query over ~90 words with a silent 0). Phrases are not stemmed, so list
    singular and plural ("ai agent" OR "ai agents"). Quoted single words are stemmed, so avoid
    ones that broaden ("agentic" matches "agent"). Don't mix AND with OR. Re-measure before adding
    a term.
  - **Silent-zero alarm:** every run logs Upwork's own count for the search (`upwork_total`, also
    in `scrape_runs.upwork_total`). Missing or 0 on a succeeded run raises
    `AGENT ALERT … query is likely broken`.
- **`maxResults` ≤ 10** per run, enforced by config validation and by Apify (`max_items`).
- **`maxAgeMinutes: 120`** is a recovery margin, not the cadence. Jobs already emitted are never
  re-billed, so a window wider than the 30-minute interval costs nothing. It lets the agent catch
  up after roughly three missed cycles (failed run, deploy, downtime, Upwork indexing lag). An
  outage longer than that loses the jobs published during it.
- **Prefilters** (`settings.prefilter`): every rule is off while `null`, and a job with no value
  for a rule's field passes it. Active today:
  - `min_hourly_rate: 70`: drops hourly ranges whose top is below $70; hourly jobs with no rate pass.
  - `min_fixed_budget: 1000`: a backstop for the URLs' `amount=1000-`.
  - `include_client_country_codes`: a region allow-list (Europe, Northern America, Western Asia,
    Australia and New Zealand; ISO3) on the actor's `clientCountryCode`.

  Changing a threshold is a config-only redeploy.
- **Prompts:** each role's prompt is its own file, `system_prompt_file: prompts/<role>.txt`
  (relative to the config; an inline `system_prompt` also works), so every prompt change is a
  readable diff. The operator owns `## Criteria` in the screener prompt, and the metaprompt and
  ABOUT ME in the writer prompt. ABOUT ME holds no contact details or employer and client names,
  and the writer is told never to put them in a proposal. Every verdict and draft records the
  `prompt_sha` of the prompt that produced it.
- **Pipeline:** `screening_enabled` (off: every prefiltered job is offered; on: only suitable ones,
  with their score), `max_offers_per_cycle` (default 50), `max_draft_per_cycle` (proposals per
  poll), `max_attempts` per writer request.
- **Secrets** (`.env.upwork-scout`, see [upwork-scout.env.template](upwork-scout.env.template)):
  `CLAUDE_CODE_OAUTH_TOKEN`, `APIFY_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`,
  `POSTGRES_PASSWORD`. The db and backup containers get only `POSTGRES_PASSWORD`, from
  `.env.upwork-scout-db` ([template](upwork-scout-db.env.template)). `ANTHROPIC_API_KEY` must stay
  unset; the agent refuses to start with it.

## Telegram

Everything happens in one private group (`settings.telegram.chat_id`, optionally a forum topic via
`topic_id`), as in the operator's `bb-trade-agent` `info_agent`. A **separate agent account**
posts. Its API id and hash are in the env file, and its login is in a per-stack Telethon
**session file**.

- **Offer:** one HTML message per job: linked title, budget, client, applicants, skills, and the
  score when screening is on.
- **Trigger:** a reply to an offer whose first word is one of `triggers`, case-insensitive (`+`,
  `go`; "google" and "+1" do not match, and a trigger word later in the text never fires). It can
  come from any member. The agent's own messages and messages that aren't replies are ignored.
- **Instructions:** text after the trigger, typically the client's application questions pasted
  from Upwork ("+ 1. Which clouds…"), is stored in `offers.request_text` and reaches the writer as
  `<operator_instructions>`: the metaprompt's "Additional instructions", answered in order. The
  actor's default output has no questions field; only `enrichDetails`, which needs the operator's
  Upwork session token, returns them.
- **Proposal:** plain text, ready to copy, as a reply to the trigger message. The first message
  holds the vacancy link and then the proposal. A separate "Check before sending" message follows
  when the writer left notes.
- **Repeats and failures:**
  - A second bare trigger gets "Already writing it." or "Already sent above." instead of a second
    draft. A trigger with instructions on a delivered offer writes a new version.
  - A writer failure that has used up `max_attempts` gets a short error reply. A new trigger
    retries it.
- **Event wake-up, cursor read:** a Telegram new-message event for a reply wakes the poll at once;
  without one, it runs every `poll_interval_s` (60) as a safety net. The event only signals: the
  poll always reads the messages after the last one it read, stored in `telegram_cursor`, so a
  reply is handled exactly once, and a silently dropped update stream, a restart or a deploy
  misses nothing. The very first poll starts at the newest message and never replays history.

The session file grants full access to the agent account. Keep one session per place (VM, local)
and never share one with another stack: Telegram can revoke a session it sees used from two IPs
at once.

## Safety and cost

- `allow_writes: false` (the default) suppresses every offer and logs
  `WRITE GATE: delivery suppressed job=<id>`. The Telegram client is not started, so nothing is
  read and no proposal is written.
- The model tools change nothing; a failed run is safe to retry (up to `max_attempts`). A
  subscription rate limit requeues the batch without spending attempts and skips the cycle's
  remaining agent stages.
- Per-cycle caps: `max_screen_per_cycle`, `max_draft_per_cycle`. A backlog waits; nothing is
  dropped.
- Apify: $0.001 per run plus $0.001 per job, at most 10 jobs per run, and Apify enforces
  `max_total_charge_usd` per run. The ceiling is $15.84/month per search. With three searches,
  measured volume is about $15/month: 3 × $1.44 in run fees plus about 370 jobs a day. The three
  overlap (about 80 of 280 daily hits), and Apify bills both copies. The monthly budget is set on
  the Apify account, not here. Each run's cost is still recorded in `scrape_runs.apify_cost_usd`,
  computed from `chargedEventCounts`, because Apify's `usageTotalUsd` under-reports it.
- Writer runs happen only on a trigger reply: at most `max_draft_per_cycle` per poll and
  `max_attempts` per request. Anyone in the group can trigger them, so keep the group private.
- Blast radius: a bad run posts noisy offers or drafts into the private group and spends Apify
  credit within the caps above. It cannot apply on Upwork or message anyone else.

## Develop

```bash
cd agents/upwork-scout
uv sync
uv run pytest -q          # DB tests use a throwaway cluster (needs pg_ctl; skipped otherwise)
ruff check --config "${LINT_CONFIGS}/ruff.toml" . && ruff format --check --config "${LINT_CONFIGS}/ruff.toml" .

# Try the scrape alone: the configured searches through the agent's own scrape code, printed,
# nothing stored. Uses a separate "-manual" stateKey so it never eats the agent's jobs.
export APIFY_TOKEN=…
uv run python scripts/try_scrape.py [--fresh] [--max 3] [--search NAME] [--out jobs.json]
# Experiments: --url URL (or SEARCH_URL=…), --set KEY=JSON, --find TEXT, --state-suffix S (own
# incremental state per experiment, e.g. to walk a search back 10 jobs per run). Docker-only host:
scripts/try_scrape.sh --fresh --url 'https://www.upwork.com/nx/search/jobs/?q=n8n' --out /out/n8n.json

# One live cycle against a local Postgres, writes off. Tokens exported in YOUR shell only.
# APIFY_STATE_SUFFIX keeps the VM's incremental Apify state untouched (same Apify account).
export DATABASE_URL=postgresql://…  APIFY_TOKEN=…  CLAUDE_CODE_OAUTH_TOKEN=…  APIFY_STATE_SUFFIX=local
env -u CLAUDECODE uv run python -m agent.main --once
```

Run the whole stack locally in the devcontainer (Docker-in-Docker), same compose file as the VM
plus [deploy/docker-compose.local.yaml](deploy/docker-compose.local.yaml). The differences:

- the image is built from the checkout, not pulled from GHCR;
- logs use Docker's default driver (`docker compose logs`), because there is no journald;
- the db trusts connections on the stack network, so no `.env.upwork-scout-db` and no
  `POSTGRES_PASSWORD`; it publishes no port, as on the VM;
- `APIFY_STATE_SUFFIX=local` keeps the VM's incremental Apify state untouched;
- the config is `agent_config.local.yaml` (gitignored), so `allow_writes` and `chat_id` flip without a commit;
- the agent runs as the devcontainer user (uid 1000), so the bind mounts stay writable without `chown`;
- no memory limits: the devcontainer cannot delegate the cgroup memory controller to its inner
  dockerd, and any limit fails with "memory.swap.max: no such file";
- no nightly backup.

```bash
cd agents/upwork-scout/deploy
export COMPOSE_PROJECT_NAME=upwork-scout-local COMPOSE_FILE=docker-compose.yaml:docker-compose.local.yaml
cp ../agent_config.yaml agent_config.local.yaml              # gitignored; flip allow_writes/chat_id here
mkdir -p claude-config telegram-session
cp ../upwork-scout.env.template .env.upwork-scout && chmod 600 .env.upwork-scout  # fill it (POSTGRES_PASSWORD not needed)
docker compose run --rm -it agent python -m agent.telegram_login   # once, only for Telegram; a LOCAL session
docker compose up --build                                   # Ctrl-C stops; `docker compose logs -f agent`
docker compose exec db psql -U upwork_scout -c 'SELECT status, count(*) FROM pipeline GROUP BY 1'
```

## Deploy

Merging to `main` with a change under this directory runs
[.github/workflows/upwork-scout.yml](../../.github/workflows/upwork-scout.yml). CI builds the image,
ships the compose file, `agent_config.yaml` and `prompts/` to `/app/upwork-scout`, and runs `up -d`. To
redeploy without a commit, run the workflow manually (Actions → upwork-scout → Run workflow).

One-time VM setup, done by the operator ([runbook](../../kb/runbooks/new-agent-vm-setup.md)):

```bash
mkdir -p /app/upwork-scout && cd /app/upwork-scout
mkdir -p claude-config telegram-session backups && chown 10001:10001 claude-config telegram-session
# create .env.upwork-scout and .env.upwork-scout-db from the templates (same POSTGRES_PASSWORD), chmod 600
```

Before Telegram is switched on (after the first deploy has shipped the compose file):

```bash
docker compose run --rm -it agent python -m agent.telegram_login   # once, interactive, as the AGENT account
# add the agent account to the private group, put the group id in settings.telegram.chat_id,
# then set agent.allow_writes: true and merge
```

**CI's post-deploy check passes if any container runs**, so after a deploy confirm all three:

```bash
docker compose ps                                   # agent, db (healthy), backup
journalctl CONTAINER_TAG=upwork-scout --since '1 hour ago' | grep -E 'cycle summary|AGENT ALERT'
```

Restore: `docker compose exec -T db pg_restore -U upwork_scout -d <scratch_db> < backups/<file>.dump`.
**Never `docker compose down -v`**: it deletes the corpus.

## Known gaps

- Backups live on the VM's own disk. Losing the VM loses the corpus and its backups (accepted).
- An outage longer than `maxAgeMinutes` permanently misses the jobs published during it.
- Offers accumulate while `allow_writes` is false. Turning it on posts the backlog, up to
  `max_offers_per_cycle` per cycle. To start clean, mark old `pending` rows `skipped_stale` first.
- At about 140 offers a day, the group is busy. Turning screening back on, or tightening the
  prefilters, is the lever.
- Unknown until the 24 h observation: whether `contentHash` changes on applicant-count updates,
  which would keep each run near 10 results.
- Personal-data columns (`contact_*`, `extracted_*`, `social_profiles`) are stored without a
  retention policy. They are never sent to Telegram or into prompts.
- US-only posts reach the screener: the logged-out actor returns 4–9% more jobs than the
  operator's feed, mostly posts restricted to US freelancers, and its record has no field for the
  restriction. The screener drops them only when the description says so.
- Search volumes were measured on one day; re-check them in `scrape_runs` after 1–2 weeks.
- There are no screener or writer evals yet (Phase 3).
- The poll handles one writer run at a time, so it pauses while a draft is being written.
