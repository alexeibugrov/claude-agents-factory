"""Entrypoint: `python -m agent.main` (long-lived scheduler) or `python -m agent.main --once`.

Two in-process loops. Every ``settings.schedule.interval_minutes`` one pipeline cycle runs
(scrape → ingest → prefilter → [screen] → offer). Ticks are fixed-rate from process start; a cycle
that overruns starts the next one immediately and never concurrently. With ``allow_writes`` on, a
second loop reads the Telegram group for trigger replies and answers them with proposals. It wakes
on a Telegram reply event, or every ``telegram.poll_interval_s`` as a safety net when events stop.
Each loop has its own DB connection; they share the Telegram client. On SIGTERM the current cycle
and poll finish, then the process exits.

Logging goes to stdout only. The compose file sends stdout to the host journald with a stable tag,
which is what makes a run's decision trace survive the container being recreated on the next deploy.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import time

from agent import db, store
from agent.config import AgentConfig, AgentConfigError
from agent.loop import run_once
from agent.pipeline import Deps, cycle, poll
from agent.telegram import TelethonChat

logger = logging.getLogger("agent")


def configure_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    # httpx logs every request URL at INFO; keep the Apify client's transport quiet.
    for noisy in ("httpx", "httpcore", "telethon"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def startup_errors(cfg: AgentConfig) -> list[str]:
    """Refuse to run with missing or dangerous credentials. Checks presence only, never values."""
    errors = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        # Left set, it takes precedence over CLAUDE_CODE_OAUTH_TOKEN and silently switches the
        # agent from subscription billing to per-token API billing. Refuse rather than surprise.
        errors.append("ANTHROPIC_API_KEY is set; this agent runs on subscription auth only. Unset it.")
    if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        errors.append("CLAUDE_CODE_OAUTH_TOKEN is not set; run `claude setup-token` and add it to .env.")
    if not os.environ.get("APIFY_TOKEN"):
        errors.append("APIFY_TOKEN is not set.")
    if not (os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_PASSWORD")):
        errors.append("neither DATABASE_URL nor POSTGRES_PASSWORD is set.")
    if cfg.allow_writes:
        if not (os.environ.get("TELEGRAM_API_ID") and os.environ.get("TELEGRAM_API_HASH")):
            errors.append("allow_writes is true but TELEGRAM_API_ID / TELEGRAM_API_HASH are not set.")
        if not os.path.isfile(f"{cfg.telegram.session_path}.session"):
            errors.append(
                f"allow_writes is true but no Telegram session at {cfg.telegram.session_path}.session;"
                " run python -m agent.telegram_login"
            )
    return errors


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent.main")
    parser.add_argument("--once", action="store_true", help="run a single cycle and exit")
    args = parser.parse_args(argv)
    once = args.once or os.environ.get("RUN_ONCE") == "1"

    configure_logging()
    try:
        cfg = AgentConfig.load()
    except AgentConfigError as exc:
        logger.error("startup aborted: %s", exc)
        return 1
    errors = startup_errors(cfg)
    for error in errors:
        logger.error("startup aborted: %s", error)
    if errors:
        return 1

    from apify_client import ApifyClient

    chat = await TelethonChat(cfg.telegram).start() if cfg.allow_writes else None
    deps = Deps(apify_client=ApifyClient(os.environ["APIFY_TOKEN"]), run_once=run_once, chat=chat)
    conn = await db.connect(db.conninfo(cfg.db))
    applied = await db.migrate(conn)
    await store.reset_in_flight(conn)
    logger.info(
        "agent starting: screening=%s writer=%s searches=%s interval=%smin allow_writes=%s migrations_applied=%s",
        f"{cfg.screener.model} {cfg.screener.prompt_ref}" if cfg.pipeline.screening_enabled else "off",
        f"{cfg.writer.model} {cfg.writer.prompt_ref}",
        [s.name for s in cfg.apify.searches],
        cfg.interval_minutes,
        cfg.allow_writes,
        applied,
    )

    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopping.set)

    try:
        tasks = [_cycle_loop(conn, cfg, deps, stopping, once)]
        if chat is not None and not once:
            reply_seen = asyncio.Event()
            chat.on_reply(reply_seen.set)
            tasks.append(_poll_loop(cfg, deps, stopping, reply_seen))
        await asyncio.gather(*tasks)
    finally:
        await conn.close()
        if chat is not None:
            await chat.close()
    logger.info("agent stopped")
    return 0


async def _sleep_or_stop(stopping: asyncio.Event, delay: float) -> None:
    try:
        await asyncio.wait_for(stopping.wait(), timeout=delay)
    except TimeoutError:
        pass


async def _cycle_loop(conn: db.Conn, cfg: AgentConfig, deps: Deps, stopping: asyncio.Event, once: bool) -> None:
    interval = cfg.interval_minutes * 60
    next_tick = time.monotonic()
    while not stopping.is_set():
        try:
            await cycle(conn, cfg, deps)
        except Exception as exc:  # noqa: BLE001 — one bad cycle must not kill the scheduler.
            logger.exception("AGENT ALERT cycle crashed: %s", exc)
            if conn.closed:
                conn = await db.connect(db.conninfo(cfg.db))
        if once:
            stopping.set()
            break
        next_tick += interval
        delay = max(0.0, next_tick - time.monotonic())
        if delay == 0.0:
            next_tick = time.monotonic()  # overran: start now, and re-anchor the schedule
        await _sleep_or_stop(stopping, delay)


async def _wake_or_stop(stopping: asyncio.Event, wake: asyncio.Event, delay: float) -> None:
    waiters = [asyncio.create_task(stopping.wait()), asyncio.create_task(wake.wait())]
    try:
        await asyncio.wait(waiters, timeout=delay, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiter in waiters:
            waiter.cancel()


async def _poll_loop(cfg: AgentConfig, deps: Deps, stopping: asyncio.Event, reply_seen: asyncio.Event) -> None:
    conn = await db.connect(db.conninfo(cfg.db))
    try:
        while not stopping.is_set():
            # Cleared before the poll: a reply that lands while it runs triggers the next one at once.
            reply_seen.clear()
            try:
                await poll(conn, cfg, deps)
            except Exception as exc:  # noqa: BLE001 — one bad poll must not stop the replies.
                logger.warning("AGENT ALERT telegram poll failed: %s: %s", type(exc).__name__, exc)
                if conn.closed:
                    conn = await db.connect(db.conninfo(cfg.db))
            await _wake_or_stop(stopping, reply_seen, cfg.telegram.poll_interval_s)
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
