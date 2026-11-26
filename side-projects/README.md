# side-projects

Small, standalone tools that are **not** factory agents: no Claude Agent SDK, no `agents/` entry,
no CI caller. Each tool is one self-contained folder with its own `pyproject.toml` + `uv.lock`,
`Dockerfile`, `docker-compose.yml`, and a `README.md` that is its only documentation. They are
deployed by hand over SSH to `/app/<name>` on the runtime VM.

The repo-wide rules still apply: no committed secrets (only `*.env.template` scaffolds), never
open a `.env*` file, and code goes through `/task-review` before commit.

## Conventions

- **Scrapers send ordinary browser headers** (a current Chrome User-Agent, `Accept`,
  `Accept-Language`, `Referer`), not a tool-identifying User-Agent. Keep the request volume modest
  (randomised, daytime-only schedules).
- **Telegram notifications default to a Telethon user session**: `TELEGRAM_API_ID` and
  `TELEGRAM_API_HASH` in `.env`, an interactive `login` command, and the session file in a
  bind-mounted `data/` owned by uid 10001. This matches the existing VM stacks. Use a bot token only
  if the operator asks for one.
- **Errors are never silent.** Every failure reaches the notification channel: alert on the first
  failure, remind while it keeps failing, and announce recovery. A top-level crash is reported (rate
  limited) and then re-raised so Docker restarts the container. Document any failure that cannot
  reach the channel (for example an invalid Telegram session) in the project's README.

## Projects

| Project | What it does |
| --- | --- |
| [vhs-sprachtest-watcher](vhs-sprachtest-watcher/) | Alerts Telegram when Berlin VHS "Sprachtest zur Einbürgerung" dates appear or free up |
