# Notes: upwork-scout screener live

## Operator decisions (2026-10-27)

- Scale 0–5, labelled "Match" (`Match 4/5 — reason`), as the second line of the offer, right
  under the linked title.
- Every job is posted whatever its match. There is no threshold.
- Screener model: the latest Sonnet, at medium effort (`claude-sonnet-5-5`, `effort: medium`).
- Eval data: the 20 applied-to postings plus 10 production jobs the operator ignored. The
  operator will gather more and notify me.
- Deploy through the PR (merge to `main`), not a branch trigger.

## Decisions made in execution

- The writer no longer gets the "Screening verdict" line, because the writer evals were reviewed
  without it. Writer v5 drops its mention.
- `submit_screening` takes `score` and `reason` only. `suitable` and `matched_criteria` are gone
  from the tool, but the DB columns stay (006 makes `suitable` nullable).
- A job the screener fails on `max_attempts` times is offered as `Match ?/5 — not rated`
  (`store.release(..., exhausted="screened")`).
- ABOUT ME moved verbatim except for writer-only instructions:
  - the rule-6 pointer is dropped, since rule 6 already says it;
  - the rate override and the negotiable note moved into rule 8;
  - about-me keeps "$125/hour, negotiable".
- The `prompt_sha` covers the role prompt plus ABOUT ME. The evals compute the same identity, and
  the provider appends ABOUT ME as production does. `--about-me` tries another version.
- The 10 ignored jobs were read from VM `jobs.raw` (read-only `SELECT`, temp file removed) and
  added with `add-jobs` (personal-data keys dropped). The VM had 0 screenings and no
  `suitable`/`unsuitable` rows, so no data migration was needed.

## Saved jobs (2026-10-27)

- The operator supplied 30 saved jobs as text. They are kept verbatim as
  `evals/datasets/source/upwork-saved-2026-10-27.txt`.
- `textimport` now also reads that layout (`JOB N of M`, header fields, `--- DESCRIPTION ---`,
  case ids `sNN-…`).
- 25 were imported into `screener.yaml` (v2, 55 cases). Saved 7, 9, 10, 16 and 21 were already
  there as applied (j04, j06, j07, j08, j10) and are skipped.
- Baseline on 55 cases: `eval-p6o-2026-10-27T21:10:08`. It supersedes `eval-yVk` (30 cases).
- Run-to-run variance is visible on the same prompt: j09 and j11 scored 4 in `eval-yVk` and 5 in
  `eval-p6o`, and j02 went from 3 to 4. Use `--repeat` before judging prompt changes by single
  scores.

## Queued doc updates (apply at finalize)

- kb/conventions/agents.md (versioned prompt files): a shared, role-agnostic document (ABOUT ME)
  is versioned the same way and appended by config. `prompt_sha` covers the composed text.
- kb/patterns/prompts-and-evals.md: the scoring-role review convention (👍 = agree; 👎 + a leading
  own mark), and its need for negatives in the dataset (applied-to-only data scores high).
