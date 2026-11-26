# Notes — 003 vhs-apointment

## Queued doc updates (apply at finalize)

- CLAUDE.md § Layout: add `side-projects/` (standalone non-agent tools, deployed by hand over SSH).
- kb/architecture/overview.md: one line pointing at `side-projects/README.md`, if the overview lists top-level dirs.

## Operator decisions

- Telegram identity: the operator's **user account** (Telethon session), not a bot.
- Live testing: **allowlist + rebuild** (`www.vhsit.berlin.de` added to `.devcontainer/init-firewall.sh`)
  rather than testing only on the VM.
- Scraper: `requests` + BeautifulSoup instead of Playwright. The devcontainer has no Docker and
  can't reach the Playwright CDN, and the postbacks replay cleanly over plain HTTP.
- Scraper sends ordinary Chrome headers, not a tool-identifying User-Agent (operator correction).
- Every failure must reach Telegram (first failure, reminders, recovery, rate-limited crash alert)
  (operator request); "errors never silent" added to side-projects conventions.
- Check interval changed to ~30 min (random 20–40 min) (operator request).

## Applied at finalize

- CLAUDE.md layout, kb/architecture/overview.md, CLAUDE.md + security-strategy.md firewall prose.
- Harvested lessons 1 and 3 plus "errors never silent" into side-projects/README.md § Conventions
  (lesson 2, form serialisation, declined by the operator).
