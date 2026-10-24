# Notes: upwork-scout

## Operator feedback and decisions

- 2026-10-22: Plan approved after three review rounds; decisions are recorded in plan.md §8.
- Never more than 10 jobs per actor run, including test scrapes.
- Budget limit: $20/month across all searches.
- Telegram is configured the way `arbproject-org/bb-trade-agent` `sdk_agent` does it: API id/hash in
  env, a per-stack bind-mounted `.session` file.
- The operator restarts the devcontainer to apply tooling changes (firewall, Dockerfile).
- The operator pasted a live Apify API token into the chat to run the sample scrape. It must never be
  written to a repo file. The operator should rotate it after Phase 1.

- After Phase 1 the operator asked for typed columns for the actor's extra fields, too, not
  only `raw`, and for the Phase 1 risks (R15–R19) to be carried into `report.md`.

## Phase 2 implementation notes (2026-10-23)

- **Deviation (Telegram login):** the session-setup helper ships in the image as
  `python -m agent.telegram_login`, run through `docker compose run --rm -it agent …`. It is not a
  copied venv folder as in bb-trade-agent, because CI ships only the compose file and the config to
  the VM. The session lives in a bind-mounted **directory** (`./telegram-session`), not a file
  mount, so Docker can never create a directory where the session file should be.
- **Deviation (screener fallback):** the screener has no fallback model. I didn't invent a model
  name the template doesn't use.
- **Found in the smoke run:** `chargedEventCounts` settles a few seconds *after* the run ends. An
  immediate re-read showed 0 result events for 1 returned item. Fix: the result-event count is
  floored at the number of items returned (unit-tested).
- **Smoke cycle** (real Apify + local Postgres, agents stubbed, writes off): 1 job fetched, because
  `maxAgeMinutes: 120` kept the new stateKey from walking back through the backlog. 1 new, 1
  screened, 1 drafted, delivery suppressed. Cost: $0.002. Total Apify spend so far: $0.024.
- **Template parity:** pyright's one remaining error (`HookMatcher(hooks=[gate])` in `guards.py`)
  is present verbatim in `agents/_template`. Plain `ruff format --check .` (no config) fails on
  the template too; the shared `${LINT_CONFIGS}/ruff.toml` is the effective gate. Candidates for
  harvest-lessons, along with the new-agent skill's macOS-only `sed -i ''`.
- Checking the `postgres:16` tag on the VM pulled the image there; the stack pins `postgres:16.15`.

## First real search

```text
https://www.upwork.com/nx/search/jobs/?contractor_tier=2,3&hourly_rate=40-&location=Americas,Europe&q=%28%22ai%20agent%22%20OR%20%22workflow%20automation%22%20OR%20chatbot%20OR%20%22internal%20assistant%22%29&t=0,1
```

Decoded: `q=("ai agent" OR "workflow automation" OR chatbot OR "internal assistant")`, intermediate
and expert tiers, hourly rate $40 and up, Americas and Europe, hourly and fixed-price jobs.

## Phase 1 sample scrape (2026-10-22)

Two runs of the operator's search URL, with `maxResults: 10`, `incrementalMode: true` and
`stateKey: upwork-scout-phase1-test`, through a throwaway script in the scratchpad. The 20 records
are in `sample-dataset.json`. Total spend: $0.022.

- **Field contract holds.** All 20 records have a non-null, unique `jobId`. Every `url` contains
  `~02<jobId>`. `contentHash` is a 64-char sha256. Descriptions are full with
  `descriptionMaxLength: 0` and no enrichment needed: 400–3,900 chars, ending naturally.
- **Fields beyond the README:** `contactEmail`, `contactName`, `contactPhone`, `extractedEmails`,
  `extractedPhones`, `extractedUrls`, `socialProfiles`, `salaryType`/`salaryMin`/`salaryMax`/
  `salaryCurrency`, `weeklyRetainerBudget`, `firstSeenAt`, `lastSeenAt`, `sourcingTimestamp`.
  They are kept in `raw`; no typed columns for them. `descriptionHtml` is null even with
  `descriptionFormat: all`.
- **Billing matches the README:** `chargedEventCounts` = 1 × `apify-actor-start` + 10 ×
  `apify-default-dataset-item`, at $0.001 each = $0.011 per run. **`usageTotalUsd` reports
  $0.001 and is NOT the charge**, so `scrape_runs.apify_cost_usd` must be computed as
  `chargedEventCounts` × `pricingInfo.pricingPerEvent`. The actor-start event is charged per GB of
  memory, so keep the run memory at ≤ 1 GB.
