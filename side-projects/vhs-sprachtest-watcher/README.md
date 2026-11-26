# vhs-sprachtest-watcher

Checks the [Berlin VHS course search](https://www.vhsit.berlin.de/VHSKURSE/BusinessPages/CourseSearch.aspx)
for **"Sprachtest zur Einbürgerung"** dates and posts to a Telegram group from your own account when

- a **new date** (new course number) appears, or
- a date that was `belegt` now shows **free places**.

The first run sends one "watcher started" summary and records a baseline. After that it stays quiet
unless something changes.

**Errors are never silent.** A failed check (site down, markup changed, Telegram hiccup) sends
"⚠️ Prüfung fehlgeschlagen" with the last lines of the traceback, a reminder every 6 failed checks
in a row (~3 h), and "✅ wieder OK" once a check succeeds again. If the loop itself crashes, it
sends "💥 abgestürzt" (at most once an hour, so a restart loop can't spam) and exits non-zero so
Docker restarts it. Two cases can only be logged, not sent: a Telegram session that is no longer
valid, and missing env values at startup. Check `journalctl -t vhs-sprachtest-watcher` if the
group goes quiet for a day.

## How it works

- `watcher/vhs.py` replays the search's ASP.NET postbacks with `requests`: Erweitert tab, then
  keyword `Sprachtest` (ID `2018`), then Suchen, then every result page. It keeps only rows whose
  title contains "Einbürgerung".
- `watcher/state.py` diffs the rows against `data/state.json`.
- `watcher/notify.py` sends through a Telethon **user** session (`data/watcher.session`), the same
  pattern the VM's `bb-sdk-agent` stacks use.
- `watcher/main.py` runs the loop. A check happens every 20–40 min (random, ~30 on average), only between 07:00 and
  20:00 Europe/Berlin. Outside those hours it sleeps until 07:00–07:20. You can change this with the
  `WINDOW_*` and `INTERVAL_*` values in `docker-compose.yml`.

## Commands

```bash
python -m watcher check --dry-run   # one live check, print the would-be message, no Telegram, no state
python -m watcher login             # interactive Telegram login + list your groups' IDs
python -m watcher test-message      # one test message to TELEGRAM_CHAT
python -m watcher check             # one real check (sends + saves state)
python -m watcher run               # the loop (container default)
```

Local dev: `uv run pytest -q`, `uv run ruff check .`, `DATA_DIR=./data uv run python -m watcher check --dry-run`.

## Deploy (by hand over SSH, no CI)

The code lives in `/app/vhs-sprachtest-watcher` on the VM. Copy the directory there without
`.venv/` and `data/`, then:

```bash
cd /app/vhs-sprachtest-watcher
cp watcher.env.template .env          # then edit .env: TELEGRAM_API_ID, TELEGRAM_API_HASH
mkdir -p data && chown 10001:10001 data
docker compose build
docker compose run --rm -it watcher python -m watcher login       # phone, code, 2FA → data/watcher.session
#   copy the target group's ID from the printed list into .env as TELEGRAM_CHAT
docker compose run --rm watcher python -m watcher test-message    # confirm delivery
docker compose up -d
journalctl -t vhs-sprachtest-watcher -f                            # or: docker compose logs -f
```

To update, copy the changed files, then run `docker compose build && docker compose up -d`. To reset
the baseline, delete `data/state.json`.

## Notes

- **You must be a member of the target group.** The account in `data/watcher.session` can send as
  you, so keep `data/` root/uid-10001 only.
- If the site's markup changes, checks fail with `ScrapeError` and the warning reaches Telegram.
