"""All database reads and writes: ingest with dedup, the pipeline ledger, and the outbox.

Dedup (plan D3) happens here, before any agent call: ``INSERT INTO jobs … ON CONFLICT (job_id) DO
NOTHING RETURNING job_id``. Only a returned row — the job's first-ever sighting — creates its
``pipeline`` row, and agents only ever read from ``pipeline``. Everything else (UPDATED or
REAPPEARED records, a NEW record for a known id, the same job from another search) refreshes the
latest state, adds a version, and never re-queues the job.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, LiteralString, cast

from psycopg.types.json import Jsonb

from agent.config import PipelineConfig
from agent.db import Conn
from agent.prefilter import prefilter_reason
from agent.scrape import ScrapeResult

# actor field -> jobs column. raw keeps the full record verbatim regardless.
_FIELD_MAP = {
    "url": "url",
    "title": "title",
    "description": "description",
    "descriptionMarkdown": "description_markdown",
    "jobType": "job_type",
    "experienceLevel": "experience_level",
    "budgetAmount": "budget_amount",
    "budgetCurrency": "budget_currency",
    "hourlyBudgetMin": "hourly_budget_min",
    "hourlyBudgetMax": "hourly_budget_max",
    "weeklyRetainerBudget": "weekly_retainer_budget",
    "salaryType": "salary_type",
    "salaryMin": "salary_min",
    "salaryMax": "salary_max",
    "salaryCurrency": "salary_currency",
    "engagementType": "engagement_type",
    "engagementDuration": "engagement_duration",
    "engagementDurationWeeks": "engagement_duration_weeks",
    "publishTime": "published_at",
    "createTime": "created_at_upwork",
    "totalApplicants": "total_applicants",
    "personsToHire": "persons_to_hire",
    "enterpriseJob": "enterprise_job",
    "premium": "premium",
    "customJobScore": "custom_job_score",
    "clientCountry": "client_country",
    "clientCountryCode": "client_country_code",
    "clientTotalSpent": "client_total_spent",
    "clientSpentCurrency": "client_spent_currency",
    "clientPaymentVerified": "client_payment_verified",
    "clientRating": "client_rating",
    "clientReviewCount": "client_review_count",
    "clientHasFinancialPrivacy": "client_has_financial_privacy",
    "isRepost": "is_repost",
    "repostOfId": "repost_of_id",
    "repostDetectedAt": "repost_detected_at",
    "contactName": "contact_name",
    "contactEmail": "contact_email",
    "contactPhone": "contact_phone",
    "firstSeenAt": "actor_first_seen_at",
    "lastSeenAt": "actor_last_seen_at",
    "sourcingTimestamp": "sourcing_timestamp",
    "scrapedAt": "scraped_at",
    "source": "source",
    "contentHash": "content_hash",
}
_ARRAY_FIELDS = {
    "skills": "skills",
    "extractedEmails": "extracted_emails",
    "extractedPhones": "extracted_phones",
    "extractedUrls": "extracted_urls",
}
_TS_COLUMNS = {
    "published_at",
    "created_at_upwork",
    "repost_detected_at",
    "actor_first_seen_at",
    "actor_last_seen_at",
    "sourcing_timestamp",
    "scraped_at",
}

_JOB_COLUMNS = [col for col in _FIELD_MAP.values()] + list(_ARRAY_FIELDS.values()) + ["social_profiles", "raw"]


def _ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def map_record(record: dict[str, Any]) -> dict[str, Any]:
    """Actor record -> jobs columns (without job_id). Missing optional fields become null."""
    row: dict[str, Any] = {}
    for src, col in _FIELD_MAP.items():
        value = record.get(src)
        row[col] = _ts(value) if col in _TS_COLUMNS else value
    for src, col in _ARRAY_FIELDS.items():
        row[col] = [str(v) for v in (record.get(src) or [])]
    social = record.get("socialProfiles")
    row["social_profiles"] = Jsonb(social) if social else None
    row["raw"] = Jsonb(record)
    row["title"] = row["title"] or "(untitled)"
    row["content_hash"] = row["content_hash"] or ""
    return row


async def start_scrape_run(conn: Conn, search_name: str, cycle_started_at: datetime, run_input: dict[str, Any]) -> int:
    cur = await conn.execute(
        "INSERT INTO scrape_runs (status, search_name, cycle_started_at, run_input)"
        " VALUES ('running', %s, %s, %s) RETURNING id",
        (search_name, cycle_started_at, Jsonb(run_input)),
    )
    row = await cur.fetchone()
    assert row is not None
    return int(row["id"])


async def finish_scrape_run(conn: Conn, run_id: int, result: ScrapeResult, counts: dict[str, int]) -> None:
    await conn.execute(
        "UPDATE scrape_runs SET finished_at = now(), status = %s, apify_run_id = %s, apify_dataset_id = %s,"
        " items_total = %s, items_new = %s, items_known = %s, items_invalid = %s, apify_cost_usd = %s, error = %s,"
        " upwork_total = %s WHERE id = %s",
        (
            result.status,
            result.apify_run_id,
            result.apify_dataset_id,
            len(result.items),
            counts.get("new", 0),
            counts.get("known", 0),
            counts.get("invalid", 0),
            result.cost_usd,
            result.error,
            result.upwork_total,
            run_id,
        ),
    )


def _initial_status(
    row: dict[str, Any], repost_known: bool, cfg: PipelineConfig, now: datetime
) -> tuple[str, str | None]:
    if repost_known and cfg.skip_known_reposts:
        return "skipped_repost", f"repost of known job {row.get('repost_of_id')}"
    published = row.get("published_at")
    if cfg.max_age_hours_to_screen is not None and published is not None:
        if now - published > timedelta(hours=cfg.max_age_hours_to_screen):
            return "skipped_stale", f"published {published.isoformat()} > {cfg.max_age_hours_to_screen}h ago"
    return "pending", None


async def ingest(
    conn: Conn,
    record: dict[str, Any],
    *,
    run_id: int,
    search_name: str,
    cfg: PipelineConfig,
    now: datetime | None = None,
) -> str:
    """Store one actor record. Returns "new" (first sighting, queued), "known", or "invalid"."""
    job_id = record.get("jobId")
    if not job_id or not record.get("url"):
        return "invalid"
    job_id = str(job_id)
    now = now or datetime.now(timezone.utc)
    row = map_record(record)
    cols = ["job_id", *_JOB_COLUMNS, "first_run_id"]
    values = [job_id, *(row[c] for c in _JOB_COLUMNS), run_id]

    async with conn.transaction():
        # Column names come from the module's own constants, never from input.
        insert = f"INSERT INTO jobs ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"
        cur = await conn.execute(
            cast(LiteralString, insert + " ON CONFLICT (job_id) DO NOTHING RETURNING job_id"), values
        )
        is_new = await cur.fetchone() is not None
        if not is_new:
            updates = ", ".join(f"{c} = %s" for c in _JOB_COLUMNS)
            update = f"UPDATE jobs SET {updates}, last_seen_at = now(), seen_count = seen_count + 1 WHERE job_id = %s"
            await conn.execute(cast(LiteralString, update), [*(row[c] for c in _JOB_COLUMNS), job_id])
        await conn.execute(
            "INSERT INTO job_versions (job_id, content_hash, change_type, run_id, total_applicants, raw)"
            " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (job_id, row["content_hash"], record.get("changeType"), run_id, row["total_applicants"], row["raw"]),
        )
        await conn.execute(
            "INSERT INTO job_searches (job_id, search_name, first_run_id) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (job_id, search_name, run_id),
        )
        if is_new:
            repost_known = False
            if row.get("is_repost") and row.get("repost_of_id"):
                cur = await conn.execute("SELECT 1 FROM jobs WHERE job_id = %s", (str(row["repost_of_id"]),))
                repost_known = await cur.fetchone() is not None
            status, reason = _initial_status(row, repost_known, cfg, now)
            await conn.execute(
                "INSERT INTO pipeline (job_id, status, reason) VALUES (%s, %s, %s)", (job_id, status, reason)
            )
    return "new" if is_new else "known"


async def apply_prefilters(conn: Conn, rules: dict[str, Any]) -> int:
    """Mark pending jobs that fail a configured rule as prefiltered. Returns how many."""
    if not any(v is not None for v in rules.values()):
        return 0
    cur = await conn.execute("SELECT j.* FROM jobs j JOIN pipeline p USING (job_id) WHERE p.status = 'pending'")
    count = 0
    for job in await cur.fetchall():
        reason = prefilter_reason(job, rules)
        if reason:
            await set_status(conn, job["job_id"], "prefiltered", reason)
            count += 1
    return count


async def set_status(conn: Conn, job_id: str, status: str, reason: str | None = None) -> None:
    await conn.execute(
        "UPDATE pipeline SET status = %s, reason = %s, updated_at = now() WHERE job_id = %s",
        (status, reason, job_id),
    )


async def claim(conn: Conn, from_status: str, to_status: str, limit: int, max_attempts: int) -> list[dict[str, Any]]:
    """Atomically move up to ``limit`` jobs between statuses (oldest first) and return them."""
    if limit <= 0:
        return []
    cur = await conn.execute(
        "WITH picked AS ("
        "  SELECT job_id FROM pipeline WHERE status = %s AND attempts < %s"
        "  ORDER BY created_at LIMIT %s FOR UPDATE SKIP LOCKED)"
        " UPDATE pipeline p SET status = %s, attempts = p.attempts + 1, updated_at = now()"
        " FROM picked WHERE p.job_id = picked.job_id RETURNING p.job_id",
        (from_status, max_attempts, limit, to_status),
    )
    ids = [r["job_id"] for r in await cur.fetchall()]
    if not ids:
        return []
    cur = await conn.execute("SELECT * FROM jobs WHERE job_id = ANY(%s) ORDER BY first_seen_at", (ids,))
    return list(await cur.fetchall())


async def release(
    conn: Conn, job_id: str, back_to: str, error: str, max_attempts: int, exhausted: str = "error"
) -> str:
    """A failed agent run: requeue the job, or move it to ``exhausted`` once attempts run out. Returns the status."""
    cur = await conn.execute(
        "UPDATE pipeline SET status = CASE WHEN attempts >= %s THEN %s ELSE %s END,"
        " reason = %s, updated_at = now() WHERE job_id = %s RETURNING status",
        (max_attempts, exhausted, back_to, error[:1000], job_id),
    )
    row = await cur.fetchone()
    return row["status"] if row else back_to


async def requeue(conn: Conn, job_id: str, back_to: str, error: str) -> None:
    """Requeue without spending an attempt (a rate limit is not the job's fault)."""
    await conn.execute(
        "UPDATE pipeline SET status = %s, attempts = greatest(attempts - 1, 0), reason = %s, updated_at = now()"
        " WHERE job_id = %s",
        (back_to, error[:1000], job_id),
    )


async def reset_in_flight(conn: Conn) -> None:
    """After a crash, in-flight jobs go back to their queue. Safe: the model tools change nothing."""
    await conn.execute("UPDATE pipeline SET status = 'pending', updated_at = now() WHERE status = 'screening'")
    await conn.execute("UPDATE pipeline SET status = 'requested', updated_at = now() WHERE status = 'drafting'")


async def record_screening(
    conn: Conn, job_id: str, *, prompt_sha: str, run: dict[str, Any], verdict: dict[str, Any]
) -> int:
    async with conn.transaction():
        cur = await conn.execute(
            "INSERT INTO screenings (job_id, prompt_sha, model, score, reasons,"
            " cost_usd, num_turns, duration_s) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (job_id, prompt_sha) DO UPDATE SET score = EXCLUDED.score, reasons = EXCLUDED.reasons"
            " RETURNING id",
            (
                job_id,
                prompt_sha,
                run.get("model") or "",
                verdict["score"],
                verdict["reason"],
                run.get("cost_usd"),
                run.get("num_turns"),
                run.get("duration_s"),
            ),
        )
        row = await cur.fetchone()
        assert row is not None
        await set_status(conn, job_id, "screened")
    return int(row["id"])


async def latest_screening(conn: Conn, job_id: str) -> dict[str, Any] | None:
    cur = await conn.execute("SELECT * FROM screenings WHERE job_id = %s ORDER BY created_at DESC LIMIT 1", (job_id,))
    return await cur.fetchone()


async def record_proposal(
    conn: Conn,
    job_id: str,
    *,
    screening_id: int | None,
    prompt_sha: str,
    run: dict[str, Any],
    draft: dict[str, Any],
    request_text: str | None = None,
    revises_id: int | None = None,
) -> None:
    """Store a new version; an earlier one, delivered or revised, is kept."""
    async with conn.transaction():
        await conn.execute(
            "INSERT INTO proposals (job_id, screening_id, prompt_sha, model, body,"
            " cost_usd, num_turns, duration_s, request_text, revises_id)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                job_id,
                screening_id,
                prompt_sha,
                run.get("model") or "",
                draft["proposal"],
                run.get("cost_usd"),
                run.get("num_turns"),
                run.get("duration_s"),
                request_text,
                revises_id,
            ),
        )
        await set_status(conn, job_id, "drafted")


