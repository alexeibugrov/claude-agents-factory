# Plan: VHS Sprachtest appointment watcher (side project)

- **Date:** 2026-11-26
- **Scope:** Small — first entry under a new `side-projects/` root
- **Status:** Approved in chat (prompt confirmed, Telegram = user account, test = allowlist + rebuild)

## Summary

A small Python container that checks the Berlin VHS course search for **"Sprachtest zur
Einbürgerung"** dates about every 30 min (random 20–40 min gaps, only 07:00–20:00 Europe/Berlin) and
posts to the operator's Telegram group when a new date appears or a booked-out date gets free places.
It is **not an agent**: no Claude, no `agents/` entry, no CI. It is deployed to the VM by hand over SSH.

## Feasibility findings (Claude in Chrome, 2026-11-26)

- `https://www.vhsit.berlin.de/VHSKURSE/BusinessPages/CourseSearch.aspx` is ASP.NET WebForms with no
  captcha and no login.
- The search is a chain of form postbacks, replayable with plain HTTP (verified with `fetch`):
  GET search → POST `lbtnTab2` (Erweitert) → POST keyword `2018` ("Sprachtest") + `btnAdd` → POST
  `btnSearch` → `CourseList.aspx` → POST the `arrow_right.gif` image button for each next page.
- The results are server-rendered `tr.DataGridItem` / `tr.DataGridAlternatingItem` rows with
  `DataGridItem{District,CourseNumber,CourseTitle,CourseBegin,Places,Booking}` cells. There were
  14 hits on 2 pages, 13 of them titled "Sprachtest zur Einbürgerung…" and all `belegt`.
- The VM reaches the site (HTTP 200). The devcontainer needed an allowlist entry.
- Decision: `requests` + BeautifulSoup rather than Playwright. Same result, a much smaller image,
  and it is testable in the devcontainer without opening the Playwright CDN or Debian mirrors.

## Design

- `side-projects/vhs-sprachtest-watcher/`: package `watcher` (`vhs.py` scrape, `state.py` diff,
  `notify.py` Telethon, `main.py` loop and CLI), tests, Dockerfile, compose, env template, README.
- Telegram follows the existing VM pattern (`bb-sdk-agent-prod`): `TELEGRAM_API_ID` and
  `TELEGRAM_API_HASH` in a gitignored env file, plus a Telethon `.session` created by a one-time
  interactive login (run in the container), bind-mounted under `./data`.
- The state is `data/state.json`. The first run records a baseline and sends one "watcher started"
  message. After that it alerts only on new course numbers or a `belegt` → free-places change.

## Acceptance

1. `uv run pytest -q` and `ruff check` are green. A live `check --dry-run` against the site works
   from the devcontainer.
2. The image builds and runs on the VM under `/app/vhs-sprachtest-watcher`, and the operator gets
   the login and keys guide.
3. One real Telegram delivery is confirmed after the operator logs in.