- **Incremental state records only emitted jobs.** Run 1 scanned 500 (of 818 available) and
  emitted the 10 newest. Run 2, two minutes later, emitted the *next* 10 older jobs, with zero
  overlap. Consequences:
  - Overflow beyond `maxResults` is **not lost**; it arrives in the next run.
  - Without an age bound, a new `stateKey` walks backwards through the ~500-job window at 10 per
    run, about 50 runs or 25 hours of full-price runs, before reaching steady state.
  - **Fix: set the actor's `maxAgeMinutes`** in `defaults_input` (recommended 120: four
    intervals of margin). The backlog walk then never starts, and `max_age_hours_to_screen` stays
    as the in-code backstop.
- **Real volume for this search:** the 20 newest jobs span 12:38–20:11 UTC, about 2.7 per hour,
  or ~1.4 per 30-minute run. Steady-state cost is about 1440 × ($0.001 + 1.4 × $0.001) ≈
  **$3.50/month**, well under $20. Still unknown: whether `contentHash` changes when only
  `totalApplicants` changes. If it does, UPDATED records keep R higher; check during the 24 h
  observation.
- **apify-client is 3.x** (3.3.0 at the time of the run): `call()` takes `run_timeout`
  (timedelta), `max_items` and `max_total_charge_usd`, and returns pydantic models
  (`model_dump(by_alias=True)`). Use `max_items` = `maxResults` and a small
  `max_total_charge_usd` as hard per-run cost caps enforced by Apify.

## Actor run input (from the operator's snippet)

Actor id `FlbDgNCfA8bOdFQWT`. Field names: `query`, `sort`, `verifiedPaymentOnly`,
`contractToHire`, `maxAgeMinutes`, `minClientTotalSpent`, `minClientRating`,
`minClientReviewCount`, `maxResults`, `descriptionMaxLength`, `compact`, `incrementalMode`,
`skipReposts`, `enrichDetails`, `detailConcurrency`, `notificationLimit`, `notifyOnlyChanges`,
`includeRunMetadata`, `descriptionFormat` (`all`), `excludeEmptyFields`, `proxyConfiguration`
(`{useApifyProxy: true}`), `emitUnchanged`, `emitExpired`.

`maxAgeMinutes` and the `min*` client fields are actor-side filters. They are candidates for the
config-driven filters in D7, and may cost less than filtering in code, because the actor bills
only the records it emits.

## Search quality investigation (2026-10-23)

Operator saw "n8n + OpenAI Automation Developer Needed" (jobId 2113578769155034747, published
10:30 UTC, fixed $200, Expert, US client) in the Upwork UI, but the agent's search missed it.
Seven capped runs (`scripts/try_scrape.py --fresh --max 10 --set maxAgeMinutes=600`, about $0.075):

| Run | Search | Total on Upwork | Job found? |
|---|---|---|---|
| e1 | `q=n8n`, no filters | 611 | yes |
| e2 | operator's keywords, no filters (window 08:51-10:48) | 2475 | no |
| e3-e5 | operator's URL minus location / rate / tier | 1238 / 1546 / 842 | no |
| e6 | operator's URL + `"ai agents"` | 930 (was 808) | yes |
| e7 | `q="ai agents"`, no filters | 1164 | yes |

Root cause: quoted phrases match exactly, with no plural stemming. The job says "AI agents" and
never "ai agent", "workflow automation", "chatbot" or "internal assistant". The URL filters are
applied by Upwork server-side (the totals change with them), and none of them excluded the job.
Adding the plural alone raised the matching pool by about 15%.

## Search tuning (2026-10-23)

Report: [search-tuning-report.md](search-tuning-report.md); raw numbers:
[search-tuning-log.md](search-tuning-log.md).

Operator decisions:

- Hourly jobs that state no rate are a **hard requirement** → no `hourly_rate` in any URL; the
  $70 floor lives in `prefilter.min_hourly_rate` (missing rate passes).