async def offer_queue(conn: Conn, from_status: str, limit: int) -> list[dict[str, Any]]:
    """Jobs ready to be offered, oldest first, with their latest screening's score and reasons if any."""
    cur = await conn.execute(
        "SELECT j.*, s.score, s.reasons FROM pipeline p JOIN jobs j USING (job_id)"
        " LEFT JOIN LATERAL (SELECT score, reasons FROM screenings WHERE job_id = p.job_id"
        "   ORDER BY created_at DESC LIMIT 1) s ON true"
        " WHERE p.status = %s ORDER BY p.created_at LIMIT %s",
        (from_status, limit),
    )
    return list(await cur.fetchall())


async def record_offer(conn: Conn, job_id: str, chat_id: str, message_id: int) -> None:
    async with conn.transaction():
        await conn.execute(
            "INSERT INTO offers (job_id, chat_id, message_id) VALUES (%s, %s, %s)", (job_id, chat_id, message_id)
        )
        await set_status(conn, job_id, "offered")


async def offer_by_message(conn: Conn, chat_id: str, message_id: int) -> dict[str, Any] | None:
    """The offer a group message points at, with the job's pipeline status."""
    cur = await conn.execute(
        "SELECT o.*, p.status FROM offers o JOIN pipeline p USING (job_id) WHERE o.chat_id = %s AND o.message_id = %s",
        (chat_id, message_id),
    )
    return await cur.fetchone()


