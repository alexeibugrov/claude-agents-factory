# Plan addendum: offer → reply → proposal flow, and Docker-in-Docker (2026-10-23)

Two operator requests on the `feat/upwork-agent` branch, after the search tuning. The main
[plan.md](plan.md) stays the record of the original design. This file records what changes.

## A. Docker-in-Docker in the devcontainer

Goal: `docker build` and `docker compose up` for an agent from inside the devcontainer, so
"build and test green" can be proven before deploy (CLAUDE.md) without the host.

Operator decision: real Docker-in-Docker, not the host socket.

- **Daemon:** Docker CE installed in [.devcontainer/Dockerfile](../../../.devcontainer/Dockerfile)
  from Docker's apt repo, with pinned versions. `node` is in the `docker` group.
- **Privileges:** `--privileged` replaces `--cap-add=NET_ADMIN/NET_RAW`, because an inner dockerd
  needs it. `/var/lib/docker` is a named volume per task container, since overlay on overlay
  does not work and the volume also keeps the build cache across rebuilds.
- **Start order:** `init-firewall.sh` flushes every iptables chain, which would wipe dockerd's
  own chains. So the script stops dockerd if it is running, sets the rules, then starts dockerd
  itself. A re-run is safe.
- **Inner containers stay behind the allowlist.** Their traffic is forwarded, not output, so the
  script writes the egress filter into `DOCKER-USER`, the chain Docker evaluates first and leaves
  alone. It allows established traffic, DNS, traffic between containers, and the `allowed-domains`
  ipset. It rejects everything else.
- **New allowlist entries,** checked to resolve on 2026-10-23:
  - `registry-1.docker.io`, `auth.docker.io` and `production.cloudflare.docker.com`, for Docker
    Hub pulls (`python:3.12-slim`, `postgres:16.15`);
  - `deb.debian.org`, for the agent Dockerfile's `apt-get`.
- **Harness:** `Bash(docker:*)` stays in `ask`. Membership of the `docker` group is root inside
  the devcontainer. A privileged or host-network container could rewrite the firewall, so the
  per-command prompt is the gate. Recorded in
  [security-strategy.md](../../../.agentic/docs/security-strategy.md).

The container must be rebuilt to take effect.

## B. upwork-scout: offers to Telegram, a proposal on request

Operator decisions:

- **Where:** a private group. A separate agent Telegram account posts, as in `bb-trade-agent`'s
  `info_agent`.
- **Offers:** after the code prefilters, every job is posted as **one message per offer**.
- **Trigger:** a **reply** to an offer message, from any member of the group, that contains a
  configured trigger word or sign. The agent then writes a proposal and replies in the same chat
  with plain text: the vacancy link and the proposal.
- **Screening is parked.** The code stays, behind `settings.pipeline.screening_enabled: false`.
  When it is enabled, only suitable jobs are offered, with their score.

Flow (pipeline statuses):

```text
cycle (every 30 min):  scrape → ingest → prefilter ─┬─ screening off: pending ──────────┐
                                                    └─ screening on:  pending → suitable ┤
                                                                     OFFER (one message) ┘ → offered
poller (every poll_interval_s):  new messages in the group after the stored cursor
   reply to an offer + trigger token, not our own message → requested
   writer run → proposal stored → plain-text reply (link + proposal) → delivered
```

- **Detection is polling, not update events.** A cursor (the last message id read) is stored in
  Postgres. Every `poll_interval_s` the agent reads the messages after it. Nothing is missed
  across a disconnect, a restart or a deploy, and there is no listener that can die silently.
- **Matching:** the message must reply to an offer the agent posted (`offers.message_id`), must
  not be from the agent itself, and must contain a token from `settings.telegram.triggers`
  (case-insensitive and whole token, default `["+", "go"]`). A trigger on a job that is already
  requested, being drafted or delivered gets a short reply instead of a second draft.
- **Writes:** posting offers and replies is gated by `allow_writes`, as before. With writes off,
  offers are suppressed and logged, and the poller does not run.
- **Concurrency:** the cycle and the poller run as two asyncio tasks, each with its own DB
  connection. They share one Telethon client.

Schema (migration 003): an `offers` table (job_id, chat_id, message_id, posted_at), a
`telegram_cursor` table, nullable `proposals.screening_id`, and request columns on proposals
(requested_by, request_message_id).

Validation:

- the existing tests are updated, and new ones cover offers once per job, the suppressed gate,
  trigger matching, own-message and non-reply rejection, a repeat trigger, a writer failure, and
  the cursor;
- `uv run pytest -q` and ruff pass;
- after the rebuild: `docker build` of the agent, and `docker compose` with a local db.
