# 004 — upwork-scout writer evals (Promptfoo, human review)

**Date:** 2026-10-24 · **Branch:** `feat/upwork-agent` (operator's current branch)

Written by the main agent directly from the operator's detailed task prompt (Context / Task / AC),
which already fixed the workflow. No separate planning round.

## Goal

Make the writer prompt (`agents/upwork-scout/prompts/writer.txt`) improvable from the operator's
own reviews. Run the real writer over a dataset with one fixed prompt, have the operator review each
draft in Promptfoo's viewer, export the reviewed batch, have a separate model propose ONE candidate
prompt with a change list tied to case IDs, rerun on the same cases, compare, and let the operator
decide on adoption. No LLM judge and no automatic optimisation loop.

## Design

- **Location:** `agents/upwork-scout/evals/`, a Python package run from the agent's own venv
  (`uv run python -m evals …`). Docs go in the agent README (one page per agent). The image
  never ships it (`.dockerignore` already excludes `evals/`).
- **Promptfoo** pinned in `evals/package.json` plus a lockfile, version `0.124.1` (Node ≥ 22.22).
  The devcontainer moves `node:20` → `node:24-bookworm` (current LTS, same Debian as before).
- **Provider:** `evals/provider.py` (Python provider). Raw Apify actor record →
  `store.map_record` → `render.writer_prompt` → `loop.run_once` with the writer role from
  `agent_config.yaml`, only `system_prompt` replaced by the prompt under test. Fresh SDK session per
  case, `allow_writes=False`, the real `submit_proposal` tool.
- **Datasets:** YAML with `dataset: {id, version, split}` and `cases: [{id, job_file | job,
  operator_instructions?, reference?, metadata?}]`. Splits are `smoke`, `tuning` and `validation`.
  The prompt editor refuses validation feedback by default. The smoke set is synthetic and labelled.
- **Experiment record:** `run` writes `runs/<run_id>/{manifest.json, promptfooconfig.yaml,
  results.json}` and embeds the manifest in the eval's `metadata`. The manifest holds the prompt
  path and sha, the dataset id, version and sha, the writer config, the git commit and dirty flag,
  and the Promptfoo version.
- **Review state:** every output carries a deterministic `human_review` marker assertion that
  fails with "Awaiting human review". A 👍/👎 in the viewer overrides it. In the viewer, Passes
  shows human-approved outputs only. The export reads verdicts only from the `human` component.
- **Export:** `promptfoo export eval` (DB-backed, so it carries the latest saved ratings) →
  `feedback/<run_id>.json`. It refuses unreviewed results unless `--partial` is passed.
- **Editor:** `propose` sends the package to a configurable model through the Claude Agent SDK
  (subscription auth) with one `submit_candidate` tool. Output goes to `candidates/<id>/`
  (`prompt.txt`, `CHANGES.md` with a diff, `proposal.json`). It never touches `prompts/`.
- **Compare:** `compare A B` pairs results by case ID: verdicts, comments and word counts.
- **CI:** the caller ignores `agents/upwork-scout/evals/**`, so a review or candidate commit does
  not redeploy the agent.
