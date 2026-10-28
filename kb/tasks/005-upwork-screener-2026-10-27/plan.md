# 005 — upwork-scout screener live (Match 0–5) + shared ABOUT ME + screener evals

**Date:** 2026-10-27 · **Branch:** `feat/upwork-agent` (the open, not-yet-PR'd branch)

Written by the main agent from the operator's request and four answered questions, as in task 004.

## Goal

1. Every job that passes the prefilters is screened by the screener agent. It rates how well the
   posting matches the operator's experience, from 0 to 5. **Every job is still posted**, and
   nothing is hidden by the rating.
2. The offer message reads: linked title, then **`Match 4/5 — <one-sentence reason>`**, then
   pricing, client, applicants and skills, as today.
3. The ABOUT ME part of the writer prompt becomes **one shared document**, not written for any
   one agent. The writer and the screener both get it appended to their system prompts, and the
   operator iterates on it (case studies, extra projects) separately from either prompt.
4. The screener gets the same human-reviewed Promptfoo loop as the writer: the existing 20
   operator jobs, plus 10 low-fit jobs from production. The operator rates each output 👍/👎 with
   their own mark and a short comment.

## Operator decisions (2026-10-27)

- **Scale 0–5.** The rating is labelled "Match", and every job is posted whatever its rating.
- **Eval data:** the existing 20 jobs plus 10 offered jobs from production that got no reply. The
  operator will gather more and notify me.

## Design

### Shared ABOUT ME

- New `prompts/about-me/v1.md`: `## ABOUT ME` through `### Rate` from writer v4, moved verbatim
  except for two writer instructions, which stay in the writer prompt:
  - "Experience beyond them follows rule 6 …";
  - "a rate in the operator's comment replaces it; wherever a proposal states the rate, follow it
    with a negotiable note …".

  ABOUT ME keeps the fact: $125/hour by default, negotiable depending on scope and hours. The file
  is versioned like the prompts: a change is a new `v<N+1>.md`, plus a one-line pointer change.
- **Config:** a new top-level `about_me_file: prompts/about-me/v1.md` (optional; when omitted,
  nothing is appended). `config.py` appends it to every role's prompt as
  `<role prompt>\n\n<about me>`. Both are bind-mounted, since CI already ships all of `prompts/`.
- **The `prompt_sha` covers the composed text**, so a new ABOUT ME version shows up in every stored
  verdict and draft. `prompt_ref` becomes `prompts/writer/v5.md+prompts/about-me/v1.md@<sha>` in
  the startup log. `RoleConfig` keeps the role file and the about-me file separately, so the evals
  can swap either one.
- **Writer v5** = v4 minus the ABOUT ME section, with the two writer-only sentences kept in rule 6
  and rule 8. Composed with about-me v1, the writer's input is the same in substance as v4.

### Screener

- **Screener v2** (`prompts/screener/v2.md`) is rewritten around one question: how well does this
  posting match the experience in ABOUT ME? The 0–5 rubric:
  - 5: the core work is squarely what the ABOUT ME projects did;
  - 4: strong overlap with a minor gap;
  - 3: the main stack is known, but the domain or a part is new;
  - 2: adjacent;
  - 1: barely related;
  - 0: unrelated, or an excluded category (v1's "Not suitable" list, a country restriction, or a
    budget far below the floor).

  The reason is one sentence for the Telegram line, naming the matching ABOUT ME experience or the
  gap. v1's "Criteria" list (the work the operator wants) stays as the target-work anchor, the
  injection guard is kept, and the client-quality note now lowers the score by at most 1.
- **Tool:** `submit_screening(score: 0–5, reason: str ≤ 300 chars)`. `suitable` and
  `matched_criteria` are dropped, because nothing filters on them now. Migration `006` makes
  `screenings.suitable` nullable. The 0–100 rows (if any) stay as history, and `prompt_sha` tells
  them apart.
- **Pipeline:**
  - with `screening_enabled: true`: `pending → screening → screened → offered`;
  - a screening that uses up `max_attempts` still goes to `screened`, with the error as its reason,
    and its offer shows `Match ?/5`: a job is never lost to a screener failure;
  - a rate limit requeues, as today;
  - `suitable`/`unsuitable` statuses are no longer written, and the offer queue reads `screened`.
- **Config:**
  - `screening_enabled: true`;
  - the screener model `claude-sonnet-5` → `claude-sonnet-5-5` (the latest Sonnet),
    `effort: medium` (operator, 2026-10-27), for about 140 runs a day on the subscription;
  - `max_screen_per_cycle: 20`.
- **Writer input:** the writer no longer gets the "Screening verdict" line. The writer evals ran
  without it, so production stays equal to what was reviewed.

### Telegram offer

```text
<b><a href=…>Title</a></b>
Match 4/5 — Kubernetes cost work on AWS, like the Karpenter/Spot project.
Hourly $70-$120/hr
Client: …
Applicants: … · Published …
Skills: …
```

### Screener evals (no new tooling beyond a role switch)

- `run --role screener` (the default stays `writer`): the provider calls `screener_prompt` →
  `run_once` with the screener role, and the system prompt under test is composed with the
  about-me file. `--about-me <path>` tries a new ABOUT ME version for either role. The output is
  `Match N/5 — reason`, and the metadata holds the score, reason and turns. The manifest, run id
  and labels name the role.
- **Review:** 👍 if the mark is right. Otherwise 👎, with a comment that starts with your own mark
  and a short why: `2 — mostly frontend; the k8s part is minor`. `export` parses the leading
  digit into `operator_score`. `status` and `compare` show the agent's score next to yours. The
  `human_review` marker and verdict rules are unchanged.
- **Dataset** `evals/datasets/screener.yaml` (split `tuning`) references the 20 existing fixtures
  (`metadata: {source: applied}`), plus 10 new fixtures from production (`source: ignored`):
  - the 10 are offered jobs with no request, from the VM's Postgres, read-only, picked from
    different searches;
  - they are added through `add-jobs`, which drops the contact and personal-data fields.
- `propose` (the editor) stays writer-only for now: it refuses `--role screener` with a clear
  message. The screener prompt is edited by hand from the review until a screener editor prompt
  is worth building.

## Steps

1. `prompts/about-me/v1.md`, `prompts/writer/v5.md`, `prompts/screener/v2.md`; config
   composition, `prompt_ref` and `agent_config.yaml`.
2. Tool, migration 006, pipeline statuses, render (offer line, writer prompt without the
   verdict), and tests.
3. Evals: role switch, `--about-me`, the screener output, `operator_score`, and status and
   compare columns.
4. Pull the 10 production jobs (read-only SQL over SSH), `add-jobs` into `screener.yaml`.
5. Run the screener baseline on the 30 cases and hand the eval id to the operator.
6. README (agent) updates.
7. `/task-review`, then human review of the diff, then commit.
8. Deploy: the branch is not on `main` yet. **Ask the operator:** merge the PR, or a temporary
   branch trigger as before.

## Verification

- `uv run pytest -q`, `ruff check`, and `docker build`.
- The startup log shows both prompt refs with the about-me file.
- After the deploy, the first cycle logs `screened job=… score=…`, and offers in the group carry
  the Match line.

## Out of scope

- A screener editor (`propose --role screener`).
- A threshold that hides low matches (`min_match_to_offer`); it can be added later from data.
- Re-screening jobs that were already offered.
