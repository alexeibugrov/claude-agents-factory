# Plan: Upwork job scout agent (`upwork-scout`)

- **Date:** 2026-10-22
- **Scope:** Critical
- **Status:** Approved 2026-10-22; Phases 1–2 done, Phase 3 (local validation) next. Operator decisions are recorded in §8.
  Content placeholders (criteria, profile, Telegram target) are deliberate.

## 1. Summary

A new self-contained agent under `agents/upwork-scout/` runs a cycle every 30
minutes. Each cycle starts a run of the Apify actor `blackfalcondata/upwork-scraper`, then
deduplicates the postings in code on `jobId` against a Postgres unique constraint and stores every
record in full. Only postings seen for the first time go to **Agent 1**, which screens them against
criteria written in the prompt. Postings Agent 1 marks suitable go to **Agent 2**, which drafts a
proposal. Deterministic code then posts the job link and the draft to Telegram from the operator's
**user account** (MTProto, Telethon), not a bot.

The storage is built as a market-data corpus from day one: the full raw record, typed columns, a
version history, and full-text indexes. Analysing it later needs no migration.

The biggest risk is **cost and volume running away unnoticed**. That covers two things: an Apify
bill that grows with results per run, and a first-run or state-loss flood of "new" postings that
fans out into hundreds of model calls on the owner's shared subscription. Hard per-cycle caps in
config and incremental mode as a cost lever both address it (§6 D2, D7). The second risk is the
operational load of a stateful database on a shared VM that today has no backups (§6 D9).

## 2. Goal and non-goals

**Goals**

1. Scrape recent Upwork postings every 30 min through Apify. The scope is set by actor input held
   in `agent_config.yaml`.
2. Deduplicate in code before any model call. **No posting ever reaches an agent twice.**
3. Persist every scraped record (full raw JSON, typed columns, change history) in a database whose
   shape supports later time-based keyword and description analysis.
4. Agent 1 screens each new posting against configurable criteria. The verdict, score and reasons
   are stored.
5. Agent 2 drafts a proposal for each suitable posting, and the draft is stored.
6. Deliver the job link, key facts and the draft to a Telegram chat, sent from a Telegram user
   account.
7. Run and test locally first. Then deploy as a Docker Compose stack in `/app/<name>` on
   `157.90.18.149` through the shared pipeline.

**Non-goals**

- Market-demand analytics: dashboards, trend queries, embeddings. Only the storage that enables
  them is in scope (§18).
- Submitting proposals to Upwork. The agent drafts; the human sends.
- The actor's built-in Telegram or Slack notifications. The agent sends its own alert.
- Changes to the shared reusable workflow (a gap is noted in §14 R8 and §18).
  *Amended 2026-10-23:* the operator sanctioned one change, an optional "Upload prompts" step
  (see notes.md, "Writer prompt and local run"). The pre-commit review also re-pinned its
  actions to their latest majors.

## 3. Current state

- **The factory has no real agents yet.** `agents/` holds only `_template/` (`ls agents`). The one
  earlier agent plan, `kb/tasks/002-tg-job-autoapply-2026-08-24/plan.md`, was never implemented. It
  is still the closest precedent for an LLM job-classifier in this repo, and this plan mirrors its
  decisions where they apply (§5).
- **The template is single-prompt, single-role, and stateless.** `AgentConfig` requires one
  top-level `system_prompt` (`agents/_template/agent/config.py:29-72`). `run_once` does one
  `query()` per request with `tools=[]`, `setting_sources=[]`, `permission_mode="dontAsk"` and a
  `PreToolUse` write gate (`agents/_template/agent/loop.py:58-78`). The trigger is a placeholder
  `iter_requests()` (`agents/_template/agent/main.py:33-35`). The compose stack has one `agent`
  service, journald logging, the config bind-mounted read-only, `cap_drop: ALL`, and `mem_limit`
  (`agents/_template/deploy/docker-compose.yaml:4-36`). There is no persistence anywhere in the
  template.
- **Conventions that constrain this design.** The prompt lives in `agent_config.yaml` "and nowhere
  else" (`kb/conventions/agents.md:28-29`). Every state-changing tool goes in `WRITE_TOOLS`, and
  `allow_writes` starts false (`kb/conventions/agents.md:37-38`). Behaviour is fixed with prompts
  and evals, never hardcoded guardrails; the exception is a config-gated, categorical, logged veto
  (`kb/patterns/prompts-and-evals.md:12-28`). Deduplicate before anything expensive and claim the
  key atomically (`kb/patterns/lessons.md:42-47`).
- **CI.** The single reusable pipeline builds `agents/<name>/` and ships `deploy/docker-compose.yaml`
  and `agent_config.yaml` to `/app/<name>`. It runs `docker compose pull && up -d && docker image
  prune -f` (`.github/workflows/agent-deploy.reusable.yml:165-185`). It then passes if **any**
  container in the stack is running (`:187-193`). That is a blind spot for a multi-service stack
  (§14 R8). A one-shot cron-style container would *fail* that check, which matters for D1.
- **The VM** (MCP `ssh_execute pulse`) has 58 GB free on `/`, 7.7 GB RAM with about 6.5 GB
  available, and 4 vCPU. Journald is persistent. It already runs `cloud-scraper` and three `bb-*`
  agents. An earlier stack, `/app/pulse-ai`, ran `pgvector/pgvector:pg16` on a named `dbdata`
  volume (`/app/pulse-ai/docker-compose.yaml:8,19`), so the operator has run Postgres on this VM
  before. **No backup cron exists** (`crontab -l` is empty; `/etc/cron.d` holds only certbot,
  e2scrub, sysstat). The VM reaches `api.apify.com` (HTTP 200) and `api.telegram.org` (HTTP 302).
- **Devcontainer egress.** `apify.com` and `api.apify.com` are **blocked**. DNS resolves, TCP
  connect fails (`curl` exit 7), and WebFetch returns nothing. They are absent from the resolve
  list in `.devcontainer/init-firewall.sh:77-89`. `api.telegram.org` (149.154.166.110) is
  **reachable** (HTTP 302), because it falls inside the pinned `149.154.160.0/20` range
  (`init-firewall.sh:126-144`).
- **There is no Docker and no Postgres in the devcontainer** (`docker`, `psql` and `pg_ctl` are all
  missing; the base is `node:20` on Debian 12, `.devcontainer/Dockerfile:1,53-70`). The factory's
  `docker build` gate has been run on the operator's host
  (`kb/tasks/001-agents-factory-setup-2026-08-24/report.md:45-49`).
