# 004 — upwork-scout-evals

**Date:** 2026-10-27

## Task

The operator asked for Promptfoo-based eval infrastructure for the upwork-scout writer prompt. The
loop: run the real agent over a dataset with one fixed prompt, review every draft in Promptfoo's
viewer, export the reviewed batch, have a separate editor model propose one candidate prompt, rerun
the same cases, compare, and adopt by hand. No LLM judge and no automatic optimisation. Mid-task the
operator added a Node LTS devcontainer bump, a real 20-job dataset, versioned prompt files, and
agent changes that came out of the first reviews.

## What was done

- **Evals** ([agents/upwork-scout/evals/](../../../agents/upwork-scout/evals/)), run as
  `uv run python -m evals`:
  - `provider.py`: a Promptfoo Python provider that runs `map_record → writer_prompt → run_once`
    with only the system prompt swapped, and retries like production.
  - `run` records a manifest (prompt, dataset and config shas, git commit) and adds a
    pending-review marker to every output.
  - `status` / `export`: verdicts come only from the operator's 👍/👎 (`human` component), and
    `status` also flags drafts that needed 3+ submits.
  - `propose`: the editor model (Agent SDK, `submit_candidate` with validation, `--note` for
    operator directions) writes `candidates/<id>/` with `CHANGES.md`.
  - `compare`; `import-text` / `add-jobs` for datasets.
  - Promptfoo 0.124.1 is pinned in `evals/package.json`.
- **Datasets:** a synthetic smoke set, plus the operator's 20 submitted-proposal postings split
  15 tuning / 5 validation, with the source text kept verbatim.
- **Agent** ([agents/upwork-scout/](../../../agents/upwork-scout/)):
  - The writer prompt moved to versioned files, `prompts/writer/v1–v3.md`. The config points at
    **v3**, the eval-approved candidate.
  - `writer.max_turns` is 8 (was 4).
  - A proposal goes out as one Telegram message; operator notes are stored, not sent.
  - The README has a "Prompt evals" guide.
- **Devcontainer:** `node:24-bookworm`
  ([.devcontainer/Dockerfile](../../../.devcontainer/Dockerfile)).
- **CI:** the [caller](../../../.github/workflows/upwork-scout.yml) ignores `evals/**`.
- **Lessons:**
  - a new [promptfoo skill](../../../.claude/skills/promptfoo/SKILL.md);
  - versioned prompt files in [conventions/agents.md](../../conventions/agents.md);
  - "a rejecting tool costs a turn per retry" in [patterns/tool-design.md](../../patterns/tool-design.md);
  - human-reviewed evals in [patterns/prompts-and-evals.md](../../patterns/prompts-and-evals.md);
  - two environment-limit rules in [CLAUDE.md](../../../CLAUDE.md).

## Result

- **Verification:** the smoke set runs end to end. A saved 👍/👎 and comment comes back in the
  export, keyed to the right case, output and prompt sha.
- **Review rounds:**
  - Round 1: v2 had 3/3 drafts rejected; the editor's candidate then had 2/2 rated drafts
    approved, and was adopted as v3.
  - Round 2: v3 had 3/3 approved on new jobs.
  - j09/j10/j13 (`eval-SFi-2026-10-26T20:53:44`) are not yet reviewed.
- **Checks:** 101 tests pass; `/task-review` found no blockers.
- **Deployment:** the VM still runs the original `writer.txt`. v3 deploys when the PR merges to
  `main`.

## Comment

- **Promptfoo pin:** pinned rather than `npx @latest`. Releases since 0.122 need Node ≥ 22.22,
  which drove the devcontainer bump.
- **Cache off by default:** the Python provider's cache key ignores imported agent code and
  config, so a cached rerun after a code change would replay stale drafts. `run` uses
  `--no-cache`, and `--reuse-cache` is opt-in.

## Follow-ups

- Remove `notes_for_operator` from `submit_proposal` together with its last mention in the next
  writer prompt version.
- Watch the word-limit retries: so far 3 of 9 drafts needed 3+ submits, all from question-heavy
  postings. If this becomes frequent, fix the prompt rather than raising `max_turns`.
- Improvement: revise a delivered draft by replying to it (README, Known gaps).
- Review j09/j10/j13, the remaining tuning jobs, then the 5 validation jobs on v3.
