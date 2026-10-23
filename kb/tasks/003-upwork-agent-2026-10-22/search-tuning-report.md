# Search tuning report and handover: upwork-scout

- **Date:** 2026-10-23.
- **Status:** decided. The operator chose **Option A**: no location in the search URLs, regions
  enforced in code.
- **For:** the developer who implements the agent and config changes.
- **Ready-to-run prompt:** [Handover prompt for the agent developer](#handover-prompt-for-the-agent-developer).
  Draft prompt texts for the agent itself are in [Prompts for upwork-scout](#prompts-for-upwork-scout-drafts).
- **Sources:** task prompt [search-tuning-prompt.md](search-tuning-prompt.md); raw measurements
  [search-tuning-log.md](search-tuning-log.md); session notes [notes.md](notes.md#search-tuning-2026-10-23).

## Decisions

| # | Decision | Value | Reason / evidence |
|---|---|---|---|
| D1 | Number of Apify searches | **3**: `ai-agents-automation`, `ai-llm-claude`, `devops-cloud` | Each search costs $1.44/month in run fees alone. One search can't hold everything because of the ~90-word query limit ([rules](#how-upworks-search-behaves-measured)) |
| D2 | Query shape | Pure OR lists of quoted phrases, at most 80 words each | OR is exact; AND/OR mixing is unreliable; over ~90 words the result is a silent 0 |
| D3 | Job types | `t=0,1` (hourly and fixed) | Operator brief |
| D4 | Fixed-price floor | `amount=1000-` in the URL + `prefilter.min_fixed_budget: 1000` | `amount` filters fixed-price jobs only, so hourly jobs are unaffected |
| D5 | Hourly floor | **No `hourly_rate` in the URL**; `prefilter.min_hourly_rate: 70` | **Hard requirement: keep hourly jobs that state no rate.** `hourly_rate` removes all of them; the prefilter lets a missing rate pass |
| D6 | Client regions | Europe, Northern America (US, CA), Western Asia (= Middle East: Gulf, Israel, Turkey, Levant; not Egypt/North Africa), Australia **and New Zealand** | Operator brief and follow-ups |
| D7 | Where regions are enforced | **Option A (chosen): in code**, `prefilter.include_client_country_codes` on the actor's `clientCountryCode`; **no `location` in the URL** | The actor's location filter loses clients stored as country codes (FRA/NLD/DEU), about 4% of jobs |
| D8 | Experience-level filter | **None** (drop `contractor_tier=2,3`) | Entry level is 2% of jobs, about 1/10 relevant |
| D9 | Interval, cap, age window | Unchanged: 30 min, `maxResults: 10`, `maxAgeMinutes: 120` | Average 2–3 new jobs per search per run; short peaks of 10–12 overflow into the next run |
| D10 | Budget | Expect about **$15/month** of the $20 | 3 × $1.44 in run fees + about 370 jobs/day × $0.001. The 80% alert ($16) is close: the operator decides whether to raise it |
| D11 | US-only posts (4–9% of jobs) | Accepted as noise for now; optional `enrichDetails` test | The actor has no field for the restriction |
| D12 | Upwork UI saved searches | Operator's own action; [proposal](#upwork-ui-saved-searches-operator-action) | Not part of the agent |

## What changes in the agent

1. **Config:** three new searches and new prefilter values. The exact diff is in
   [Implementation spec](#implementation-spec).
2. **New prefilter rule `include_client_country_codes`:** a region allow-list. It doesn't exist yet,
   and `config.py` rejects unknown keys.
3. **Config validation:** reject any search whose query is longer than 80 words. This prevents the
   silent-zero failure.
4. **Run monitoring:** alert when the actor's log has no "total available: N" or N = 0. This
   catches a broken query at runtime.
5. **Prompts:** fill the screener criteria and the writer's "About me" from the drafts below, after
   the operator confirms the flagged lines.
6. **Docs and tooling:**
   - README: searches, prefilter, limits, cost.
   - Keep and document the `--state-suffix` flag already added (uncommitted) to
     `scripts/try_scrape.py`.

## How Upwork's search behaves (measured)

| Rule | Evidence |
|---|---|
| `"a" OR "b"` is an exact union | "ai agent" 1,281 + "ai agents" 1,101 − both 594 = 1,788, as measured |
| A space between terms means AND | `"ai agent" "ai agents"` = 595 (the intersection) |
| `X AND NOT (group)` is exact, with OR-groups on either side | Three cross-checks matched exactly, e.g. 1,144 + 974 − 501 = 1,617 |
| **Mixing a positive AND with OR is unreliable** | `"ai agent" AND ("langchain" OR "langgraph")` = 945, while the true value is ≤ 193 (116 + 77). The operator's "cloud architect" mix was correct (483 = 1,022 − 539). Test any mixed query with its complement, or use pure OR lists |
| **About 90 words per query, then a silent 0** | 48 real terms (90 words) worked; 49 terms (93 words) gave 0 in the UI and on the actor (run `dPzPqFzebxvXJgQ7w`, status `SUCCEEDED`, 0 items, no total in the log). 58 single words worked, so the limit counts words. Phrases that match nothing don't count |
| Quoted single words are stemmed | `"agentic"` matches "agent": 518 extra jobs, 0/10 relevant. Multi-word phrases stay exact |
| No plural stemming inside phrases | "ai agent" ≠ "ai agents"; list both |
| `hourly_rate=70-` keeps a range if its top reaches 70, and **drops every hourly job with no rate** | "ai agent", 4 regions: 716 hourly → 55; 0 of 23 no-rate jobs survived |
| `amount=1000-` filters fixed-price only, even with `t=0,1` | 716 hourly + 76 fixed = 792, exact |
| Multi-word location names must be double-encoded | `Northern%2520America` etc. (UI only; the agent no longer sends location) |

## The Apify actor versus the logged-in feed

The actor (`blackfalcondata/upwork-scraper`) searches as a **logged-out visitor**. It parses the
`searchUrl` into its own filter object and re-runs the search. Two effects:

1. **The location filter loses jobs.**
   - The actor expands "Europe" into its own list of 31 countries.
   - Jobs whose client location Upwork stores as a country code are lost: "FRA", "NLD", "DEU". All
     3 such cases checked were lost.
   - A fixed $1,500 job from a German client came back with `t=0,1&amount=1000-`. It did not come
     back with `location=Europe…`, `location=Germany` or `location=DEU`.
   - The actor's record still carries `clientCountry` / `clientCountryCode` (ISO3), so the region
     check belongs in code. That is decision D7.
2. **Restricted posts appear.**
   - The actor returns 4–9% more jobs than the operator's feed shows.
   - Example: "US-Based Contract Attorney Needed", whose job page says *"Only freelancers located
     in the U.S. may apply."*
   - The operator, based in Germany, never sees these posts and cannot apply.
   - The actor record has no field for this, and the description usually doesn't mention it
     (D11).

## Parity of the starting searches

UI (logged in) and actor were read within a minute of each other. Mismatches are classified as:

- **restricted:** a US-only post, actor only;
- **location:** a client stored as a country code, lost by the actor's location filter.

| Search | UI count | Actor `upwork_total` (run) | Newest 10: shared / UI only / actor only | Verdict |
|---|---|---|---|---|
| Current config `ai-automation` (tier 2,3, hourly 40+, Americas+Europe) | 787 | 815 (`Up33F6pZZRK6ek3ui`) | 8 / 1 location ("AI Chatbot Developer — Instagram DM", FRA) / 1 restricted | Same slice ± the two effects |
| UI "ai assistant" (query only) | 2,346 | 2,482 (`XzqnASUxm1RgoHZSg`) | 10 / 0 / 0 | Same slice; no location filter, so the FRA job is kept |
| UI "cloud architect" (query only) | 483 | 526 (`LJteIXY0dzp3osNCw`) | 9 / 0 / 1 restricted | Same slice |
| UI "ai infra" | 0 | not run | — | Broken: 8 phrases with no OR = implicit AND |
| **Final S1** (no location) | 2,878 | 3,093 (`ZBV9NEpcCatVHJ9i9`) | 9 / 0 / 1 restricted | Same slice |
| **Final S2** (no location) | 2,558 | 2,743 (`O41iwSateUcmBPa3s`) | 9 / 0 / 1 restricted | Same slice |
| **Final S3** (no location) | 2,107 | 2,301 (`WBvjptkRBXLyuPWI5`) | 7 / 0 / 3 restricted | Same slice |

## Final searches

| Name | Terms / words | UI open jobs (no location) | Actor jobs / 24 h (with location) | Avg / peak per 30 min (with location) | Expected without location |
|---|---|---|---|---|---|
| `ai-agents-automation` | 32 / 59 | 2,878 | 102 | 2.1 / 8 | ~130/day, peak ~10–11 |
| `ai-llm-claude` | 35 / 68 | 2,558 | 96 | 2.0 / 9 | ~120/day, peak ~11 |
| `devops-cloud` | 25 / 39 | 2,107 | 83 | 1.7 / 9 | ~115/day, peak ~12 |

- **Peaks.** Peaks fall at 15:00–19:00 UTC (US morning). A run at a peak can hit the 10-job cap.
  The rest arrives in the next run, and with averages around 2.5 per run the backlog clears long
  before `maxAgeMinutes: 120`.
- **Overlap.** The three searches share 80 of 281 daily hits (201 unique). The database
  deduplicates them, but Apify charges both copies.
- **After the prefilters.** Hourly jobs whose range tops out below $70 are about 55% of hits, and
  out-of-region clients about 20%. Roughly **85 jobs/day** reach the screener; capacity is 10 per
  cycle, 480 a day.

**`ai-agents-automation`** (59 words)

```text
"ai agent" OR "ai agents" OR "agentic ai" OR "agentic workflow" OR "agentic workflows" OR "agentic system" OR "agentic systems" OR "agentic automation" OR "multi-agent" OR "multi agent" OR "autonomous agent" OR "autonomous agents" OR "agent sdk" OR "agents sdk" OR "crewai" OR "autogen" OR "langgraph" OR "langchain" OR "model context protocol" OR "voice agent" OR "voice agents" OR "agent development" OR "agent developer" OR "ai automation" OR "ai automations" OR "ai developer" OR "ai developers" OR "workflow automation" OR "workflow automations" OR "n8n" OR "openai api" OR "codex"
```

**`ai-llm-claude`** (68 words)

```text
"claude code" OR "claude api" OR "claude expert" OR "claude developer" OR "claude agent" OR "claude agents" OR "claude-based" OR "anthropic" OR "llm" OR "llms" OR "large language model" OR "large language models" OR "rag" OR "retrieval augmented" OR "retrieval-augmented" OR "vector database" OR "ai engineer" OR "ai engineering" OR "ai architect" OR "ai integration" OR "ai implementation" OR "ai adoption" OR "ai transformation" OR "forward deployed" OR "ai coding" OR "ai-assisted development" OR "bedrock" OR "azure openai" OR "vertex ai" OR "llm evaluation" OR "prompt injection" OR "fractional cto" OR "technical advisor" OR "architecture review" OR "production readiness"
```

**`devops-cloud`** (39 words)

```text
"devops" OR "site reliability" OR "platform engineer" OR "platform engineering" OR "kubernetes" OR "terraform" OR "infrastructure as code" OR "pulumi" OR "github actions" OR "gitlab ci" OR "cloud architect" OR "cloud engineer" OR "solutions architect" OR "cloud infrastructure" OR "devsecops" OR "mlops" OR "llmops" OR "ai infrastructure" OR "finops" OR "cloud migration" OR "aws" OR "azure" OR "gcp" OR "google cloud" OR "docker"
```

**Editing rules for these queries:**

- Stay at 80 words or fewer, counting hyphenated and slash-separated parts as separate words.
- Use quoted phrases joined by OR only.
- List singular and plural forms.
- Never add a single word that a stemmer can broaden ("agentic" → "agent").
- Re-measure before adding any term.

## Term decisions

- "Adds" = open jobs (with the filters) matched by the term and by no other term in its group.
- "Rel." = relevant share of the newest 10 of those jobs.

| Term(s) | Adds | Rel. | Decision |
|---|---|---|---|
| "agentic" | 518 | 0/10 | Reject. Stemmed to "agent": sales, support and sourcing agents |
| "agentic ai/workflow(s)/system(s)/automation" | 67 | 7/10 | Adopt |
| multi-agent, autonomous agent(s), agent(s) sdk, crewai, autogen, langgraph, model context protocol | 31 | 8/10 | Adopt |
| "langchain" | 16 | 6/10 | Adopt |
| "voice agent(s)" | 64 | 6/10 | Adopt ("AI Voice Agent" is not matched by "ai agent") |
| "agent development/developer" | 31 | 7/10 | Adopt |
| "mcp" | 80 | 3/10 | Reject. Matches certifications in ads and Workday jobs; Claude+MCP jobs are caught by S2 |
| "ai assistant" / "ai assistants" (+ "mcp server(s)") | 100 / 71 | 2/10 / 0/10 | Reject. VAs, GEO marketing |
| "voice ai", "ai voice", "conversational ai" | 356 | 0/10 | Reject. AI video and voice-over |
| "chatbot(s)", "ai chatbot" | 251 | 0–1/10 | Reject |
| "ai automation(s)", "workflow automation(s)", "ai developer(s)", "n8n", "openai api", "codex" | 529 / 329 / 267 (outside G1/G2) | 3–4/10 | Adopt into S1. Real AI-automation builds; the screener takes the noise |
| bare "claude" | 886 (after the Claude phrases) | ~1/30 | Reject. SEO, EA and controller jobs listing Claude as a tool |
| "claude code/api/expert/developer/agent(s)", "claude-based" | 298 | 4–5/10 | Adopt ("claude ai" dropped: EA noise) |
| "llm(s)", "large language model(s)" | 346 | 3/10 | Adopt. Core term; the noise is SEO "LLM visibility" |
| "generative ai", "genai", "gen ai" | 292 | 1/10 | Reject. Image and video generation |
| "rag" | 10 | 5/10 | Adopt |
| "ai integration/implementation/adoption/transformation" | 195 | 5/10 | Adopt |
| "ai consultant/consulting" | 56 | 0/10 | Reject. Cold callers hired by AI consultancies |
| "fractional cto", "technical advisor", "architecture review", "production readiness" | 96 | 4/10 | Adopt |
| "evals", "guardrails" | 53 (with LLM-evaluation phrases) | 0–1/10 | Reject (the phrases "llm evaluation", "prompt injection" stay: tiny and specific) |
| "openai", "chatgpt", "gpt" | 1,434 | 0–1/10 | Reject |
| "code review", "cto" | 124 | 2/10 | Reject |
| "ci/cd", "cicd" | 148 (with GitHub/GitLab) | 2/10 | Reject (full-stack jobs). Keep "github actions", "gitlab ci" |
| "solutions architect", "cloud engineer", "cloud infrastructure" | 92 | 5/10 | Adopt |
| "helm", "eks", "gke", "aks", "k8s", "sre" | 20 | 0/10 | Reject ("at the helm", talent "sourcer") |
| "aws", "azure", "gcp", "google cloud", "docker" | 680 | 5/10 | Adopt |
| "amazon web services", "containerization", "microservices", "cost optimization", "cloud cost", "systems architect" | 54 | 2/10 | Reject |

## Coverage proof

**Against the reference set** (the profile report's 30 searches and the operator's 3): every term
is either in a group or listed above with what it would add. No rejected term adds more than 2
relevant jobs in 10.

**Against the real feed, job by job.**

- **Method:** each final search was walked back through the last 24 hours on the actor, 10 jobs per
  run with its own incremental state, until a run came back short. That took 11, 10 and 9 runs. The
  result was compared with the newest 100 jobs in the operator's logged-in UI over the shared
  window.

| Search | UI jobs in window | Also on actor | UI only | Actor only |
|---|---|---|---|---|
| S1 | 91 | 87 (96%) | 4 | 14 (restricted pattern) |
| S2 | 98 | 94 (96%) | 4 | 2 |
| S3 | 74 | 74 (100%) | 0 | 9 |

- **Where the gaps come from:** the walk-backs still used the URL location filter. The 6 unique
  UI-only jobs come from the location leak; both checked had NLD- and DEU-coded clients.
- **Without the location filter (decision D7):** the final confirmation runs had **0 UI-only jobs**
  among the newest 10 of each search.

## Implementation spec

### 1. `agent_config.yaml`

The diff below is not applied yet.

- The URLs are single long lines. yamllint warns above 200 characters, which is a warning, not an
  error; the current config already has one.
- Don't wrap the URLs inside `>-`: folding inserts spaces into the URL.

```diff
     searches:
-      - name: ai-automation   # TODO(operator): confirm or replace; first search from the Phase 1 sample
+      - name: ai-agents-automation
         run_input:
           searchUrl: >-
-            https://www.upwork.com/nx/search/jobs/?contractor_tier=2,3&hourly_rate=40-&location=Americas,Europe&q=%28%22ai%20agent%22%20OR%20%22workflow%20automation%22%20OR%20chatbot%20OR%20%22internal%20assistant%22%29&t=0,1
+            https://www.upwork.com/nx/search/jobs/?q=%22ai%20agent%22%20OR%20%22ai%20agents%22%20OR%20%22agentic%20ai%22%20OR%20%22agentic%20workflow%22%20OR%20%22agentic%20workflows%22%20OR%20%22agentic%20system%22%20OR%20%22agentic%20systems%22%20OR%20%22agentic%20automation%22%20OR%20%22multi-agent%22%20OR%20%22multi%20agent%22%20OR%20%22autonomous%20agent%22%20OR%20%22autonomous%20agents%22%20OR%20%22agent%20sdk%22%20OR%20%22agents%20sdk%22%20OR%20%22crewai%22%20OR%20%22autogen%22%20OR%20%22langgraph%22%20OR%20%22langchain%22%20OR%20%22model%20context%20protocol%22%20OR%20%22voice%20agent%22%20OR%20%22voice%20agents%22%20OR%20%22agent%20development%22%20OR%20%22agent%20developer%22%20OR%20%22ai%20automation%22%20OR%20%22ai%20automations%22%20OR%20%22ai%20developer%22%20OR%20%22ai%20developers%22%20OR%20%22workflow%20automation%22%20OR%20%22workflow%20automations%22%20OR%20%22n8n%22%20OR%20%22openai%20api%22%20OR%20%22codex%22&t=0,1&amount=1000-&sort=recency
+      - name: ai-llm-claude
+        run_input:
+          searchUrl: >-
+            https://www.upwork.com/nx/search/jobs/?q=%22claude%20code%22%20OR%20%22claude%20api%22%20OR%20%22claude%20expert%22%20OR%20%22claude%20developer%22%20OR%20%22claude%20agent%22%20OR%20%22claude%20agents%22%20OR%20%22claude-based%22%20OR%20%22anthropic%22%20OR%20%22llm%22%20OR%20%22llms%22%20OR%20%22large%20language%20model%22%20OR%20%22large%20language%20models%22%20OR%20%22rag%22%20OR%20%22retrieval%20augmented%22%20OR%20%22retrieval-augmented%22%20OR%20%22vector%20database%22%20OR%20%22ai%20engineer%22%20OR%20%22ai%20engineering%22%20OR%20%22ai%20architect%22%20OR%20%22ai%20integration%22%20OR%20%22ai%20implementation%22%20OR%20%22ai%20adoption%22%20OR%20%22ai%20transformation%22%20OR%20%22forward%20deployed%22%20OR%20%22ai%20coding%22%20OR%20%22ai-assisted%20development%22%20OR%20%22bedrock%22%20OR%20%22azure%20openai%22%20OR%20%22vertex%20ai%22%20OR%20%22llm%20evaluation%22%20OR%20%22prompt%20injection%22%20OR%20%22fractional%20cto%22%20OR%20%22technical%20advisor%22%20OR%20%22architecture%20review%22%20OR%20%22production%20readiness%22&t=0,1&amount=1000-&sort=recency
+      - name: devops-cloud
+        run_input:
+          searchUrl: >-
+            https://www.upwork.com/nx/search/jobs/?q=%22devops%22%20OR%20%22site%20reliability%22%20OR%20%22platform%20engineer%22%20OR%20%22platform%20engineering%22%20OR%20%22kubernetes%22%20OR%20%22terraform%22%20OR%20%22infrastructure%20as%20code%22%20OR%20%22pulumi%22%20OR%20%22github%20actions%22%20OR%20%22gitlab%20ci%22%20OR%20%22cloud%20architect%22%20OR%20%22cloud%20engineer%22%20OR%20%22solutions%20architect%22%20OR%20%22cloud%20infrastructure%22%20OR%20%22devsecops%22%20OR%20%22mlops%22%20OR%20%22llmops%22%20OR%20%22ai%20infrastructure%22%20OR%20%22finops%22%20OR%20%22cloud%20migration%22%20OR%20%22aws%22%20OR%20%22azure%22%20OR%20%22gcp%22%20OR%20%22google%20cloud%22%20OR%20%22docker%22&t=0,1&amount=1000-&sort=recency
@@
   prefilter:
@@
-    min_hourly_rate: null
-    min_fixed_budget: null
+    min_hourly_rate: 70                # drops hourly ranges topping out below $70; no-rate hourly passes
+    min_fixed_budget: 1000             # backstop; the URLs already carry amount=1000-
     exclude_client_country_codes: null  # e.g. [IND, PAK]
+    # Europe, Northern America, Western Asia (Middle East), Australia and New Zealand: UN M49, ISO3.
+    include_client_country_codes: [
+      ALA, ALB, AND, AUT, BEL, BGR, BIH, BLR, CHE, CZE, DEU, DNK, ESP, EST, FIN, FRA, FRO, GBR, GGY, GIB,
+      GRC, HRV, HUN, IMN, IRL, ISL, ITA, JEY, LIE, LTU, LUX, LVA, MCO, MDA, MKD, MLT, MNE, NLD, NOR, POL,
+      PRT, ROU, RUS, SJM, SMR, SRB, SVK, SVN, SWE, UKR, VAT, XKX,
+      BMU, CAN, GRL, SPM, USA,
+      ARE, ARM, AZE, BHR, CYP, GEO, IRQ, ISR, JOR, KWT, LBN, OMN, PSE, QAT, SAU, SYR, TUR, YEM,
+      AUS, NZL, NFK]
```

- **Renaming resets incremental state.** Renaming `ai-automation` resets its state
  (`stateKey = upwork-scout-<name>`), and the new searches start with fresh state.
  `maxAgeMinutes: 120` bounds the first catch-up to about 3–4 runs per search.

### 2. New prefilter rule `include_client_country_codes`

- Add the key to `PREFILTER_KEYS` in `agent/config.py`.
- Add the rule to `agent/prefilter.py`, after `exclude_client_country_codes`.
- The rule must follow the module's contract: null = off, and a missing value passes.

```python
    if active("include_client_country_codes"):
        allowed = {str(c).upper() for c in rules["include_client_country_codes"]}
        code = job.get("client_country_code")
        if code and str(code).upper() not in allowed:
            return f"include_client_country_codes: {code} not in allowed regions"
```

Tests:

- a code in the list passes;
- a code not in the list is prefiltered with that reason;
- a missing code passes;
- case doesn't matter;
- null turns the rule off.

### 3. Config validation: query length

Make `AgentConfig.load` fail fast when a search's query is longer than **80 words**:

- Read the query from the `searchUrl`'s `q` parameter (URL-decoded) or from `query`.
- Count the words inside quoted phrases, splitting on whitespace, `-` and `/`.

The real limit is about 90 words, and above it Upwork returns 0 silently, so 80 leaves a margin. Add
a test with a 49-term query (93 words) that must be rejected, and the three final queries, which
must pass.

### 4. Monitoring: silently broken query

After each actor run, read the run log and parse `total available: (\d+)`. `scripts/try_scrape.py`
`log_counts` already does this.

- Log the value with the run.
- Emit an `AGENT ALERT` when it's missing or 0 for a search; for these broad searches that's always
  abnormal.
- Optional: persist it as `scrape_runs.upwork_total` (new migration) and alert only after N
  consecutive misses.
- A failed log read is reported, never raised, in line with `scrape.py`'s contract.

### 5. Tooling and docs

- **Keep `--state-suffix`** in `scripts/try_scrape.py`. It's already in the working tree,
  uncommitted, and separates the incremental state of experiments. Mention it in the README's
  experiments line, and in the walk-back recipe if you document one.
- **README updates:**
  - the three searches and why they hold no `location` / `hourly_rate` / `contractor_tier`;
  - the 80-word rule and the stemming caveats;
  - the new prefilter;
  - the cost estimate (about $15/month);
  - the known limitation: US-only posts reach the screener (D11).

### 6. Optional experiment (D11)

- Run one search once with `--set enrichDetails=true`, at most 10 items.
- Check whether the records gain a freelancer-location restriction field, and check the per-item
  charge.
- Report it; don't adopt it without the operator.

## Rejected alternatives

| Alternative | Why not |
|---|---|
| Option B: keep `location=…` in the URLs, no code change | About 4% of in-region jobs lost (clients stored as codes). It costs about $12.7/month instead of $15, but completeness was the requirement |
| The profile report's 30 separate searches | About $43/month in run fees alone |
| One combined search | Exceeds the ~90-word limit (G1+G2 alone is 112 words, which returned 0) |
| `hourly_rate=70-` in the URL | Drops all hourly jobs that state no rate (hard requirement) |
| `contractor_tier=2,3` | Removes 2% of jobs, about 1/10 relevant; not worth the risk |
| A fourth "AI automation" search | Merged into S1 instead (59 words); saves $1.44/month |
| Country codes in `location` | `location=DEU` and `location=Germany,DEU` still lost the DEU-coded job on the actor |

## Prompts for upwork-scout (drafts)

The prompts live only in `agent_config.yaml`. Paste these drafts there after the operator confirms
the flagged lines.

### Screener: replaces the `## Criteria` TODO

```text
## Criteria
The freelancer is a senior AI and cloud engineer: AI agents, LLM applications and Claude Code for
engineering teams, on top of DevOps on AWS, Azure and GCP. Mark a job suitable when its core work
is one of:
- AI agents: agentic workflows, multi-agent systems, voice agents, agent SDKs (Claude Agent SDK,
  OpenAI Agents SDK, LangChain, LangGraph, CrewAI), MCP servers and tool integrations.
- LLM applications: RAG and knowledge bases, vector databases, evals and guardrails, prompt
  injection, cost control, Bedrock / Azure OpenAI / Vertex AI.
- Claude, Claude Code and AI coding agents for engineering teams: setup, CLAUDE.md, hooks,
  sandboxing, AI code review in CI.
- AI integration, implementation, adoption or transformation for a business; AI architecture;
  forward deployed engineering; fractional CTO, technical advisor, architecture or production
  readiness reviews.
- DevOps, platform and cloud: Kubernetes, Terraform / IaC, CI/CD (GitHub Actions, GitLab CI),
  Docker, AWS / Azure / GCP architecture and migration, MLOps / LLMOps, FinOps.
- AI automation builds (n8n, Make, Zapier) only when they integrate LLMs or agents into real
  systems, not simple app-to-app glue.

Money: hourly work that reaches $70/hour or states no rate, fixed price from $1,000. Rates and
regions are already filtered before you; mark unsuitable only when the text shows the real budget
is far below that (for example "$10/hour", "$300 total").

Not suitable, even when the text mentions AI, ChatGPT, Claude or LLMs:
- sales, cold calling, appointment setting, lead generation, recruiting or talent sourcing;
- customer support, virtual or executive assistant, data entry, admin and operations roles;
- marketing, SEO / GEO, ads, social media or content writing that only uses AI tools;
- AI image, video, music or voice-over production;
- testing gigs, technical interviewer or tutoring panels, research participation;
- web, mobile, WordPress, Shopify or no-code work with no AI or infrastructure scope;
- jobs the posting restricts to freelancers in a specific country other than Germany or the EU.

Client quality lowers the score but does not decide on its own: no payment verification and no
spend history is a weak signal; a new client with a clear, well-scoped brief can still fit.
```

### Writer: replaces the `## About me` TODO

Built from the operator's 2026-10-19 profile analysis. **[CONFIRM]** marks a line the operator must
confirm or soften before the text goes into the config. Then remove the markers.

```text
## About me
- AI agent & LLM engineer, Claude Code for engineering teams, and DevOps on AWS, Azure and GCP.
  Based in Berlin (CET); available for calls in European and US East Coast hours. Rate $120/hour.
- Anthropic Claude Certified Architect (2026). [CONFIRM which cloud certifications are current:
  AZ-305, Google Cloud PCA, AWS SAA, CKA; otherwise write "previously AWS, Azure, Google Cloud and
  CKA certified"]
- Builds AI agents and LLM apps for production: RAG, MCP tools and connectors, multi-agent
  workflows, evals, guardrails, prompt-injection testing, observability, token cost control.
  Claude, OpenAI, Gemini; LangChain, LangGraph, Claude Agent SDK; Bedrock, Azure OpenAI, Vertex AI.
- Sets up Claude Code for teams the way a platform team would: CLAUDE.md per area of a monorepo,
  subagents and slash commands, hooks that hold risky commands (terraform apply, kubectl delete)
  for human approval, sandboxed dev containers, secrets kept from the model, AI review in CI.
- Recent work (clients anonymised):
  - B2B SaaS company: AI assessment and target architecture delivered over a weekend; rated 5.0.
  - Global biotech: enterprise AI workspace, Microsoft 365 Copilot grounded in company data, with
    MCP connectors acting in business systems inside existing access rules.
  - German enterprise: chat-with-your-data copilot on AWS over Confluence and document stores.
  - 30-service Go and Node.js monorepo: Claude Code with per-service CLAUDE.md, approval hooks and
    sandboxed agents, on CI/CD hardened for parallel builds. [CONFIRM public]
  - Gaming platform and European crypto exchange: multi-account AWS and Kubernetes platforms, spot
    savings, production EKS migration from on-premises.
- English native or bilingual, German conversational.
- Never claim: "10+ years" [CONFIRM: employment history shown starts Oct 2021], client names,
  numbers not listed here.
```

## Handover prompt for the agent developer

Paste as-is into a fresh Claude Code session in this repo.

````markdown
# Context

- `agents/upwork-scout` scrapes Upwork every 30 minutes through the Apify actor
  `blackfalcondata/upwork-scraper`: one run per configured search, at most 10 jobs per run, a
  $20/month budget. Jobs pass code prefilters, then a screener agent, then a writer agent.
- Search tuning is finished and decided: `kb/tasks/003-upwork-agent-2026-10-22/search-tuning-report.md`
  (the operator chose Option A). Read its Decisions, "The Apify actor versus the logged-in feed",
  Implementation spec and "Prompts for upwork-scout" first.
- Facts that drive the work: Upwork returns 0 silently above ~90 query words; hourly jobs with no
  rate must be kept, so no `hourly_rate` in URLs; the actor's location filter loses clients stored
  as country codes, so regions are enforced in code on `clientCountryCode`.

# Task

1. Read the report sections above, `kb/conventions/agents.md` and `agents/upwork-scout/README.md`.
2. Add the prefilter rule `include_client_country_codes` (config key + rule + tests) exactly as in
   Implementation spec §2.
3. Add config validation that rejects any search query over 80 words, with tests (spec §3).
4. Add the "total available" check and `AGENT ALERT` for silently broken queries, with a test
   (spec §4).
5. Apply the `agent_config.yaml` diff from spec §1: three searches, prefilter values, country list.
6. Replace the screener `## Criteria` and writer `## About me` TODOs with the drafts in "Prompts for
   upwork-scout". Ask the operator to resolve every [CONFIRM] line first; never ship a [CONFIRM]
   marker.
7. Keep `--state-suffix` in `scripts/try_scrape.py`; update the README (spec §5).
8. Verify: `uv run pytest -q`, `ruff check`, `docker build`; then one `scripts/try_scrape.sh --fresh
   --set maxAgeMinutes=1440 --search <name>` per search, and confirm `upwork_total` is non-zero and
   within ~15% of the report's actor totals (3,093 / 2,743 / 2,301).
9. Optional, only if the operator agrees: the `enrichDetails` experiment (spec §6).
10. Run `/task-review`, fix block findings, then present the PR title and body and wait for approval.

# Constraints

- `maxResults` never above 10, in config or in test runs; the scripts enforce it.
- Never open any `.env*` file; the Apify token reaches scripts only as `APIFY_TOKEN`.
- No `location`, `hourly_rate` or `contractor_tier` in any `searchUrl`; queries stay pure OR lists
  of quoted phrases. Don't add or remove terms without re-measuring (report: Term decisions).
- `agent.allow_writes` stays false. Prefilters stay config-gated: null = off, missing value passes.
- Apify spend for verification at most $0.10.
- Git: work on a branch, never push to main, no `Co-Authored-By` trailer, PR text approved before
  `gh pr create`.

# Heads-up

- `docker build` hung for 40 minutes on the operator's host during tuning. If it hangs, stop and
  ask; the scratch-venv fallback (`UV_PROJECT_ENVIRONMENT=<dir> uv run --locked`) works for
  `try_scrape.py`.
- Expected cost is about $15/month, close to the 80% alert ($16 of $20); ask the operator whether
  to raise `monthly_budget_usd`.
- About 4–9% of delivered jobs will be US-only posts the operator cannot apply to (no field for it
  in the actor output). That is accepted for now.

# Acceptance criteria

1. `include_client_country_codes` works as specified, with tests for in-list, out-of-list,
   missing, case and off.
2. Config load rejects a query over 80 words; the three final queries load.
3. A run with no or zero "total available" produces an `AGENT ALERT` (tested).
4. `agent_config.yaml` holds exactly the three searches and prefilter values from the report; the
   old `ai-automation` search is gone.
5. Screener criteria and About me are filled with no [CONFIRM] markers left.
6. README documents searches, prefilters, limits, cost and the `--state-suffix` flag.
7. pytest, ruff and docker build are green; each search's verification run shows a non-zero
   `upwork_total`; spend is reported.
8. `/task-review` has no block findings; the PR is proposed, not created, until the operator
   approves.
````

## Upwork UI saved searches (operator action)

- **Not for the developer.**
- The logged-in UI filters location correctly, so the UI keeps the region filter.
- The UI has no cost or URL-length pressure, so the extra searches are narrow views for quick
  scanning.
- Upwork names a saved search after its query, so each query starts with its most telling phrase.

| # | Query (first terms) | Filters | Purpose |
|---|---|---|---|
| 1 | S1 query ("ai agent" OR …) | 4 regions, hourly + fixed, fixed ≥ $1,000 | Mirror of the agent's S1 |
| 2 | S2 query ("claude code" OR …) | same | Mirror of S2 |
| 3 | S3 query ("devops" OR …) | same | Mirror of S3 |
| 4 | "claude code" OR "claude agent" OR "claude agents" OR "claude api" OR "anthropic" OR "agent sdk" OR "mcp server" OR "model context protocol" | same | Signature offer, low volume |
| 5 | "forward deployed" OR "ai transformation" OR "ai adoption" OR "ai architect" OR "fractional cto" OR "technical advisor" OR "architecture review" OR "production readiness" | same | FDE, transformation and advisory work |
| 6 | "ai agent" OR "ai agents" OR "llm" OR "rag" OR "claude code" OR "ai engineer" OR "ai architect" OR "devops" OR "kubernetes" OR "terraform" | 4 regions, hourly only, $70+/hr | Best-paid hourly, first thing to check |
| 7 | same as 6 | 4 regions, fixed only, $5,000+ | Big-ticket fixed projects |
| 8 | "german-speaking" OR "german speaking" OR "deutschsprachig" | Germany, Austria, Switzerland | Optional: German-language clients |

Delete:

- **"ai infra":** 0 jobs.
- **"ai assistant":** replaced by #1; its `chatbot` term is noise.
- **"cloud architect":** works, but #3 covers it except "systems architect".

## Spend and method

- **Apify:** 47 runs, **$0.401**, under the $1.00 cap.
  - 33 runs were the 24-hour walk-backs (30) and final confirmations (3); the rest were syntax,
    parity and diagnostic runs.
  - The 10-job cap was never raised, and no `.env*` file was opened.
  - The token was passed per command and written nowhere. The operator should rotate it, since it
    was pasted in chat.
- **Browser:** about 180 page loads of Upwork search and job pages, in one tab, logged in and
  read-only.
  - Pauses were random (5–25 s between loads, with longer breaks). No captcha or warning appeared.
  - Nothing on the account was changed.
- **Tooling:** the agent's Docker image build hung for 40 minutes on the operator's host, so runs
  used a scratch venv built from the committed `uv.lock`.

## Open items (operator)

- Resolve the [CONFIRM] lines in the About me draft.
- Decide on `monthly_budget_usd` (D10) and on the `enrichDetails` experiment (D11).
- Approve and apply the UI saved-search changes (optional).
- Rotate the Apify token.
- Re-check volumes 1–2 weeks after deploy using `scrape_runs` (they were measured on one Thursday).