async def offer_for_job(conn: Conn, job_id: str) -> dict[str, Any] | None:
    cur = await conn.execute("SELECT * FROM offers WHERE job_id = %s", (job_id,))
    return await cur.fetchone()


async def request_proposal(
    conn: Conn,
    job_id: str,
    requested_by: int | None,
    request_message_id: int,
    request_text: str | None = None,
    revise_proposal_id: int | None = None,
) -> bool:
    """Queue the writer for an offered job, or retry one that errored. A request with suggestions
    also writes a new version of a delivered proposal; one with ``revise_proposal_id`` edits that
    proposal instead. False if the job is already in hand or done."""
    if revise_proposal_id is not None:
        statuses = ["delivered", "error"]
    else:
        statuses = ["offered", "error"] + (["delivered"] if request_text else [])
    async with conn.transaction():
        cur = await conn.execute(
            "UPDATE pipeline SET status = 'requested', attempts = 0, reason = NULL, updated_at = now()"
            " WHERE job_id = %s AND status = ANY(%s) RETURNING job_id",
            (job_id, statuses),
        )
        if await cur.fetchone() is None:
            return False
        await conn.execute(
            "UPDATE offers SET requested_by = %s, request_message_id = %s, request_text = %s,"
            " revise_proposal_id = %s, requested_at = now() WHERE job_id = %s",
            (requested_by, request_message_id, request_text, revise_proposal_id, job_id),
        )
    return True