- Fixed price ≥ $1,000 (`amount=1000-`, fixed-only by Upwork's semantics).
- Regions: Europe, Northern America, Middle East = Upwork's Western Asia (not Egypt/North Africa),
  Australia **and New Zealand**.
- Fewer Apify searches to save cost; AI agents as their own search.
- 2026-10-23: **Option A chosen**: no `location` in search URLs, regions enforced in code via a new
  `prefilter.include_client_country_codes`. The report is the handover document for the agent
  developer (it carries the developer task prompt and draft screener/writer prompt texts).

Facts learned (details in the report): Upwork silently returns 0 above ~90 query words (the actor
too, with status SUCCEEDED); quoted single words are stemmed ("agentic" = "agent"); positive AND
mixed with OR is unreliable; the actor's logged-out location filter drops clients stored as ISO
codes (FRA/NLD/DEU), so location belongs in code; the actor also returns US-only posts the
operator's account cannot see. Session spend: 47 runs, $0.401.

Deferred doc update: if `scripts/try_scrape.py --state-suffix` (added for walk-backs, uncommitted)
stays, mention it in the README's experiments line.

## Reply flow, DinD, deploy (2026-10-23)

Plan: [plan-reply-flow-and-dind.md](plan-reply-flow-and-dind.md).

Operator decisions:

- Trigger: a **reply** to an offer containing a sign or word (default `+`, `go`), from any group
  member. Reactions were assessed and not chosen.
- Chat: a **private group**, posts from a separate **agent account** (Telethon user session).
- Automatic triage (screener) **parked**: code kept, `screening_enabled: false`.
- Devcontainer Docker: **Docker-in-Docker** (not the host socket).
- Telegram `chat_id` and the "About me" prompt text stay **placeholders**; the operator supplies
  the prompt later.
- **No budget logic in the agent**: the Apify spending limit is set at account level, so
  `monthly_budget_usd` / `budget_alert_ratio` and the month-to-date alert were removed. The
  per-run `max_charge_per_run_usd` actor cap and per-run cost recording stay.
- Deploy to the same VM through the existing reusable workflow (info-agent pattern); the caller
  got `workflow_dispatch` so the operator can redeploy after preparing the VM.

Facts learned: Docker Hub serves layer blobs from `production.cloudfront.docker.com` as well as
the Cloudflare host, so the firewall needs both. The runtime VM is aarch64; CI already builds
amd64 + arm64.

## Writer prompt and local run (2026-10-23)

Operator decisions:

- The writer uses the operator's **proposal metaprompt verbatim**; ABOUT ME is extracted from the
  two CVs (`CV Architect.pdf`, `CV_en.pdf`). Proposals must **never contain private information**
  (email, phone, LinkedIn); ABOUT ME also omits employer and client names (NDA style of CV_en).
  Hourly rate: $120 by default, always stated as negotiable depending on scope and expected hours.
- Prompts move to **their own files** (`prompts/<role>.txt`, `system_prompt_file` in the config)
  for easier versioning. Plain `.txt`: the metaprompt is plain text, and markdownlint would
  demand edits to it. CI ships `prompts/` beside the config (reusable workflow, optional step).
- Deploy happens only on merge to `main`; this task's scope is the local run.
- Local Telegram target: the basic group "Upwork Scout", `-5363412068` (local config only; the
  committed `chat_id` stays a placeholder).

Facts learned: inside the devcontainer, the inner dockerd cannot get the cgroup memory controller
(VS Code's `docker exec` sessions land in the container's root cgroup), so containers with a
memory limit fail with `memory.swap.max: no such file`; the local override drops the limits.
Moving processes to an `init` cgroup before dockerd starts did fix the earlier "threaded mode"
error.

## First VM deploy (2026-10-23)

- Operator request: deploy from the PR branch for a first test only. A TEMPORARY
  `feat/upwork-agent` push trigger in `upwork-scout.yml`, removed before merge; after that only a
  merge to `main` deploys. Sequence: deploy with writes off → Telegram login on the VM → commit
  `chat_id` + `allow_writes: true` → confirm → remove trigger → PR.
- The env file was copied from the devcontainer to the VM unread; the operator added
  `POSTGRES_PASSWORD` and created `.env.upwork-scout-db` on the VM.
- Pre-commit `/task-review` blockers were fixed: action majors re-pinned, the caller passes
  `SSH_PRIVATE_KEY` explicitly instead of `secrets: inherit`, two pyright errors fixed. **The
  template changed too** (caller template and `guards.py` return type), which affects every
  future agent.

Deferred doc update: `kb/conventions/agents.md` § Config and secrets says the prompt lives in
`agent_config.yaml` only; sanction `system_prompt_file` + `prompts/` (shipped by the reusable's
optional step) as the pattern.

Go-live (2026-10-24): Telegram login on the VM (session chmod 600/700); `allow_writes: true` and
`chat_id: -5363412068` committed; the 10 offers queued while writes were off were posted, by
operator choice. Operator asked for CET: the agent runs with `TZ=Europe/Berlin` (DST-aware) for
log lines and offer times; the DB and the VM clock stay UTC. The temporary branch trigger is
removed; deploys happen only on merge to `main`. Manual `docker compose` on the VM needs
`IMAGE_TAG=sha-<commit>` until a `main` build pushes `latest`.
