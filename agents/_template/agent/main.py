"""Entrypoint: `python -m agent.main`.

TEMPLATE: replace :func:`iter_requests` with this agent's real trigger — polling a queue, reading
a Telegram chat, serving HTTP, or a cron-shaped single pass. Everything below it is generic.

Logging goes to stdout only. The compose file sends stdout to the host journald with a stable tag,
which is what makes a run's decision trace survive the container being recreated on the next deploy.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import AsyncIterator

from agent.config import AgentConfig, AgentConfigError
from agent.context import RunContext
from agent.loop import run_once

logger = logging.getLogger("agent")


def configure_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


async def iter_requests() -> AsyncIterator[tuple[str, str]]:
    """Yield ``(run_id, prompt)`` pairs. TEMPLATE: this is the agent's trigger."""
    yield "demo-1", "Use the echo tool to echo 'wiring works', then report what happened."


async def main() -> int:
    configure_logging()
    try:
        cfg = AgentConfig.load()
    except AgentConfigError as exc:
        logger.error("startup aborted: %s", exc)
        return 1

    if os.environ.get("ANTHROPIC_API_KEY"):
        # Left set, it takes precedence over CLAUDE_CODE_OAUTH_TOKEN and silently switches the
        # agent from subscription billing to per-token API billing. Refuse rather than surprise.
        logger.error("ANTHROPIC_API_KEY is set; this agent runs on subscription auth only. Unset it.")
        return 1
    if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        logger.error("CLAUDE_CODE_OAUTH_TOKEN is not set; run `claude setup-token` and add it to .env.")
        return 1

    logger.info("agent starting: model=%s allow_writes=%s", cfg.model, cfg.allow_writes)
    async for run_id, prompt in iter_requests():
        result = await run_once(prompt, RunContext(run_id=run_id), cfg)
        logger.info("run %s finished: %s", run_id, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