async def proposal_by_message(conn: Conn, chat_id: str, message_id: int) -> dict[str, Any] | None:
    """The delivered proposal a group message points at (any of its parts), with the job's status."""
    cur = await conn.execute(
        "SELECT p.id, p.job_id, pl.status FROM proposals p JOIN pipeline pl USING (job_id)"
        " WHERE p.telegram_chat_id = %s AND %s = ANY(p.telegram_message_ids)",
        (chat_id, message_id),
    )
    return await cur.fetchone()


async def proposal_chain(conn: Conn, proposal_id: int) -> list[dict[str, Any]]:
    """The proposal and every version it revises, oldest first: the new draft, then each revision."""
    cur = await conn.execute(
        "WITH RECURSIVE chain AS ("
        " SELECT id, revises_id, body, request_text, 0 AS depth FROM proposals WHERE id = %s"
        " UNION ALL SELECT p.id, p.revises_id, p.body, p.request_text, c.depth + 1"
        " FROM proposals p JOIN chain c ON p.id = c.revises_id)"
        " SELECT id, body, request_text FROM chain ORDER BY depth DESC",
        (proposal_id,),
    )
    return list(await cur.fetchall())


async def undelivered(conn: Conn, limit: int) -> list[dict[str, Any]]:
    """The outbox: drafted proposals not yet sent, oldest first, with their job and offer."""
    cur = await conn.execute(
        "SELECT p.id AS proposal_id, p.body, p.job_id, o.message_id AS offer_message_id,"
        " o.request_message_id FROM proposals p JOIN pipeline pl ON pl.job_id = p.job_id"
        " JOIN offers o ON o.job_id = p.job_id"
        " WHERE p.delivered_at IS NULL AND pl.status = 'drafted' ORDER BY p.created_at LIMIT %s",
        (limit,),
    )
    rows = list(await cur.fetchall())
    for row in rows:
        jcur = await conn.execute("SELECT * FROM jobs WHERE job_id = %s", (row["job_id"],))
        row["job"] = await jcur.fetchone()
    return rows


async def mark_delivered(conn: Conn, proposal_id: int, job_id: str, chat_id: str, message_ids: list[int]) -> None:
    async with conn.transaction():
        await conn.execute(
            "UPDATE proposals SET delivered_at = now(), telegram_chat_id = %s, telegram_message_ids = %s WHERE id = %s",
            (chat_id, message_ids, proposal_id),
        )
        await set_status(conn, job_id, "delivered")


async def get_cursor(conn: Conn, chat_id: str) -> int | None:
    cur = await conn.execute("SELECT last_message_id FROM telegram_cursor WHERE chat_id = %s", (chat_id,))
    row = await cur.fetchone()
    return int(row["last_message_id"]) if row else None


async def set_cursor(conn: Conn, chat_id: str, message_id: int) -> None:
    await conn.execute(
        "INSERT INTO telegram_cursor (chat_id, last_message_id) VALUES (%s, %s) ON CONFLICT (chat_id)"
        " DO UPDATE SET last_message_id = EXCLUDED.last_message_id, updated_at = now()",
        (chat_id, message_id),
    )