- **Actor facts.** These come from the actor README, which the operator pasted and the coordinator
  relayed on 2026-10-22. Claude could not read the page itself, because of the firewall.
  - Input: `query` (string or array, with batched queries sharing one run-start charge),
    `searchUrl`, `jobType`, `experienceLevel`, `category`, `location`/`excludeLocations`, `budget`,
    `hourlyRate`, `maxResults`, `compact`, `descriptionMaxLength` (0 means full), client filters,
    `incrementalMode` + `stateKey` (with `emitUnchanged`, `emitExpired`, `skipReposts`), and a
    detail-enrichment toggle (off by default).
  - Output (standard mode, every field present, null when unknown): `jobId`, `title`,
    `description`/`descriptionMarkdown`/`descriptionHtml`, `contentHash`, `jobType`,
    `experienceLevel`, the budget and hourly fields, the `engagement*` fields, `skills`,
    `skillsDetailed`, `publishTime`, `createTime`, `totalApplicants`, `personsToHire`, the
    `client*` fields, `url`/`portalUrl`, `scrapedAt`, `source`, `isRepost`. In incremental mode
    records also carry `changeType` (`NEW|UPDATED|UNCHANGED|REAPPEARED|EXPIRED`), `repostOfId`, and
    `repostDetectedAt`.
  - Pricing: pay-per-event, **$0.001 per run start plus $0.001 per result**.
  - Triggering: either the API or Python client (start a run, wait, read the dataset), or Apify
    schedules plus a webhook.
  - A public web search turned up a **conflicting** price ("$1.00/1000" in one listing, "$0.003 per
    job" in another), plus a note that Apify is retiring rental pricing. The README figure is used
    below. It must be confirmed against the first real run's charge (Phase 1).

## 4. Evidence map

| Source | What it tells us |
|---|---|
| `kb/architecture/overview.md:26-39` | Self-contained agents; config shipped, not baked; one pipeline |
| `kb/architecture/agent-anatomy.md:19-30,31-42` | Stateless one-`query()` runs; `tools=[]`, `setting_sources=[]`, `dontAsk` |
| `kb/architecture/agent-anatomy.md:44-48,50-63,65-69` | Tools never raise; the write gate; startup refusals |
| `kb/conventions/agents.md:7-15,17-29,31-40,42-60` | Structure, config/secret rules, behaviour rules, image and dependency rules |
| `kb/patterns/prompts-and-evals.md:12-28,29-37,39-54` | Sanctioned-veto bar; prompts in git; eval shape (mock backend, data scenarios, grade end state, real loop) |
| `kb/patterns/tool-design.md:7-13,37-41` | Expose the operation as a unit; keep reads and writes distinct |
| `kb/patterns/lessons.md:15-17,19-21,27-28,42-47` | Silence is not success; retry only what placed no write; a green deploy is not a running agent; dedupe before spend |
| `kb/architecture/auth.md:27-30,33-34` | Subscription rate limits shared with the operator; `env -u CLAUDECODE` for local runs |
| `kb/architecture/cicd.md:47-51,58-62` | `vm-deploy` concurrency group; CI never touches the env file or the DB |
| `kb/runbooks/new-agent-vm-setup.md:23-61` | Operator-provisioned dir, `claude-config` chown 10001, env file, verify |
| `agents/_template/agent/config.py:29-72` | Single `system_prompt` required; must be extended for two roles |
| `agents/_template/agent/loop.py:58-133` | `run_once` contract; never raises; `AGENT ALERT` marker |
| `agents/_template/agent/tools.py:28,50-68` | `TOOL_SPECS` + never-raise wrapper + `build_server(ctx)` |
| `agents/_template/agent/guards.py:23,31-55` | `WRITE_TOOLS` and the gate |
| `agents/_template/deploy/docker-compose.yaml:4-36` | Single-service posture to replicate for `db` and `backup` |
| `.github/workflows/agent-deploy.reusable.yml:165-193` | Ships compose and config; `pull/up/prune`; "any container running" check |
| `.devcontainer/init-firewall.sh:77-89,126-144` | Resolve list lacks Apify; Telegram CIDRs already cover `api.telegram.org` |
| `.devcontainer/Dockerfile:1,53-70` | Debian 12 base; no Postgres or Docker in the apt list |
| `.claude/skills/new-agent/SKILL.md:30-37,62-68` | Scaffold commands; pre-deploy verify gate |
| `kb/tasks/002-tg-job-autoapply-2026-08-24/plan.md:206-284` | Precedent: criteria in the prompt, not regexes; tool surface; eval-first ordering |
| `kb/tasks/001-agents-factory-setup-2026-08-24/report.md:45-49` | `docker build` is verified on the operator's host |
| `curl https://api.apify.com/...` (devcontainer) | exit 7: blocked by the firewall |
| `curl https://api.telegram.org/` (devcontainer) | 302: reachable |
| `dig +short A api.apify.com` | Resolves (2 A records today): safe to add to the resolve list |
| `which docker psql pg_ctl` | None present in the devcontainer |
| MCP `ssh_execute pulse: ls /app; docker ps; df; free; nproc` | Existing stacks, capacity, persistent journald |
| MCP `ssh_execute pulse: grep image /app/pulse-ai/docker-compose*.yml; curl apify/telegram; crontab -l` | Prior pg16 use; VM egress OK; no backups |
| Actor README (operator-pasted, relayed 2026-10-22) | Input params, output fields, PPE pricing, triggering |
| WebSearch "blackfalcondata upwork-scraper apify" | Conflicting price listings; incremental mode; API + MCP access |

## 5. Patterns to mirror

| Category | Source | Pattern |
|---|---|---|
| Agent skeleton | `agents/_template/` | Copy via `.claude/skills/new-agent/SKILL.md:30-37`; package stays `agent` |
| Config load | `agents/_template/agent/config.py:39-72` | Fail-fast loader; extend with per-role blocks, keep the error style |
| Tool surface | `agents/_template/agent/tools.py:28,50-68` | `TOOL_SPECS` tuples, never-raise `_wrap`, `build_server(ctx)` |
| Write gate | `agents/_template/agent/guards.py:31-55` | Config-gated, logged veto; reused for the delivery side effect (D6) |
| Loop | `agents/_template/agent/loop.py:58-133` | One `query()` per job per role; `AGENT ALERT` on non-`COMPLETED` |
| Startup refusals | `agents/_template/agent/main.py:46-53` | Keep as is; add `APIFY_TOKEN`/`DATABASE_URL` presence checks in the same style |
| Compose posture | `agents/_template/deploy/docker-compose.yaml:14-30` | journald tag, `no-new-privileges`, `cap_drop`, `mem_limit`, for every service |
| Named DB volume on this VM | `/app/pulse-ai/docker-compose.yaml:19,98` (VM) | Postgres data on a named volume |
| Criteria in the prompt | `kb/tasks/002-.../plan.md:206-250` (D3) | Judgement lives in the prompt; vetoes only if categorical and config-gated |
| Eval suite | `kb/patterns/prompts-and-evals.md:39-54` | YAML scenarios, real `run_once`, grade end state; dev and held-out split |
| Dedup | `kb/patterns/lessons.md:42-47` | Atomic claim of the key before any model call |

There is no in-repo precedent for a database inside an agent stack, a multi-service compose file,
or a two-role agent. Those are new shapes, introduced here deliberately (D4, D8).

## 6. Architecture and trade-offs

### End-to-end flow

```text
agent container (one long-lived process; agent/main.py)
  every settings.schedule.interval_minutes (no overlap):
   ┌───────────────────────────────────────────────────────────────────────────┐
   │ 1 SCRAPE    apify-client: actor.call(run_input from config) → dataset items │  scrape_runs row
   │ 2 INGEST    per record, one txn:                                           │
   │             INSERT jobs ON CONFLICT (job_id) DO NOTHING RETURNING          │  ← DEDUP (D3)
   │               new → job_versions + pipeline(status=pending|skipped_*)      │
   │               known → job_versions(ON CONFLICT DO NOTHING) + refresh latest│  never re-queued
   │ 3 PREFILTER pending → optional config thresholds → prefiltered | screen    │  (D7)
   │ 4 SCREEN    claim ≤ N pending (FOR UPDATE SKIP LOCKED) → Agent 1 run_once  │  screenings row
   │             → submit_screening(suitable, score, reasons)                   │
   │ 5 DRAFT     suitable → Agent 2 run_once → submit_proposal(text)            │  proposals row
   │ 6 DELIVER   drafted & undelivered → Telethon send_message (user account)    │  gated by allow_writes
   └───────────────────────────────────────────────────────────────────────────┘
        │ asyncpg/psycopg over the compose network
        ▼
  db (postgres:16)  ── named volume ──  backup sidecar (nightly pg_dump → ./backups)
```

### D1. Trigger: in-process scheduler that starts the actor (chosen)

| Option | For | Against |
|---|---|---|
| **A. In-process loop: the agent starts the actor run, waits, reads the dataset** (chosen) | One failure domain; cadence in `agent_config.yaml` (config-only redeploy); no inbound port; the long-lived container satisfies CI's running check (`agent-deploy.reusable.yml:187-193`) | The process carries the timer, so a crash loop also stops scraping (visible in journald) |
| B. Apify schedule + webhook to the VM | Scraping continues if the agent is down | Needs an inbound HTTPS endpoint on the VM (via `nginx-lb`), webhook auth, and two schedules to keep in sync; cadence lives outside git |
| C. Apify schedule; agent polls `runs/last/dataset` | No inbound port | Two clocks; races (reading a run still in progress); missed runs if the agent is down longer than the interval |
| D. Host cron + `docker compose run` | Simple | Fails CI's running check; cron lives outside git; not how the template is shaped |

Mechanics: fixed-rate ticks from process start. A cycle that overruns starts the next one
immediately, and **never concurrently**. On SIGTERM the process finishes the current job, then
exits; `stop_grace_period` in compose gives it time to do so. `--once` (or `RUN_ONCE=1`) runs a
single cycle and exits, for local runs and evals.

### D2. Apify usage: incremental mode as a cost lever only

- **Standard mode with full descriptions** (`compact: false`, `descriptionMaxLength: 0`). Compact
  mode drops fields the analysis corpus wants. The detail-enrichment toggle stays **off** at first;
  its fields and price are unknown (§18).
- **Several search queries, one Apify call each (decided).** `settings.apify.searches` is a list
  of `{name, run_input}` entries, with `name` a stable slug. Shared defaults (`maxResults`, `sort`,
  `compact`, `descriptionMaxLength`, `incrementalMode`) live once in
  `settings.apify.defaults_input` and are merged under each entry. The cycle loops through the
  searches **sequentially**, one actor run per search, each with its own `scrape_runs` row. A
  failed search is logged and skipped; the others still run, and ingest still happens. The actor's
  batched `query` array is deliberately not used: separate runs keep per-search cost, volume and
  failure visible, and give each search its own incremental state. The list starts with **one
  placeholder entry** (`TODO(operator)`) until the operator supplies the queries.
- **`incrementalMode: true`, with `stateKey` derived per search** as `upwork-scout-<name>`, so
  renaming a search deliberately resets its state. This cuts results, and so cost,
  to NEW, UPDATED and REAPPEARED records. **It is never trusted for dedup** (D3). If Apify loses
  the state, every record comes back as NEW; the DB constraint absorbs that, and `maxResults` caps
  the cost spike.
- **`skipReposts: false`.** Reposts are a demand signal the corpus should keep. Whether they reach
  the agents is decided in code (D3).
- `emitExpired` stays off by default. It would give job-lifetime data for later analysis at
  $0.001 per record (§18).
- **Cost model** (README pricing): monthly cost **per search** = 30 × 48 × ($0.001 + $0.001 × R),
  with R results per run. **Total = that × the number of searches**, because every search pays
  its own run-start charge.

  | R (results/run) | per day | per month |
  |---|---|---|
  | 10 | $0.53 | ~$16 |
  | 25 | $1.25 | ~$37 |
  | 50 | $2.45 | ~$73 |
  | 100 | $4.85 | ~$145 |
  | 200 | $9.65 | ~$289 |

  **Decided (Q5): `maxResults: 10`, `sort: recency`, every 30 min, $20/month limit.** One search
  has a ceiling of 1440 runs × $0.011 = **$15.84/month**. **The ceiling grows with each search**,
  but incremental mode only bills records it actually emits:

  | Searches | Ceiling (R = 10 every run) | Realistic (R ≈ 3 new per run) |
  |---|---|---|
  | 1 | $15.84 | ~$5.76 |
  | 2 | $31.68 | ~$11.52 |
  | 3 | $47.52 | ~$17.28 |

  With two or more searches, the $20 limit holds only while real volume stays well below the
  `maxResults` cap. The operator decides between lowering `maxResults` per search, lengthening the
  interval, or relying on the observed R (§8 Q11). Real R comes from `scrape_runs.items_total`
  after Phase 1 and the 24 h observation. The Phase 1 sample run confirms the real charge.
- **Overflow (verified in Phase 1, see `notes.md`):** incremental state records only *emitted*
  jobs, so a surplus beyond `maxResults` arrives in the next run and is not lost. The flip side: an
  unbounded search walks backwards through its ~500-job window at 10 per run. So
  `defaults_input` sets the actor's **`maxAgeMinutes: 120`**, and `max_age_hours_to_screen` stays
  as the in-code backstop. **Why 120 and not 30:** the window is a recovery margin, not the
  cadence. Incremental state means jobs already emitted are never re-billed, so a wider window
  costs nothing in steady state. A 30-minute window would permanently lose every job published
  during any late or missed cycle: a failed run, a deploy restart, VM downtime, or Upwork's
  indexing lag after `publishTime`. 120 tolerates roughly three missed cycles (§14 R15). Measured volume for the first search: ~1.4 new jobs per run, about
  $3.50/month.
- Client: `apify-client` 3.x (pinned exactly). Call `actor(id).call(run_input=…,
  max_items=maxResults, max_total_charge_usd=<small cap>, memory_mbytes=≤1024,
  run_timeout=timedelta(…))`, then `dataset(id).iterate_items()`. Results are pydantic models
  (`model_dump(by_alias=True)`). `scrape_runs.apify_cost_usd` = `chargedEventCounts` ×
  `pricingInfo.pricingPerEvent`, **not** `usageTotalUsd`, which under-reports. The token is
  `APIFY_TOKEN` from the env file.

### D3. Dedup: key `jobId`, enforced by the database, before any agent call

- **Key:** the actor's `jobId`, stored as `jobs.job_id TEXT PRIMARY KEY`. It is the stable Upwork
  identifier and also appears in `url` (`/jobs/~02<jobId>`). A record with a null `jobId` is
  counted as `items_invalid`, logged with an `AGENT ALERT`, and skipped. **No URL-derived
  fallback**: a second key scheme invites silent double-keying.
- **Where:** stage 2 (INGEST), in code, one transaction per record:
  `INSERT INTO jobs … ON CONFLICT (job_id) DO NOTHING RETURNING job_id`. Only when a row is
  returned (first sighting) does ingest insert the `pipeline` row. **Agents only ever read from
  `pipeline`**, so a posting cannot reach an agent unless its first-ever insert succeeded. The
  constraint also collapses duplicates *within* one dataset and across concurrent inserts.
- **Across searches:** the same `jobId` from two searches, in one cycle or different ones, hits
  the same constraint, so it gets one `pipeline` row and one screening. Ingest also upserts
  `job_searches (job_id, search_name)` so the overlap is recorded.
- **Ledger of agent-processed jobs (decided):** `pipeline` is the authoritative record of what the
  agents have handled. Each job has exactly one row, with its status (`unsuitable`, `delivered`,
  `prefiltered`, `skipped_*`, `error`, …), `attempts`, `reason` and `updated_at`; `screenings` and
  `proposals` hold the outputs. Nothing re-queues a job automatically: not a new version, a repost,
  another search, or a prompt change. Re-screening (for example after a criteria change) would be
  an explicit operator action and is out of scope (§18). "Which jobs have the agents processed?" is
  `SELECT … FROM pipeline JOIN screenings …`.
- **Belt and braces:** `screenings` and `proposals` carry `UNIQUE (job_id, prompt_sha)`, so a bug
  in the claim logic cannot double-screen under the same prompt.
- **`changeType` is advisory.** UPDATED, REAPPEARED and UNCHANGED, and NEW for a `jobId` already in
  the DB, all take the "known" path. That path inserts `job_versions (job_id, content_hash)` with
  `ON CONFLICT DO NOTHING`, refreshes the latest columns, `raw`, `last_seen_at` and `seen_count`,
  and **never touches `pipeline`**. This is the version history the market analysis needs
  (applicant counts and budget edits over time) at no extra model cost.
- **Reposts (Q9, decided: skip):** a NEW `jobId` with `isRepost=true` whose `repostOfId` is already in `jobs`
  gets `pipeline.status = skipped_repost` when `settings.pipeline.skip_known_reposts` is true (the
  recommended default). It is still fully stored. A repost of an *unknown* original is treated as
  new. Semantic near-duplicate detection beyond the actor's `repostOfId` is out of scope.
- **Staleness:** a NEW `jobId` whose `publishTime` is older than
  `settings.pipeline.max_age_hours_to_screen` gets `skipped_stale`. This prevents a backfill flood
  on the first run or after state loss. It is categorical and config-driven, and it is cost
  plumbing, not a judgement about the job.

### D4. Database: Postgres 16, recommended (Mongo considered)

| Criterion | Postgres 16 | MongoDB 7 |
|---|---|---|
| Raw record kept verbatim | `JSONB` column; schema drift in the actor needs no migration | Native; the document *is* the record |
| Atomic dedup claim | `PRIMARY KEY` + `ON CONFLICT DO NOTHING RETURNING`: one statement | Unique index + `updateOne(upsert)`; `upsertedId` tells you new vs known. Equivalent |
| Joins (jobs ↔ versions ↔ screenings ↔ proposals) | Native, with FK integrity | `$lookup`; no FK integrity |
| Time-bucketed keyword trends (the hidden goal) | `date_trunc` + `unnest(skills)` + `GROUP BY`; `tsvector` full-text with weights, GIN indexes, `pg_trgm`; plain SQL from any notebook or BI tool | Aggregation pipelines; one text index per collection, weaker ranking; BI needs a connector |
| Future semantic analysis | `pgvector` drop-in (the operator ran `pgvector:pg16` on this VM) | Atlas Vector Search is Atlas-only; self-hosted needs a separate engine |
| Footprint on a shared 7.7 GB VM | Small and tunable (`shared_buffers`) | WiredTiger cache defaults to ~50% of (RAM − 1 GB) unless capped |
| Backups | `pg_dump -Fc`: one file, restore tested with `pg_restore` | `mongodump`: comparable |
| Operator familiarity on this VM | Prior pg16 stack (`/app/pulse-ai`) | None observed |

**Recommendation: Postgres 16**, with the full raw record in `JSONB` plus promoted typed columns.
That keeps Mongo's one real advantage, schemaless raw storage, and adds SQL analytics, full-text
search, FK integrity, and a `pgvector` path. Mongo becomes the better choice only if the operator
expects to keep many heterogeneous scrapers' outputs side by side with no common shape. That is
not the case today.

*Also considered: SQLite.* It needs no extra container and supports `ON CONFLICT` and FTS5. It was
rejected because the hidden goal implies ad-hoc analysis from outside the agent container, while
the agent writes every 30 minutes. A file DB on a bind-mount is awkward to query concurrently and
to back up safely.

### D5. Schema

These are the migrations at `agent/migrations/001_init.sql`, applied at startup by a small runner
under `pg_advisory_lock`, tracked in `schema_migrations`. Plain SQL, with no Alembic (one fewer
dependency). All timestamps are `timestamptz` in UTC.

```sql
-- One row per Apify run: cost and volume audit, and the denominator for "postings per period".
CREATE TABLE scrape_runs (
  id               bigserial PRIMARY KEY,
  started_at       timestamptz NOT NULL DEFAULT now(),
  finished_at      timestamptz,
  status           text NOT NULL,          -- running | succeeded | failed
  search_name      text NOT NULL,          -- settings.apify.searches[].name
  cycle_started_at timestamptz NOT NULL,   -- groups the per-search runs of one cycle
  apify_run_id     text,
  apify_dataset_id text,
  run_input        jsonb NOT NULL,         -- exact input sent (query, filters, stateKey)
  items_total int, items_new int, items_known int, items_invalid int,
  apify_cost_usd   numeric(10,4),          -- from the run object, when exposed
  error            text
);

-- Market data: one row per Upwork job, latest state. Never deleted by the pipeline.
CREATE TABLE jobs (
  job_id                text PRIMARY KEY,  -- actor jobId: THE dedup key
  url                   text NOT NULL,
  title                 text NOT NULL,
  description           text,
  description_markdown  text,
  job_type              text,
  experience_level      text,
  budget_amount         numeric,  budget_currency text,
  hourly_budget_min     numeric,  hourly_budget_max numeric,
  engagement_type       text, engagement_duration text, engagement_duration_weeks int,
  skills                text[] NOT NULL DEFAULT '{}',
  published_at          timestamptz,       -- publishTime
  created_at_upwork     timestamptz,       -- createTime
  total_applicants      int, persons_to_hire int,
  enterprise_job        boolean, premium boolean,
  client_country        text, client_country_code text,
  client_total_spent    numeric, client_spent_currency text,
  client_payment_verified boolean, client_rating numeric, client_review_count int,
  is_repost             boolean, repost_of_id text, repost_detected_at timestamptz,
  custom_job_score      numeric,
  client_has_financial_privacy boolean,
  salary_type           text, salary_min numeric, salary_max numeric, salary_currency text,
  weekly_retainer_budget numeric,
  contact_name          text, contact_email text, contact_phone text,   -- personal data (R17)
  extracted_emails      text[] NOT NULL DEFAULT '{}',
  extracted_phones      text[] NOT NULL DEFAULT '{}',
  extracted_urls        text[] NOT NULL DEFAULT '{}',
  social_profiles       jsonb,             -- {linkedin, github, ...}; mostly null
  actor_first_seen_at   timestamptz,       -- actor-side firstSeenAt (per stateKey)
  actor_last_seen_at    timestamptz,
  sourcing_timestamp    timestamptz,
  scraped_at            timestamptz,       -- latest scrapedAt
  content_hash          text NOT NULL,     -- latest contentHash
  first_seen_at         timestamptz NOT NULL DEFAULT now(),
  last_seen_at          timestamptz NOT NULL DEFAULT now(),
  seen_count            int NOT NULL DEFAULT 1,
  first_run_id          bigint REFERENCES scrape_runs(id),
  raw                   jsonb NOT NULL,    -- latest FULL record, verbatim
  search tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(description, '')), 'B')) STORED
);
CREATE INDEX jobs_published_at ON jobs (published_at);
CREATE INDEX jobs_first_seen_at ON jobs (first_seen_at);
CREATE INDEX jobs_skills_gin ON jobs USING gin (skills);
CREATE INDEX jobs_search_gin ON jobs USING gin (search);

-- Append-only history: every distinct contentHash ever seen for a job.
CREATE TABLE job_versions (
  job_id       text NOT NULL REFERENCES jobs(job_id),
  content_hash text NOT NULL,
  change_type  text,                       -- actor changeType, informational
  seen_at      timestamptz NOT NULL DEFAULT now(),
  run_id       bigint REFERENCES scrape_runs(id),
  total_applicants int,
  raw          jsonb NOT NULL,
  PRIMARY KEY (job_id, content_hash)
);
CREATE INDEX job_versions_seen_at ON job_versions (seen_at);

-- Which searches surfaced which job. A job matched by two searches is still ONE jobs row and
-- is screened once; this only records the overlap, for later per-search demand analysis.
CREATE TABLE job_searches (
  job_id        text NOT NULL REFERENCES jobs(job_id),
  search_name   text NOT NULL,
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  first_run_id  bigint REFERENCES scrape_runs(id),
  PRIMARY KEY (job_id, search_name)
);

-- Operational state, kept apart from market data so analytics never filter around it.
CREATE TABLE pipeline (
  job_id      text PRIMARY KEY REFERENCES jobs(job_id),
  status      text NOT NULL,  -- pending | prefiltered | skipped_repost | skipped_stale | screening
                              -- | unsuitable | suitable | drafting | drafted | delivered | error
  reason      text,           -- prefilter/skip reason, or last error
  attempts    int NOT NULL DEFAULT 0,
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX pipeline_status ON pipeline (status);

CREATE TABLE screenings (
  id bigserial PRIMARY KEY,
  job_id text NOT NULL REFERENCES jobs(job_id),
  created_at timestamptz NOT NULL DEFAULT now(),
  prompt_sha text NOT NULL, model text NOT NULL,
  suitable boolean NOT NULL, score smallint, reasons text,
  run_status text NOT NULL, cost_usd numeric(10,4), num_turns int, duration_s numeric,
  UNIQUE (job_id, prompt_sha)
);

CREATE TABLE proposals (
  id bigserial PRIMARY KEY,
  job_id text NOT NULL REFERENCES jobs(job_id),
  screening_id bigint NOT NULL REFERENCES screenings(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  prompt_sha text NOT NULL, model text NOT NULL,
  body text NOT NULL,
  run_status text NOT NULL, cost_usd numeric(10,4), num_turns int, duration_s numeric,
  telegram_chat_id text, telegram_message_ids bigint[], delivered_at timestamptz,
  UNIQUE (job_id, prompt_sha)
);
```

How this meets acceptance criterion 2:

- The full raw record is kept twice: the latest in `jobs.raw`, and every version in
  `job_versions.raw`.
- Time-based querying is covered by `published_at`, `first_seen_at` and `job_versions.seen_at`,
  each indexed.
- Keyword analysis is covered by `skills text[]` (GIN) and a weighted `tsvector` (GIN).
- `scrape_runs.run_input` records *which slice* was scraped, so a change in the query is not
  mistaken for a change in demand.

`prompt_sha` (sha256 of the role's prompt text) ties every verdict and draft to the exact prompt
that produced it.

### D6. Telegram delivery: deterministic code from a user account, gated by `allow_writes`

- **Decided (Q2): a Telegram user account, not a bot**, configured the way the operator's
  `arbproject-org/bb-trade-agent` `sdk_agent` does it. That is the reference implementation
  (`sdk_agent/orchestrator.py`, `sdk_agent/agent_config.yaml`, `deploy/sdk-agent-compose.yaml`,
  `deploy/sdk-session-setup/`). Transport is MTProto through **Telethon** (pinned exactly).
- **Credentials, mirroring the reference:** `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` in
  `.env.<name>` (never committed, never opened by Claude). The login lives in a **Telethon session
  file**, `upwork_scout.session`, bind-mounted read-write from `/app/<name>/` into the container
  (reference: `./sdk_anon.session:/app/sdk_anon.session`). It is gitignored by the existing
  `*.session` rule, and the operator chowns it to the container uid (10001) because Telethon writes
  to it.
  *Deviation from task 002:* that plan chose a `StringSession` in the env file. This plan follows
  the operator's working pattern instead: one session file per stack, the same account across
  stacks.
- **Target, mirroring the reference:** `settings.telegram.chat_id` (a forum supergroup or
  channel, `-100…`) plus an optional `settings.telegram.topic_id`, which is sent as `reply_to` to
  post into a forum topic, as the reference's `report_forum.chat_id` + `report_topic_id` does. Both
  stay **placeholders** until the operator supplies them; `allow_writes: false` means nothing is
  sent meanwhile. Config validation requires `chat_id` only when `allow_writes` is true.
- **Session creation is an operator step, using the reference's tooling.** Copy
  `deploy/sdk-session-setup/` (`setup.sh` builds a venv; `generate_session.py` reads the stack's
  env file for the API id/hash, logs in interactively with phone + code + 2FA, and writes
  `<session-name>.session` beside it) into `agents/<name>/deploy/session-setup/`, adapted to the
  defaults `--env .env.<name> --session-name upwork_scout`. It is copied, not imported, so the
  agent stays self-contained. The operator runs it on the VM, and separately on their machine for a
  local session. Claude never runs it.
- **One session per place.** A separate session for local runs and for the VM, and none shared
  with the other stacks or the Telegram MCP. Telegram can revoke a session it sees used from two
  IPs at once (`AUTH_KEY_DUPLICATED`).
- **The session file is equivalent to full account access.** It is never logged, copied or
  baked into the image (`.dockerignore` excludes `*.session`). Telethon's logger stays at WARNING.
  See §14 R6.
- **Network:** MTProto goes to Telegram's data-centre IPs. The devcontainer already allows them
  (the static Telegram block in `init-firewall.sh`). The VM's egress is open (A7).
- **Who sends:** the pipeline, **not a model tool**. Every suitable job with a draft is sent, so
  there is no decision for the model to make. A send tool would only add a turn and a way to get
  it wrong (`kb/patterns/tool-design.md:7-13`). The side effect stays gated: `guards.py` gains a
  `delivery_allowed(cfg)` check (the same config flag, logged `WRITE GATE: delivery suppressed
  job=<id>` when it fires) that `pipeline.deliver()` calls before any send. That is the sanctioned
  categorical, config-gated, logged veto (`kb/patterns/prompts-and-evals.md:12-22`), applied to
  code rather than a tool.
- **Connection:** unlike the reference, which listens to channels all day, this agent only
  sends. The client connects once per deliver stage and disconnects afterwards, so a dropped
  connection cannot leave a zombie listener.
- **Format:** Telethon `parse_mode='html'`, everything escaped, link previews off. Message 1 is
  title (linked to `url`), budget or rate, client country, spend, rating and verification,
  applicants, published time, and the Agent 1 score with a one-line reason. Message 2, a reply to
  message 1, is the draft in a `<blockquote>` for easy copying, split if it exceeds 4096
  characters. Whether the pinned Telethon supports the *expandable* blockquote is checked in
  Phase 2; a plain blockquote is the fallback.
- **Idempotency:** at least once. `proposals.delivered_at IS NULL` is the outbox; message ids are
  recorded after success. A crash between send and record re-sends once. That is accepted.
- **Rate:** sends are paced to ≤1 per second; a `FloodWaitError` stops delivery for the cycle and
  leaves the rows undelivered for the next one.

### D7. Prefilters: optional, config-driven, before any LLM call

There are two layers, and they serve different purposes:

1. **Actor input** (`settings.apify.run_input`: `query`/`searchUrl`, `category`, `jobType`,
   `excludeLocations`, …) defines **the market slice that is stored**. Narrowing here also narrows
   the future analysis corpus, so keep it as broad as the operator's niche and budget allow (Q5).
2. **Code prefilters** (`settings.prefilter`): `require_payment_verified`, `min_client_total_spent`,
   `min_client_rating`, `max_total_applicants`, `job_types`, `min_hourly_rate`,
   `min_fixed_budget`, `exclude_client_country_codes`. They run after storage and before Agent 1,
   setting `pipeline.status = prefiltered` and `reason = <rule>`, with one log line per skip.
   **Every threshold defaults to `null` (disabled).** They are cheap, deterministic,
   operator-owned criteria on structured fields, there to save subscription capacity. They are not
   a patch for model behaviour. Anything requiring judgement (tech fit, scope, red flags) stays in
   the Agent 1 prompt.

   **Decided: every filter lives in `agent_config.yaml`, none is hardcoded.** The code only
   implements the rule types; the operator sets and tightens the thresholds. They ship permissive
   (all `null`), in line with the recall-first screening (Q8), and the operator hardens them later
   from real data, with a config-only redeploy. Adding a new *rule type* is a code change with a
   test; changing a threshold never is.

**Volume caps**, in config and categorical: `max_screen_per_cycle` and `max_draft_per_cycle`. The
backlog stays `pending` for the next cycle, with nothing dropped. A subscription rate-limit error
stops the cycle's agent stage early and leaves the jobs `pending` (`kb/architecture/auth.md:27-30`).

### D8. Two roles, one agent package; config and prompt layout

The task text says "prompt files". The factory rule is that **the prompt lives in
`agent_config.yaml` and nowhere else** (`kb/conventions/agents.md:28-29`, motivated by the decorative
`prompts/` directory in `kb/patterns/prompts-and-evals.md:29-37`). This plan follows the rule: both
prompts are YAML block scalars in `agent_config.yaml`. That is a deliberate deviation from the ask.

Shape (key names only; values are decided in implementation):

```yaml
agent:
  allow_writes: false            # gates Telegram delivery (D6)
screener:                        # Agent 1
  model: …  fallback_model: …  max_turns: …  max_budget_usd: …
  system_prompt: |               # role + "## Criteria" section the operator owns (Q3)
writer:                          # Agent 2
  model: …  fallback_model: …  max_turns: …  max_budget_usd: …
  system_prompt: |               # tone, structure, length + "## About me" profile (Q6)
settings:
  schedule:  { interval_minutes }
  apify:     { actor_id, timeout_secs, memory_mbytes,
               defaults_input: { maxResults: 10, sort: recency, compact: false, … },
               searches: [ { name: TODO-operator, run_input: { query: … } } ] }
  pipeline:  { max_screen_per_cycle, max_draft_per_cycle, max_attempts,
               max_age_hours_to_screen, skip_known_reposts }
  prefilter: { …all null by default… }
  telegram:  { chat_id, topic_id, session_path, send_interval_s }   # placeholders; api id/hash in env
  db:        { host, port, name, user }   # password is a secret, in env
```

- `config.py` is extended: `RoleConfig` (model, fallback_model, max_turns, max_budget_usd,
  system_prompt) for `screener` and `writer`, both required. Fail-fast errors keep the template's
  style. The template's top-level `system_prompt` requirement is removed in **this agent only**.
  `agents/_template/` is not changed.
- `loop.run_once(prompt, ctx, role: RoleConfig, allow_writes)` keeps the template's options
  verbatim (`tools=[]`, `setting_sources=[]`, `dontAsk`, the write-gate hook).
- Model defaults: screener on `claude-sonnet-5` (high volume, classification), writer on
  `claude-opus-5` with fallback `claude-sonnet-5`. Model names follow
  `agents/_template/agent_config.yaml:13-14`. The evals decide (Phase 3).
- The **user prompt** (the job) is rendered by code from typed columns plus the full description.
  It is data, not instructions, and the system prompt says to treat job text as untrusted (§14 R7).

### D9. Tool surface and `WRITE_TOOLS`

| Tool | Role | Kind | Behaviour |
|---|---|---|---|
| `submit_screening` | screener | read (pure) | Args `suitable: bool`, `score: 0-100`, `reasons: str` (≤ 600 chars), `matched_criteria: [str]`. Validates, then records the verdict on the run's `RunContext` result holder. Returns `{"success": true}`. |
| `submit_proposal` | writer | read (pure) | Args `proposal: str` (length bounds from config, stated in the schema), `notes_for_operator: str?`. Records it on `RunContext`. |

- Each role's tool server exposes **only its own tool** (`build_server(ctx, role)`). The job
  content arrives in the prompt, so no lookup tool is needed. That means one or two turns per job.
- **Neither tool changes state.** Both write only into the per-run in-memory holder; the
  deterministic pipeline persists the result after `run_once` returns. So
  **`WRITE_TOOLS = set()`**, explicitly, with a comment saying why. The one external side effect
  (Telegram) is gated in code (D6). Consequence: a failed or confused run has written nothing and
  is **safe to retry** (`kb/patterns/lessons.md:19-21`); a job is retried up to `max_attempts`.
- A run that ends without calling its submit tool → `run_status=ERROR`, `AGENT ALERT`, attempt
  counted.
- *Alternative considered:* SDK structured output (`output_format`) instead of a submit tool. This
  is not chosen until verified against the pinned `claude-agent-sdk==0.2.105`
  (`agents/_template/pyproject.toml:7`). The tool path is proven by the template.

### D10. Compose topology on the VM

`deploy/docker-compose.yaml`, project in `/app/<name>`:

| Service | Image | Notes |
|---|---|---|
| `agent` | `ghcr.io/alexeibugrov/<name>:${IMAGE_TAG}` | Template posture unchanged; `depends_on: db: condition: service_healthy`; `stop_grace_period` ≥ one job's runtime; env from `.env.<name>`; extra volume `./upwork_scout.session:/app/upwork_scout.session` (read-write, as in the reference) |
| `db` | `postgres:16` pinned to an exact minor tag | Named volume `pgdata` with an explicit `name:` (survives project renames; `docker image prune` never touches volumes); **no published ports**; `pg_isready` healthcheck; journald tag `<name>-db`; `no-new-privileges`; `cap_drop: ALL` + `cap_add` limited to what the entrypoint needs (CHOWN, SETUID, SETGID, FOWNER, DAC_OVERRIDE; verify locally); `mem_limit` with matching `shared_buffers`; env from a **separate** `.env.<name>-db` holding only `POSTGRES_PASSWORD`, so the DB container never sees the Claude or Apify tokens |
| `backup` | same `postgres:16` tag | Loop: `pg_dump -Fc` nightly to bind-mount `./backups`, retention 14 days, then sleep. It lives in git and is deployed by CI, so there is no host cron. **On-VM only** (Q4, operator decision) |

- Network: the compose default bridge; `db` is reachable only by service name.
- Future analysis access is out of scope: `docker compose exec db psql`, or later a
  `127.0.0.1`-bound port over an SSH tunnel (§18).
- The agent's `DATABASE_URL` is built from `settings.db` plus `POSTGRES_PASSWORD` in the agent's
  env file. So the operator pastes the same password into both env files. That is documented in
  the env templates and the README.

### D11. Local run

- **Unit tests and the DB layer, in the devcontainer:** the devcontainer has no Docker and no
  Postgres. Recommended: add the `postgresql` server package to `.devcontainer/Dockerfile`'s apt
  list. Debian 12 ships 15; prod runs 16, and the SQL used is 15-compatible. Tests then use a
  throwaway cluster via `pytest-postgresql`'s process fixture. This is batched into the same
  rebuild as the firewall change (Q7).
- **Egress:** `apify.com` and `api.apify.com` are **already added** to the resolve list in
  `init-firewall.sh` (uncommitted, both resolve today). Telegram's data-centre ranges are already
  allowed for MTProto. The operator rebuilds the container. **Caveat:** Apify sits behind rotating AWS IPs, and the firewall resolves only at
  container start, so a long-lived container may lose Apify mid-session. A restart re-resolves.
  Also verify in Phase 1 that dataset item downloads do not redirect to a second host; silence
  there would look like "no results" (`CLAUDE.md` § Environment limits).
- **A live local cycle** (`env -u CLAUDECODE uv run python -m agent.main --once`, per
  `kb/architecture/auth.md:33-34`) needs real tokens in the environment. Claude never opens a
  `.env*` file, so **the operator runs this step** with variables exported in their own shell,
  against the local Postgres. Claude can then inspect the DB (`psql`) and the stdout trace.
- **`docker build` and a full compose smoke run** happen on the **operator's host**, where Docker
  exists. Same practice as `kb/tasks/001-.../report.md:45-49`.

### D12. Evals

The shape follows `kb/patterns/prompts-and-evals.md:39-54`.

- **Corpus:** after the first local scrapes, export 50–80 stored jobs (`raw` JSON) into
  `evals/screener/cases.yaml`. The operator labels `suitable: true|false` with a one-line reason
  **against the written criteria (Q3), before any prompt tuning**. Split into dev and held-out
  slices; record a checksum of the labelled file in the task folder.
- **Screener runner** (`evals/run_screener.py`): the real `run_once`, real tool handlers, real
  config, no DB. It grades the end state (`suitable`) and reports precision and recall separately;
  which matters more is Q8. It iterates the **prompt only**, then runs the held-out slice once.
- **Writer suite** (`evals/writer/cases.yaml`, 8–10 suitable jobs): automated end-state checks are
  "a proposal was submitted", "length within the config bounds", and "no unfilled placeholders"
  (`[`, `{`, `<your`). Quality is an **operator review gate** on the drafts. LLM-as-judge is
  deferred: cost on the subscription, and it adds a second prompt to tune.
- Every eval run costs real subscription calls. The suite stays small and is run on prompt
  changes, not per commit.

## 7. Assumptions

- **A1:** The actor README (as relayed) is accurate for field names, `jobId` stability and
  pricing. *It is the only source available behind the firewall.* Phase 1's sample scrape verifies
  it: field presence, `jobId` ↔ `url` consistency, and the charge on the Apify run.
- **A2:** `jobId` is unique and stable per Upwork job across runs and modes. *The README describes
  it as the job identifier, and it is embedded in the canonical URL.*
- **A3:** Volume is moderate: tens to low hundreds of new postings per 30 minutes in the chosen
  slice. *If R stays above 200, the cost table and the per-cycle caps need revisiting.*
- **A4:** One `jobs.raw` + `job_versions.raw` copy per distinct `contentHash` fits comfortably.
  *About 5–10 KB per record × 10k/day is roughly 50–100 MB/day before compression, against 58 GB
  free.* A retention decision is a follow-up (§18).
- **A5:** The Telegram target is a chat the operator owns (a private channel or Saved Messages);
  at-least-once delivery (rare duplicate on crash) is acceptable. Posting a few messages per 30
  minutes to one's own chat is low-risk for a user account (§14 R14).
- **A6:** Pay-per-event pricing includes platform compute (no separate CU billing). *Verified on
  the first run's charge.*
- **A7:** The VM runs no host firewall that blocks the agent's egress. *`curl` from the VM reached
  both APIs.*
- **A8:** English full-text configuration is good enough for the generated `tsvector`. *Upwork
  postings are predominantly English; `raw` keeps everything for re-indexing later.*

## 8. Decisions and open questions

### Decided in review 1 (2026-10-22)

| # | Decision |
|---|---|
| Q1 | Agent name: **`upwork-scout`** |
| Q2 | Telegram delivery from a **user account**, configured like `bb-trade-agent/sdk_agent`: API id/hash in the env file, a bind-mounted per-stack `.session` file made by the copied session-setup scripts (D6). `chat_id`/`topic_id` are **placeholders** until the operator supplies them |
| Q4 | Postgres in the same compose stack; nightly backups **on the VM only**, 14-day retention. No off-VM copy; the operator accepts that losing the VM loses the corpus (§14 R4) |
| Q5 | **Several searches supported in code**, looped sequentially with **one Apify call per search**, each with its own incremental state; `maxResults: 10`, every 30 min. Starts with one placeholder search. Budget limit **$20/month** (D2; see Q11) |
| Q3 | Criteria and queries: **placeholders** (`TODO(operator)`) for now |
| Q9 | **Skip** screening reposts of known jobs (stored, not screened) |
| Q10 | **Postgres 16** |
| — | `pipeline` is the ledger of agent-processed jobs; a job is never re-screened automatically (D3) |
| Q11 | Keep `maxResults: 10` per search, stay under $20/month: config `monthly_budget_usd: 20`, with an `AGENT ALERT` when the month's summed `scrape_runs.apify_cost_usd` crosses 80% |
| — | **Hard limit: never more than 10 jobs per actor run**, including the Phase 1 sample scrape. Config validation rejects `maxResults > 10` |
| — | Searches may be given as an Upwork **`searchUrl`** (the actor parses its filters) instead of `query`. First real search: the operator's AI-agent / workflow-automation URL, recorded in `notes.md` |
| — | Actor id for API calls: `FlbDgNCfA8bOdFQWT` (= `blackfalcondata/upwork-scraper`); run input field names per the operator's snippet in `notes.md` |
| — | Plan **approved** 2026-10-22 |
| Q6 | The repo is **private**: the operator profile goes in the committed `writer.system_prompt` under `## About me` |
| Q7 | Firewall entries are in the script (done); the operator does the rebuild. The `postgresql` package is added to the Dockerfile in Phase 1 |
| Q8 | **Recall first**: catch every good job. Filters ship permissive and are hardened later (D7) |
| — | All prefilters are config-driven, none hardcoded (D7) |

### Still open

No design questions are open. Content still to supply (placeholders in config, not blocking the
build): the `## Criteria` and `## About me` prompt sections, and Telegram `chat_id`/`topic_id`
(needed before the Phase 3 delivery check).

## 9. Target state

- `agents/<name>/` exists, built from `_template/`. It holds the agent package (config, context,
  tools, guards, loop, main, plus `db.py`, `migrations/`, `scrape.py`, `store.py`, `pipeline.py`,
  `telegram.py`), `tests/`, `evals/`, a rewritten `README.md`, `<name>.env.template` and
  `<name>-db.env.template`, a three-service `deploy/docker-compose.yaml`, and the
  `.github/workflows/<name>.yml` caller.
- `agent_config.yaml` holds both role prompts, `allow_writes: false`, and all knobs. It is free of
  secrets.
- On the VM, `/app/<name>` runs `agent`, `db` and `backup`. Every 30 minutes `scrape_runs` gets a
  row, `jobs`/`job_versions` grow, new postings are screened, and suitable ones are drafted.
  Delivery logs `WRITE GATE: delivery suppressed` until the operator flips `allow_writes: true`.
  After that, the channel receives link + facts + draft.
- No `jobId` ever has more than one `pipeline` row, or more than one screening per `prompt_sha`.
- A tested `pg_restore` procedure is documented in the README.

## 10. Implementation steps

### Phase 1. Preparation (harness and data contract)

- [ ] Operator supplies at least one real search query (needed for the sample scrape only).
- [x] `.devcontainer/init-firewall.sh`: `apify.com` and `api.apify.com` added to the resolve list
      with a one-line comment; both resolved before the edit.
- [x] `.devcontainer/Dockerfile`: `postgresql` + `postgresql-client` added to the apt list (Q7).
      Debian's server binaries live in `/usr/lib/postgresql/<ver>/bin`, off `PATH`; the test
      fixture is pointed there in Phase 2.
- [x] Operator rebuilt the container. Verified: Apify API → 200; PostgreSQL 15.19 installed.
- [x] Sample scrape: two runs of the operator's search URL, 10 jobs each, saved as
      `sample-dataset.json` (20 records, $0.022 spent).
- [x] Sample checked: `jobId` non-null and unique, `url` contains `~02<jobId>`, `contentHash`
      present, full descriptions, billing = $0.001 + $0.001×R (A1, A6 hold). Incremental state
      records only emitted jobs (→ `maxAgeMinutes`, D2). Findings in `notes.md`.

### Phase 2. Implementation

- [x] Scaffold per `.claude/skills/new-agent/SKILL.md:30-37` with the Q1 name. The `_template/`
      directory is **not** modified.
- [x] `pyproject.toml`: add `apify-client`, `psycopg[binary]` (v3, async), `telethon`, exact pins;
      dev: `pytest-postgresql`. `uv lock`.
- [x] `agent/config.py`: `RoleConfig` for `screener`/`writer`, typed `settings` access, fail-fast
      validation (both roles required; interval > 0; `telegram.chat` required when `allow_writes`).
- [x] `agent/migrations/001_init.sql` (D5) + `agent/db.py` (pool, advisory-locked migration
      runner, `schema_migrations`).
- [x] `agent/scrape.py`: loop over `settings.apify.searches`, one actor call per search (defaults
      merged, `stateKey` derived from the name), a `scrape_runs` row per search, item iteration,
      record → typed-column mapping. Failures return a result; they never raise into
      the cycle.
- [x] `agent/store.py`: `ingest(record, run_id)` implementing D3 exactly; prefilter (D7);
      claim/transition helpers with `FOR UPDATE SKIP LOCKED`; startup reset of `screening`/
      `drafting` → `pending`/`suitable` (safe, because the tools are pure).
- [x] `agent/context.py`: `RunContext(run_id, job_id, role, result_holder)`.
- [x] `agent/tools.py`: `submit_screening`, `submit_proposal` (D9), `build_server(ctx, role)`.
- [x] `agent/guards.py`: `WRITE_TOOLS = set()` with the reason; `delivery_allowed(cfg)` with its
      log line (D6).
- [x] `agent/loop.py`: `run_once(prompt, ctx, role, allow_writes)`; template options unchanged.
- [x] `agent/telegram.py`: Telethon client on the session file at `settings.telegram.session_path`,
      connect → `send_job(job, screening, proposal)` (with `reply_to=topic_id` when set) →
      disconnect, per D6; Telethon logger pinned to WARNING.
- [x] `deploy/session-setup/` (`setup.sh`, `generate_session.py`, `requirements.txt`): copied from
      `bb-trade-agent/deploy/sdk-session-setup/`, defaults changed to `.env.<name>` and
      `upwork_scout`. Run only by the operator.
- [x] `.dockerignore`: exclude `*.session` and `deploy/session-setup/`.
- [x] `agent/pipeline.py`: `cycle()` = scrape → ingest → prefilter → screen (cap) → draft (cap) →
      deliver (gated). It stops the agent stages on a rate limit, and logs one summary line per
      cycle (`cycle summary: fetched=… new=… prefiltered=… screened=… suitable=… drafted=…
      delivered=… suppressed=…`).
- [x] `agent/main.py`: the template's startup refusals kept verbatim, plus `APIFY_TOKEN` and
      `DATABASE_URL`/`POSTGRES_PASSWORD` presence checks, `TELEGRAM_API_ID`/`TELEGRAM_API_HASH` and
      a readable session file when `allow_writes`; migrations; scheduler (D1); `--once`; SIGTERM
      handling.
- [x] `agent_config.yaml`: D8 shape. Placeholder `## Criteria` and `## About me` sections marked
      `TODO(operator)` until the operator writes them.
- [x] `<name>.env.template` (`CLAUDE_CODE_OAUTH_TOKEN`, commented `ANTHROPIC_API_KEY` warning,
      `APIFY_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `POSTGRES_PASSWORD`) and
      `<name>-db.env.template`
      (`POSTGRES_PASSWORD`). Names only.
- [x] `deploy/docker-compose.yaml`: D10.
- [x] `tests/`: keep the template's config and guard tests, adapted. Add tests for ingest dedup (same
      `jobId` twice in one batch; NEW-flagged known id; UPDATED creates a version but no pipeline
      row; the same `jobId` from two searches → one pipeline row, two `job_searches` rows; one
      search failing does not stop the others), repost and stale skips, prefilters with null thresholds (no-op), claim concurrency
      (two claimers, disjoint sets), delivery suppressed when `allow_writes` is false, HTML
      escaping and the 4096 split, and the tool handlers rejecting out-of-range args without
      raising.
- [x] `README.md`: rewritten (purpose, flow diagram, config, schema summary, cost model, runbook
      for restore and token rotation, known gaps).
- [x] `.github/workflows/<name>.yml` from the template caller.

### Phase 3. Validation (local)

- [ ] `cd agents/<name> && uv sync && uv run pytest -q`; `ruff check . && ruff format --check .`.
- [ ] Operator (own shell, tokens exported): `env -u CLAUDECODE uv run python -m agent.main --once`
      against the local Postgres, `allow_writes: false`. Claude inspects tables and the trace.
      Run it a second time and confirm **zero** new pipeline rows for already-seen ids.
- [ ] Build the screener corpus from stored jobs → operator labels (Q3, Q8) → checksum → dev and
      held-out split → iterate the prompt on dev → one held-out run. Report both numbers.
- [ ] Writer suite + operator review of the drafts.
- [ ] Operator: create a **local** session with `deploy/session-setup/`, then run a one-off
      local cycle with `allow_writes: true` against the real chat (Q2). Confirm format, link and
      the split.
- [ ] Operator host: `docker build -t <name>:local .`, then `docker compose up` with a local
      override (image `<name>:local`), to confirm `db` comes up under the cap set and the backup
      sidecar writes a dump; then `pg_restore` that dump into a scratch DB.
- [ ] `/task-review` over the full diff; resolve block-tier findings; human review gate; present
      the PR title and body and wait for approval before `gh pr create`.

### Phase 4. Rollout

- [ ] Operator VM prep per `kb/runbooks/new-agent-vm-setup.md:23-61`: `/app/<name>/claude-config`
      chowned 10001; `/app/<name>/backups`; both env files (Claude supplies the exact lines and
      opens neither); then the operator runs `deploy/session-setup/` **on the VM** to create
      `/app/<name>/upwork_scout.session` (a separate session from the local one) and chowns it to
      10001 (D6).
- [ ] Merge → watch the caller run → verify the image pushed and the deploy step is green.
- [ ] **Because CI's check passes on any running container (§14 R8):** confirm over SSH MCP that
      `docker compose ps` shows **all three** services running and `db` healthy, and that
      `journalctl CONTAINER_TAG=<name>` shows `agent starting`, migrations applied, and a first
      `cycle summary`.
- [ ] Observe at least 24 h with `allow_writes: false`: cycle cadence, `items_new` vs R, Apify spend
      on the account, screened/suitable ratio, and that there are no `AGENT ALERT` lines.
- [ ] On the operator's word: flip `allow_writes: true` (a config-only redeploy); confirm the first
      deliveries.
- [ ] Confirm the first nightly backup file exists in `/app/<name>/backups`.

## 11. Dependencies and sequencing

- Q7 → firewall/Dockerfile edit → rebuild → sample scrape → schema check. **Nothing else in
  Phase 2 that touches `scrape.py`'s mapping should be finalised before the sample is checked.**
- Q10 gates the migration and driver choice. Q1 gates the scaffold.
- Q3 gates eval labelling; labelling precedes any prompt tuning.
- `config.py`, `db.py` and the migration can be written in parallel with `telegram.py` and
  `tools.py`. `pipeline.py` and `main.py` come last.
- The CI caller merges only after local validation, because merging deploys.
- `vm-deploy` serialisation (`kb/architecture/cicd.md:47-51`) means the first deploy queues behind
  any concurrent agent deploy. Expected.

## 12. Validation

| Check | Command | Expected |
|---|---|---|
| Apify egress (devcontainer) | `curl -sS -o /dev/null -w '%{http_code}' https://api.apify.com/v2/acts/blackfalcondata~upwork-scraper` | `200` |
| Unit tests | `uv run pytest -q` | Green, including the dedup and gate tests |
| Lint | `ruff check . && ruff format --check .` | Clean |
| Dedup end-to-end | Two `--once` cycles, then `SELECT count(*) FROM pipeline` before/after; `SELECT job_id, count(*) FROM screenings GROUP BY 1 HAVING count(*)>1` | Second cycle adds 0 pipeline rows for known ids; the duplicate query returns 0 rows |
| Raw kept | `SELECT count(*) FROM jobs WHERE raw IS NULL` | 0 |
| Queryable | `SELECT date_trunc('day', published_at), unnest(skills), count(*) … GROUP BY 1,2`; a `search @@ websearch_to_tsquery('…')` query | Returns rows using the GIN indexes (`EXPLAIN`) |
| Gate | Cycle with `allow_writes: false` | `WRITE GATE: delivery suppressed` lines; no Telegram messages |
| Image | `docker build -t <name>:local .` (operator host) | Bundled-CLI and import assertions pass |
| Stack on VM | MCP `ssh_execute pulse: cd /app/<name> && docker compose ps` | `agent`, `db` (healthy), `backup` running |
| Trace | MCP `ssh_execute pulse: journalctl CONTAINER_TAG=<name> --since '1 hour ago'` | `cycle summary` roughly every 30 min; no `AGENT ALERT` |
| Backup | `ls -l /app/<name>/backups` + test `pg_restore --list` | A dump from the last 24 h that lists all tables |

## 13. Rollback

- **Phase 1:** revert the firewall and Dockerfile lines; rebuild.
- **Phase 2/3:** unmerged branch work, so there is nothing to roll back; delete local DB clusters.
- **Phase 4, bad behaviour:** set `allow_writes: false` (a config-only redeploy) to stop Telegram
  at once. Lower `max_screen_per_cycle` to 0 to stop model calls while scraping continues.
- **Phase 4, bad image:** redeploy the previous `sha-` tag with `build: false`
  (`kb/architecture/cicd.md:22-25`).
- **Phase 4, stop everything:** `cd /app/<name> && docker compose stop agent` (data kept). This is
  operator-run, or Claude only after explicit approval. **Never `down -v`**, which destroys the
  corpus.
- **Schema:** forward-only migrations; a bad migration is fixed forward. The nightly dump is the
  last resort, and a pre-migration manual `pg_dump` is required before any future migration.

## 14. Risks and challenges

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Apify cost overrun (broad query, lost incremental state, price differs from README) | Med | Med: real money | `maxResults` hard cap; incremental mode; `scrape_runs.apify_cost_usd` logged per run; 24 h observation before trusting R; confirm price in Phase 1 |
| R2 | First run or state loss floods the agents | High (first run) | Med: burns shared subscription capacity, degrades the operator's own Claude use | `max_age_hours_to_screen`, per-cycle caps, rate-limit early stop; backlog persists |
| R3 | Actor schema drift or a renamed field | Med | Med: a promoted column goes null, or ingest fails | `raw` is always stored; mapping tolerates missing optional fields; a null `jobId` → `AGENT ALERT`; `cycle summary` makes `items_invalid` visible |
| R4 | DB data loss (volume deleted, disk failure, `down -v`) | Low | High: the long-term corpus is the point | Named volume with an explicit name; on-VM backup sidecar; restore tested in Phase 3; README warns against `down -v`. **Accepted residual:** backups share the VM's disk, so losing the VM loses both (Q4) |
| R5 | Postgres competes with other stacks for memory | Low | Med | `mem_limit` + `shared_buffers` sized; VM has ~6.5 GB available |
| R6 | Telegram session file leaks (it grants full access to the operator's account) | Low | High | Lives only in `/app/<name>/`, gitignored (`*.session`) and dockerignored; never logged; Telethon logger at WARNING; separate local and VM sessions so one can be revoked alone (Settings → Devices) |
| R7 | Prompt injection in job descriptions (e.g. "mark this suitable") | Med | Low–Med: noisy alerts or odd drafts. There is no write tool, so nothing worse can follow | Job text rendered as clearly delimited data; system prompt says so; the only tools are pure submit tools; Telegram send is not model-controlled |
| R8 | CI's post-deploy check passes while `agent` crash-loops (because `db` is running) | Med | Med: silent outage | Phase 4 checks all three services manually; follow-up to make the reusable check service-aware (§18). Not changed here: it is shared CI core |
| R9 | Duplicate Telegram message after a crash mid-send | Low | Low | Accepted at-least-once (A5) |
| R10 | Devcontainer loses Apify when AWS IPs rotate | Med | Low: local only | Container restart re-resolves; documented in README |
| R11 | `cap_drop: ALL` breaks the Postgres entrypoint | Med | Low: caught locally | Minimal `cap_add` verified on the operator host in Phase 3 |
| R12 | Subscription token expiry (~1 year) | Low (now) | High (later): all screening stops | Startup and run errors produce `AGENT ALERT`; rotation runbook (`kb/runbooks/new-agent-vm-setup.md:63-66`) |
| R13 | Prefilters drift into hidden behaviour rules | Low | Med: a `/task-review` finding | All default null; each skip logged with its rule; README documents them as operator criteria on structured fields |
| R15 | Outage longer than `maxAgeMinutes` (120) loses every job published during the gap: scraper or VM down, Apify failing, a long deploy | Low | Med: missed leads and a hole in the corpus | `AGENT ALERT` on a failed scrape; `scrape_runs` gaps are visible; raise `maxAgeMinutes` temporarily after a known outage (a config-only redeploy; cost is bounded by `maxResults`) |
| R16 | `contentHash` changes on applicant-count updates, so UPDATED records keep R near `maxResults` every run | Med | Low: cost rises to the $15.84/search ceiling, still under $20 for one search | Measured during the 24 h observation (`scrape_runs.items_known` vs `items_new`); if high, set `emitUnchanged`/tracking options or accept |
| R17 | Stored personal data: `contactName/Email/Phone`, `extracted*`, `socialProfiles` | Low (mostly null in the sample) | Med: privacy obligations (the actor's disclaimer cites GDPR) | Stored only in the private DB on the VM, never sent to Telegram or into prompts; columns documented in the README; retention policy is a follow-up (§18) |
| R18 | Apify `usageTotalUsd` under-reports the charge ($0.001 vs the real $0.011) | Certain | Med: cost tracking and the budget alert would be wrong | Cost computed from `chargedEventCounts` × `pricingPerEvent`; per-run `max_total_charge_usd` cap enforced by Apify |
| R19 | A new `stateKey` (new or renamed search) walks backwards through the job backlog at 10 per run | Med | Low: ~25 h of full-price runs, about $0.50 | `maxAgeMinutes: 120` bounds the window; the README notes that renaming a search resets its state |
| R14 | Telegram restricts or logs out the automated user account, or revokes a session reused from two IPs | Low | Med: alerts stop; the operator's own account is affected | Low volume to the operator's own chat only; `FloodWaitError` honoured; separate sessions per place; send failure → `AGENT ALERT` |

**Blast radius, stated plainly.** In the worst realistic bad run, the agent posts noisy or wrong
drafts into the operator's own private channel and spends Apify credit up to
`maxResults` × 48 per day. It cannot apply on Upwork, cannot message anyone else, and cannot alter
other stacks. Model tools change nothing; the only external write is gated by `allow_writes`.

## 15. Escalation triggers hit

- **Devcontainer firewall and Dockerfile change** (`CLAUDE.md` § Devcontainer): requires
  confirming the domain resolves first, plus an operator rebuild. Q7.
- **New external systems and credentials**: Apify token, Telegram user account (API id, API hash,
  session file), DB password. They are
  operator-provisioned in env files that Claude never opens (`CLAUDE.md` § Secrets).
- **Shared VM gains a stateful service and a host directory with backups** (`/app/<name>/backups`).
  VM prep is operator-applied; any destructive VM action is stop-and-ask (`CLAUDE.md` § MCP
  integrations).
- **The PR and the deploy**: present the PR title and body for explicit approval; merging deploys
  to the VM (`CLAUDE.md` § Git; task-flow post-merge control).
- **Known gap in shared CI** (R8) is noted but deliberately not changed. Changing the reusable
  workflow affects every agent.
- `agents/_template/` is **not** changed by this plan.

## 16. Observability and security impact

- **Logs:** journald tags `<name>` (agent), `<name>-db`, `<name>-backup`. Per-event trace from
  `loop.py` as in the template, plus one `cycle summary` line per cycle and `AGENT ALERT` for:
  failed scrape, `items_invalid > 0`, a run without a submit, max attempts reached, Telegram send
  failure, and backup failure.
- **Metrics in the DB:** `scrape_runs` (volume, cost), `screenings`/`proposals` (`cost_usd`,
  turns, duration) give spend and quality trends with no extra tooling.
- **Secrets:** four new values in `.env.<name>` (`APIFY_TOKEN`, `TELEGRAM_API_ID`,
  `TELEGRAM_API_HASH`, `POSTGRES_PASSWORD`), one in `.env.<name>-db`, and the
  `upwork_scout.session` file. Templates hold names only; gitleaks runs over the diff.
- **Network:** DB unexposed; agent egress to `api.anthropic.com`, `api.apify.com`, and Telegram's
  data-centre IPs (MTProto). The devcontainer allowlist gains `apify.com` and `api.apify.com`.
- **Privacy:** the operator profile in a committed prompt; the repo is private (Q6).

## 17. Approval checklist

- [ ] Scope confirmed (Critical)
- [ ] Assumptions A1–A8 accepted
- [ ] Open questions Q1–Q10 resolved (or defaults accepted)
- [ ] Rollback accepted
- [ ] Escalation triggers acknowledged

## 18. Out of scope / follow-ups

- Market-demand analytics: trend queries, dashboards, skill co-occurrence, `pgvector` embeddings,
  read-only analytics role, `127.0.0.1`-bound port with an SSH tunnel.
- `emitExpired` for job-lifetime data; the actor's detail-enrichment toggle (fields and price
  unknown).
- Raw-data retention or partitioning policy, once volume is known (A4).
- A service-aware post-deploy check in `agent-deploy.reusable.yml` (R8), for all multi-service
  agents.
- Telegram inline buttons ("applied / dismiss") that feed operator decisions back into the DB as
  eval labels.
- Semantic repost detection beyond the actor's `repostOfId`.
- `kb/` doc updates at finalize, queued in `notes.md` during execution. Likely candidates: a
  "stateful agent with a DB" pattern note, and the firewall entry rationale.
