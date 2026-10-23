-- upwork-scout schema v1. Forward-only: fix a bad migration with a new one, never by editing this.
-- All timestamps are timestamptz (UTC). Market data (jobs, job_versions, job_searches) is never
-- deleted by the pipeline; operational state lives in pipeline/screenings/proposals.

-- One row per Apify run (one per search per cycle): cost and volume audit, and the denominator
-- for "postings per period" in later analysis.
CREATE TABLE scrape_runs (
  id               bigserial PRIMARY KEY,
  started_at       timestamptz NOT NULL DEFAULT now(),
  finished_at      timestamptz,
  status           text NOT NULL,          -- running | succeeded | failed
  search_name      text NOT NULL,          -- settings.apify.searches[].name
  cycle_started_at timestamptz NOT NULL,   -- groups the per-search runs of one cycle
  apify_run_id     text,
  apify_dataset_id text,
  run_input        jsonb NOT NULL,         -- exact input sent (query/searchUrl, filters, stateKey)
  items_total      int,
  items_new        int,
  items_known      int,
  items_invalid    int,
  apify_cost_usd   numeric(10,4),          -- chargedEventCounts x pricingPerEvent, NOT usageTotalUsd
  error            text
);
CREATE INDEX scrape_runs_started_at ON scrape_runs (started_at);

-- Market data: one row per Upwork job, latest state. jobId is THE dedup key.
CREATE TABLE jobs (
  job_id                       text PRIMARY KEY,
  url                          text NOT NULL,
  title                        text NOT NULL,
  description                  text,
  description_markdown         text,
  job_type                     text,
  experience_level             text,
  budget_amount                numeric,
  budget_currency              text,
  hourly_budget_min            numeric,
  hourly_budget_max            numeric,
  weekly_retainer_budget       numeric,
  salary_type                  text,
  salary_min                   numeric,
  salary_max                   numeric,
  salary_currency              text,
  engagement_type              text,
  engagement_duration          text,
  engagement_duration_weeks    int,
  skills                       text[] NOT NULL DEFAULT '{}',
  published_at                 timestamptz,   -- publishTime
  created_at_upwork            timestamptz,   -- createTime
  total_applicants             int,
  persons_to_hire              int,
  enterprise_job               boolean,
  premium                      boolean,
  custom_job_score             numeric,
  client_country               text,
  client_country_code          text,
  client_total_spent           numeric,
  client_spent_currency        text,
  client_payment_verified      boolean,
  client_rating                numeric,
  client_review_count          int,
  client_has_financial_privacy boolean,
  is_repost                    boolean,
  repost_of_id                 text,
  repost_detected_at           timestamptz,
  -- Personal data, mostly null. Stored only here; never sent to Telegram or into prompts.
  contact_name                 text,
  contact_email                text,
  contact_phone                text,
  extracted_emails             text[] NOT NULL DEFAULT '{}',
  extracted_phones             text[] NOT NULL DEFAULT '{}',
  extracted_urls               text[] NOT NULL DEFAULT '{}',
  social_profiles              jsonb,
  actor_first_seen_at          timestamptz,   -- actor-side firstSeenAt (per stateKey)
  actor_last_seen_at           timestamptz,
  sourcing_timestamp           timestamptz,
  scraped_at                   timestamptz,   -- latest scrapedAt
  source                       text,
  content_hash                 text NOT NULL, -- latest contentHash
  first_seen_at                timestamptz NOT NULL DEFAULT now(),
  last_seen_at                 timestamptz NOT NULL DEFAULT now(),
  seen_count                   int NOT NULL DEFAULT 1,
  first_run_id                 bigint REFERENCES scrape_runs(id),
  raw                          jsonb NOT NULL,  -- latest FULL record, verbatim
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
  job_id           text NOT NULL REFERENCES jobs(job_id),
  content_hash     text NOT NULL,
  change_type      text,                     -- actor changeType, informational only
  seen_at          timestamptz NOT NULL DEFAULT now(),
  run_id           bigint REFERENCES scrape_runs(id),
  total_applicants int,
  raw              jsonb NOT NULL,
  PRIMARY KEY (job_id, content_hash)
);
CREATE INDEX job_versions_seen_at ON job_versions (seen_at);

-- Which searches surfaced which job. A job matched by two searches is still ONE jobs row and is
-- screened once; this only records the overlap, for later per-search demand analysis.
CREATE TABLE job_searches (
  job_id        text NOT NULL REFERENCES jobs(job_id),
  search_name   text NOT NULL,
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  first_run_id  bigint REFERENCES scrape_runs(id),
  PRIMARY KEY (job_id, search_name)
);

-- The ledger of agent processing: exactly one row per job, created only on the job's first-ever
-- insert. Agents read only from here, so no job can reach an agent twice.
CREATE TABLE pipeline (
  job_id     text PRIMARY KEY REFERENCES jobs(job_id),
  status     text NOT NULL,  -- pending | prefiltered | skipped_repost | skipped_stale | screening
                             -- | unsuitable | suitable | drafting | drafted | delivered | error
  reason     text,           -- prefilter/skip reason, or last error
  attempts   int NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX pipeline_status ON pipeline (status);

CREATE TABLE screenings (
  id               bigserial PRIMARY KEY,
  job_id           text NOT NULL REFERENCES jobs(job_id),
  created_at       timestamptz NOT NULL DEFAULT now(),
  prompt_sha       text NOT NULL,
  model            text NOT NULL,
  suitable         boolean NOT NULL,
  score            smallint,
  reasons          text,
  matched_criteria text[] NOT NULL DEFAULT '{}',
  cost_usd         numeric(10,4),
  num_turns        int,
  duration_s       numeric,
  UNIQUE (job_id, prompt_sha)
);

CREATE TABLE proposals (
  id                   bigserial PRIMARY KEY,
  job_id               text NOT NULL REFERENCES jobs(job_id),
  screening_id         bigint NOT NULL REFERENCES screenings(id),
  created_at           timestamptz NOT NULL DEFAULT now(),
  prompt_sha           text NOT NULL,
  model                text NOT NULL,
  body                 text NOT NULL,
  notes_for_operator   text,
  cost_usd             numeric(10,4),
  num_turns            int,
  duration_s           numeric,
  telegram_chat_id     text,
  telegram_message_ids bigint[],
  delivered_at         timestamptz,
  UNIQUE (job_id, prompt_sha)
);
CREATE INDEX proposals_undelivered ON proposals (created_at) WHERE delivered_at IS NULL;
