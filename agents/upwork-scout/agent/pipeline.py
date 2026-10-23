"""The cycle and the poll.

``cycle`` (every interval): scrape every search → ingest (dedup) → prefilter → [screen] → offer:
one Telegram message per job. Screening is parked unless ``pipeline.screening_enabled``.

``poll`` (woken by a reply event, at least every ``telegram.poll_interval_s``): read the group
after the stored cursor; a reply to an offer that opens with a trigger requests a proposal →
writer run → plain-text reply with the vacancy link and the proposal.

Dependencies are injected (:class:`Deps`) so tests drive a real Postgres with fake Apify, agent and
Telegram stand-ins. Each stage is bounded by config caps; a backlog stays queued and nothing is
dropped. One failing search, run or send never stops the rest.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


from agent import render, store
from agent.db import Conn
from agent.config import AgentConfig, RoleConfig
from agent.context import RunContext
from agent.guards import delivery_allowed
from agent.scrape import ScrapeResult, build_run_input, run_search
from agent.telegram import Chat, FloodWait

logger = logging.getLogger(__name__)

RunOnce = Callable[..., Awaitable[dict]]
SearchRunner = Callable[[Any, Any, Any], Awaitable[ScrapeResult]]


@dataclass
class Deps:
    apify_client: Any
    run_once: RunOnce
    chat: Chat | None = None  # None while allow_writes is false: nothing is sent or read
    run_search: SearchRunner = run_search


@dataclass
class CycleSummary:
    fetched: int = 0
    new: int = 0
    known: int = 0
    invalid: int = 0
    failed_searches: int = 0
    prefiltered: int = 0
    screened: int = 0
    suitable: int = 0
    offered: int = 0
    suppressed: int = 0
    errors: list[str] = field(default_factory=list)

    def line(self) -> str:
        return (
            f"cycle summary: fetched={self.fetched} new={self.new} known={self.known} invalid={self.invalid}"
            f" failed_searches={self.failed_searches} prefiltered={self.prefiltered} screened={self.screened}"
            f" suitable={self.suitable} offered={self.offered} suppressed={self.suppressed}"
        )


@dataclass
class PollSummary:
    read: int = 0
    requested: int = 0
    drafted: int = 0
    delivered: int = 0


def _is_rate_limit(error: str | None) -> bool:
    text = (error or "").lower()
    return "rate limit" in text or "rate_limit" in text or "usage limit" in text


async def _scrape(conn: Conn, cfg: AgentConfig, deps: Deps, summary: CycleSummary) -> None:
    cycle_started = datetime.now(timezone.utc)
    for search in cfg.apify.searches:
        run_id = await store.start_scrape_run(conn, search.name, cycle_started, build_run_input(search))
        result = await deps.run_search(deps.apify_client, cfg.apify, search)
        counts = {"new": 0, "known": 0, "invalid": 0}
        for record in result.items:
            outcome = await store.ingest(conn, record, run_id=run_id, search_name=search.name, cfg=cfg.pipeline)
            counts[outcome] += 1
        await store.finish_scrape_run(conn, run_id, result, counts)
        summary.fetched += len(result.items)
        summary.new += counts["new"]
        summary.known += counts["known"]
        summary.invalid += counts["invalid"]
        if result.status != "succeeded":
            summary.failed_searches += 1
        if counts["invalid"]:
            logger.warning("AGENT ALERT invalid records search=%s count=%d", search.name, counts["invalid"])


async def _agent_run(deps: Deps, role: RoleConfig, job: dict[str, Any], prompt: str, allow_writes: bool):
    ctx = RunContext(run_id=f"{role.name}-{uuid.uuid4().hex[:8]}", job_id=job["job_id"], role=role.name)
    run = await deps.run_once(prompt, ctx, role, allow_writes=allow_writes)
    return ctx, run


async def _screen(conn: Conn, cfg: AgentConfig, deps: Deps, summary: CycleSummary) -> bool:
    """Returns False when the subscription is rate-limited, so later agent stages are skipped."""
    p = cfg.pipeline
    claimed = await store.claim(conn, "pending", "screening", p.max_screen_per_cycle, p.max_attempts)
    for i, job in enumerate(claimed):
        ctx, run = await _agent_run(deps, cfg.screener, job, render.screener_prompt(job), cfg.allow_writes)
        if run["status"] != "COMPLETED" or "suitable" not in ctx.result:
            error = run.get("error") or "screener finished without calling submit_screening"
            logger.warning("AGENT ALERT screening failed job=%s error=%s", job["job_id"], error)
            summary.errors.append(error)
            if _is_rate_limit(run.get("error")):
                # Not the jobs' fault: requeue this one and the rest of the batch, attempts unspent.
                for rest in claimed[i:]:
                    await store.requeue(conn, rest["job_id"], "pending", error)
                return False
            await store.release(conn, job["job_id"], "pending", error, p.max_attempts)
            continue
        await store.record_screening(
            conn, job["job_id"], prompt_sha=cfg.screener.prompt_sha, run=run, verdict=ctx.result
        )
        summary.screened += 1
        summary.suitable += int(ctx.result["suitable"])
        logger.info(
            "screened job=%s suitable=%s score=%s reasons=%s",
            job["job_id"],
            ctx.result["suitable"],
            ctx.result["score"],
            ctx.result["reasons"],
        )
    return True


async def _offer(conn: Conn, cfg: AgentConfig, deps: Deps, summary: CycleSummary) -> None:
    from_status = "suitable" if cfg.pipeline.screening_enabled else "pending"
    queue = await store.offer_queue(conn, from_status, cfg.pipeline.max_offers_per_cycle)
    if not queue:
        return
    if not cfg.allow_writes or deps.chat is None:
        for job in queue:
            delivery_allowed(allow_writes=False, job_id=job["job_id"])
        summary.suppressed += len(queue)
        return
    for job in queue:
        try:
            message_id = await deps.chat.post(render.offer_message(job))
        except FloodWait as exc:
            logger.warning("telegram flood wait; offers resume next cycle: %s", exc)
            return
        except Exception as exc:  # noqa: BLE001 — unsent offers stay queued for the next cycle.
            logger.warning("AGENT ALERT telegram offer failed: %s: %s", type(exc).__name__, exc)
            return
        await store.record_offer(conn, job["job_id"], deps.chat.chat_id, message_id)
        summary.offered += 1


def parse_trigger(text: str, triggers: tuple[str, ...]) -> str | None:
    """The text after a leading trigger ("" for a bare one), or None when the reply is not a request.

    The trigger must be the reply's first token, case-insensitive: "+ Q1: ..." and "Go" fire,
    "google it" and "+1" do not, and a trigger word inside the questions never fires on its own.
    """
    parts = text.strip().split(maxsplit=1)
    if not parts or parts[0].lower() not in triggers:
        return None
    return parts[1].strip() if len(parts) > 1 else ""


async def _read_replies(conn: Conn, cfg: AgentConfig, chat: Chat, summary: PollSummary) -> None:
    cursor = await store.get_cursor(conn, chat.chat_id)
    if cursor is None:
        # First start: begin at the newest message; the group's history is never replayed.
        await store.set_cursor(conn, chat.chat_id, await chat.latest_id())
        return
    messages = await chat.fetch_after(cursor, limit=100)
    for msg in messages:
        summary.read += 1
        if msg.own or msg.reply_to is None:
            continue
        instructions = parse_trigger(msg.text, cfg.telegram.triggers)
        if instructions is None:
            continue
        offer = await store.offer_by_message(conn, chat.chat_id, msg.reply_to)
        if offer is None:
            continue
        if await store.request_proposal(conn, offer["job_id"], msg.sender_id, msg.id, instructions or None):
            logger.info(
                "proposal requested job=%s by=%s message=%s instructions=%d chars",
                offer["job_id"],
                msg.sender_id,
                msg.id,
                len(instructions),
            )
            summary.requested += 1
        elif offer["status"] in ("drafted", "delivered"):
            trigger = cfg.telegram.triggers[0]
            await chat.reply(
                msg.id,
                [
                    f"Already sent above. For a new version, reply {trigger} followed by the questions to answer"
                    " or what to change."
                ],
            )
        else:
            await chat.reply(msg.id, ["Already writing it."])
    if messages:
        await store.set_cursor(conn, chat.chat_id, messages[-1].id)


async def _draft_requested(conn: Conn, cfg: AgentConfig, deps: Deps, chat: Chat, summary: PollSummary) -> None:
    p = cfg.pipeline
    claimed = await store.claim(conn, "requested", "drafting", p.max_draft_per_cycle, p.max_attempts)
    for i, job in enumerate(claimed):
        screening = await store.latest_screening(conn, job["job_id"])
        offer = await store.offer_for_job(conn, job["job_id"])
        prompt = render.writer_prompt(job, screening, (offer or {}).get("request_text"))
        ctx, run = await _agent_run(deps, cfg.writer, job, prompt, cfg.allow_writes)
        if run["status"] != "COMPLETED" or "proposal" not in ctx.result:
            error = run.get("error") or "writer finished without calling submit_proposal"
            logger.warning("AGENT ALERT drafting failed job=%s error=%s", job["job_id"], error)
            if _is_rate_limit(run.get("error")):
                for rest in claimed[i:]:
                    await store.requeue(conn, rest["job_id"], "requested", error)
                return
            if await store.release(conn, job["job_id"], "requested", error, p.max_attempts) == "error":
                offer = await store.offer_for_job(conn, job["job_id"])
                if offer:
                    note = f"Could not write a proposal: {error[:300]}. Reply again with a trigger to retry."
                    await chat.reply(offer["request_message_id"] or offer["message_id"], [note])
            continue
        await store.record_proposal(
            conn,
            job["job_id"],
            screening_id=screening["id"] if screening else None,
            prompt_sha=cfg.writer.prompt_sha,
            run=run,
            draft=ctx.result,
        )
        summary.drafted += 1


async def _deliver(conn: Conn, cfg: AgentConfig, chat: Chat, summary: PollSummary) -> None:
    for item in await store.undelivered(conn, limit=20):
        if not delivery_allowed(allow_writes=cfg.allow_writes, job_id=item["job_id"]):
            return
        proposal = {"proposal": item["body"], "notes_for_operator": item["notes_for_operator"]}
        try:
            ids = await chat.reply(
                item["request_message_id"] or item["offer_message_id"], render.proposal_messages(item["job"], proposal)
            )
        except FloodWait as exc:
            logger.warning("telegram flood wait; delivery resumes next poll: %s", exc)
            return
        await store.mark_delivered(conn, item["proposal_id"], item["job_id"], chat.chat_id, ids)
        summary.delivered += 1


async def poll(conn: Conn, cfg: AgentConfig, deps: Deps) -> PollSummary:
    """One poll: read trigger replies, draft what was requested, deliver the drafts."""
    summary = PollSummary()
    if deps.chat is None or not cfg.allow_writes:
        return summary
    await _read_replies(conn, cfg, deps.chat, summary)
    await _draft_requested(conn, cfg, deps, deps.chat, summary)
    await _deliver(conn, cfg, deps.chat, summary)
    if summary.requested or summary.drafted or summary.delivered:
        logger.info(
            "poll summary: read=%d requested=%d drafted=%d delivered=%d",
            summary.read,
            summary.requested,
            summary.drafted,
            summary.delivered,
        )
    return summary


async def cycle(conn: Conn, cfg: AgentConfig, deps: Deps) -> CycleSummary:
    summary = CycleSummary()
    await _scrape(conn, cfg, deps, summary)
    summary.prefiltered = await store.apply_prefilters(conn, cfg.prefilter)
    if cfg.pipeline.screening_enabled:
        await _screen(conn, cfg, deps, summary)
    await _offer(conn, cfg, deps, summary)
    logger.info(summary.line())
    return summary
