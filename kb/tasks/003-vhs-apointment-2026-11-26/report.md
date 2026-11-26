# 003 — vhs-apointment

**Date:** 2026-11-26

## Task

The operator needs a "Sprachtest zur Einbürgerung" appointment at a Berlin VHS. New dates appear at
random times, so they asked for a small dockerised Python watcher that checks the course search
regularly (only in daytime, with random gaps) and posts to their Telegram group when dates appear or
places free up. They wanted it as a standalone side project, not a factory agent, deployed by hand
over SSH.

## What was done

- [side-projects/README.md](../../../side-projects/README.md): the new `side-projects/` root. It
  says what belongs there and lists its conventions (browser-like scraper headers, Telethon user
  session for Telegram).
- [side-projects/vhs-sprachtest-watcher/](../../../side-projects/vhs-sprachtest-watcher/):
  - `watcher/vhs.py` replays the ASP.NET postback chain (Erweitert tab → keyword `2018` → Suchen →
    every result page) and submits the form the way a browser does.
  - `state.py` diffs against `data/state.json`.
  - `notify.py` sends through Telethon.
  - `main.py` runs the 07:00–20:00 Berlin loop with random 20–40 min gaps. Failures, recovery and
    crashes are reported to Telegram.
  - Also: the Dockerfile, compose file, env template, 9 tests and the README (deploy and login guide).
- [.devcontainer/init-firewall.sh](../../../.devcontainer/init-firewall.sh) allowlists
  `www.vhsit.berlin.de`. [CLAUDE.md](../../../CLAUDE.md),
  [security-strategy.md](../../../.agentic/docs/security-strategy.md) and
  [overview.md](../../../kb/architecture/overview.md) now mention the host and `side-projects/`.

## Result

The watcher is deployed to `/app/vhs-sprachtest-watcher` on the VM (`pulse`) and runs
`unless-stopped`, with journald tag `vhs-sprachtest-watcher`.

Verified:

- A live dry run from the devcontainer and in the VM container returned 13 Einbürgerung dates
  across 2 result pages, all `belegt`. This matches the browser.
- The operator completed the Telethon login, and the test message was delivered to the group.
- The container logs its next check inside the window.
- pytest (9), ruff, pyright, hadolint, trivy config, yamllint, semgrep and gitleaks are clean, per
  `/task-review`.

## Comment

- **`requests` instead of Playwright.** The devcontainer has no Docker and can't reach the
  Playwright CDN. The postbacks replay cleanly over plain HTTP, which gives a much smaller image and
  local testability.
- **A Telethon user session instead of a bot.** This is the operator's choice, and it matches the
  existing `bb-sdk-agent` stacks.
- **Deployed by hand.** There's no CI by design; updates are copied over SSH, then
  `docker compose build && up -d`.

## Follow-ups

- Two failures can't be sent to Telegram: an invalid Telegram session and missing env values at
  startup. They only show in journald.
