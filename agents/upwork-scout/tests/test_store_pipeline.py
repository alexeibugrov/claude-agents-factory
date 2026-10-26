"""Dedup, the pipeline ledger and full cycles, against a real Postgres (see conftest)."""

import copy
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from agent import db, store
from agent.config import AgentConfig, PipelineConfig
from agent.pipeline import Deps, cycle, parse_trigger, poll
from agent.scrape import ScrapeResult
from agent.telegram import Incoming

SAMPLES = json.loads((Path(__file__).parent / "fixtures" / "sample_jobs.json").read_text())
NO_STALE = PipelineConfig(max_age_hours_to_screen=None)


def _rec(i=0, **over):
    record = copy.deepcopy(SAMPLES[i])
    record.update(over)
    return record


async def _count(conn, sql, *params):
    cur = await conn.execute(sql, params)
    row = await cur.fetchone()
    return list(row.values())[0]


async def _run_id(conn, search="one"):
    return await store.start_scrape_run(conn, search, datetime.now(timezone.utc), {"query": "x"})


# --- ingest / dedup ------------------------------------------------------------------------


async def test_migrations_are_idempotent(conn):
    assert await db.migrate(conn) == []


async def test_same_job_twice_in_one_batch_is_queued_once(conn):
    run = await _run_id(conn)
    first = await store.ingest(conn, _rec(), run_id=run, search_name="one", cfg=NO_STALE)
    second = await store.ingest(conn, _rec(), run_id=run, search_name="one", cfg=NO_STALE)
    assert (first, second) == ("new", "known")
    assert await _count(conn, "SELECT count(*) FROM pipeline") == 1
    assert await _count(conn, "SELECT seen_count FROM jobs") == 2


async def test_new_flag_for_known_id_takes_the_known_path(conn):
    run = await _run_id(conn)
    await store.ingest(conn, _rec(changeType="NEW"), run_id=run, search_name="one", cfg=NO_STALE)
    await store.set_status(conn, SAMPLES[0]["jobId"], "unsuitable")
    again = await store.ingest(conn, _rec(changeType="NEW"), run_id=run, search_name="one", cfg=NO_STALE)
    assert again == "known"
    assert await _count(conn, "SELECT status FROM pipeline") == "unsuitable"


async def test_update_adds_a_version_but_never_requeues(conn):
    run = await _run_id(conn)
    await store.ingest(conn, _rec(), run_id=run, search_name="one", cfg=NO_STALE)
    changed = _rec(changeType="UPDATED", contentHash="f" * 64, totalApplicants=150)
    await store.ingest(conn, changed, run_id=run, search_name="one", cfg=NO_STALE)
    assert await _count(conn, "SELECT count(*) FROM job_versions") == 2
    assert await _count(conn, "SELECT total_applicants FROM jobs") == 150
    assert await _count(conn, "SELECT count(*) FROM pipeline") == 1


async def test_same_job_from_two_searches_is_one_job_two_search_rows(conn):
    run_a, run_b = await _run_id(conn, "a"), await _run_id(conn, "b")
    await store.ingest(conn, _rec(), run_id=run_a, search_name="a", cfg=NO_STALE)
    assert await store.ingest(conn, _rec(), run_id=run_b, search_name="b", cfg=NO_STALE) == "known"
    assert await _count(conn, "SELECT count(*) FROM pipeline") == 1
    assert await _count(conn, "SELECT count(*) FROM job_searches") == 2


async def test_record_without_job_id_is_invalid(conn):
    run = await _run_id(conn)
    assert await store.ingest(conn, _rec(jobId=None), run_id=run, search_name="one", cfg=NO_STALE) == "invalid"
    assert await _count(conn, "SELECT count(*) FROM jobs") == 0


async def test_typed_columns_and_raw_are_stored(conn):
    run = await _run_id(conn)
    await store.ingest(conn, _rec(contactEmail="a@b.c"), run_id=run, search_name="one", cfg=NO_STALE)
    cur = await conn.execute("SELECT * FROM jobs")
    job = await cur.fetchone()
    assert job["published_at"].tzinfo is not None
    assert job["skills"] == SAMPLES[0]["skills"]
    assert job["contact_email"] == "a@b.c"
    assert job["raw"]["jobId"] == SAMPLES[0]["jobId"]


async def test_repost_of_known_job_is_stored_not_screened(conn):
    run = await _run_id(conn)
    await store.ingest(conn, _rec(0), run_id=run, search_name="one", cfg=NO_STALE)
    repost = _rec(1, isRepost=True, repostOfId=SAMPLES[0]["jobId"])
    await store.ingest(conn, repost, run_id=run, search_name="one", cfg=NO_STALE)
    status = await _count(conn, "SELECT status FROM pipeline WHERE job_id = %s", SAMPLES[1]["jobId"])
    assert status == "skipped_repost"


async def test_stale_job_is_stored_not_screened(conn):
    run = await _run_id(conn)
    published = datetime.fromisoformat(SAMPLES[0]["publishTime"])
    cfg = PipelineConfig(max_age_hours_to_screen=6)
    await store.ingest(conn, _rec(), run_id=run, search_name="one", cfg=cfg, now=published + timedelta(hours=7))
    assert await _count(conn, "SELECT status FROM pipeline") == "skipped_stale"


async def test_prefilter_marks_and_explains(conn):
    run = await _run_id(conn)
    await store.ingest(conn, _rec(1), run_id=run, search_name="one", cfg=NO_STALE)  # clientTotalSpent 0
    assert await store.apply_prefilters(conn, {"min_client_total_spent": 100}) == 1
    cur = await conn.execute("SELECT status, reason FROM pipeline")
    row = await cur.fetchone()
    assert row["status"] == "prefiltered" and row["reason"].startswith("min_client_total_spent")


# --- full cycles ---------------------------------------------------------------------------


def _config(**over):
    raw = {
        "agent": {"allow_writes": over.pop("allow_writes", False)},
        "screener": {"model": "m", "system_prompt": "screen"},
        "writer": {"model": "m", "system_prompt": "write"},
        "settings": {
            "apify": {
                "actor_id": "a",
                "defaults_input": {"maxResults": 10},
                "searches": over.pop("searches", [{"name": "one", "run_input": {"query": "x"}}]),
            },
            "pipeline": {"max_age_hours_to_screen": None, **over.pop("pipeline", {})},
            "telegram": {"chat_id": -100123},
        },
    }
    return AgentConfig.from_dict(raw)


class FakeChat:
    """The group: offers and replies get increasing message ids; ``say`` adds a member's message."""

    chat_id = "-100123"

    def __init__(self):
        self.last_id = 0
        self.posts: list[tuple[int, str]] = []
        self.replies: list[tuple[int, list[str]]] = []
        self.inbox: list[Incoming] = []

    def _next(self):
        self.last_id += 1
        return self.last_id

    async def post(self, html_text):
        message_id = self._next()
        self.posts.append((message_id, html_text))
        return message_id

    async def reply(self, to_id, texts):
        self.replies.append((to_id, texts))
        return [self._next() for _ in texts]

    async def latest_id(self):
        return self.last_id

    async def fetch_after(self, min_id, limit):
        return [m for m in self.inbox if m.id > min_id][:limit]

    def say(self, text, reply_to=None, own=False, sender_id=42):
        message_id = self._next()
        self.inbox.append(Incoming(message_id, sender_id, reply_to, text, own))
        return message_id


def _deps(
    items_by_search, *, suitable=True, chat=None, rate_limited=False, failing=(), writer_fails=False, prompts=None
):
    async def fake_search(client, cfg, search):
        if search.name in failing:
            return ScrapeResult(search.name, search.run_input, "failed", error="boom")
        return ScrapeResult(
            search.name,
            search.run_input,
            "succeeded",
            items=items_by_search.get(search.name, []),
            cost_usd=Decimal("0.011"),
        )

    drafts = 0

    async def fake_run_once(prompt, ctx, role, *, allow_writes):
        nonlocal drafts
        if prompts is not None:
            prompts.append(prompt)
        if rate_limited:
            return {"status": "ERROR", "error": "rate limit exceeded", "model": role.model}
        if ctx.role == "screener":
            ctx.result.update(suitable=suitable, score=77, reasons="fits", matched_criteria=[])
        elif writer_fails:
            return {"status": "ERROR", "error": "model refused", "model": role.model}
        else:
            drafts += 1
            ctx.result.update(proposal=f"V{drafts} " + "P" * 400)
        return {"status": "COMPLETED", "error": None, "model": role.model, "cost_usd": 0.01, "num_turns": 1}

    return Deps(apify_client=None, run_once=fake_run_once, chat=chat, run_search=fake_search)


async def test_cycle_with_writes_off_suppresses_offers_and_skips_screening(conn):
    summary = await cycle(conn, _config(), _deps({"one": SAMPLES}, chat=FakeChat()))
    assert (summary.new, summary.screened, summary.offered, summary.suppressed) == (3, 0, 0, 3)
    assert await _count(conn, "SELECT count(*) FROM pipeline WHERE status = 'pending'") == 3


async def test_cycle_offers_each_job_once(conn):
    chat = FakeChat()
    cfg, deps = _config(allow_writes=True), _deps({"one": SAMPLES}, chat=chat)
    first = await cycle(conn, cfg, deps)
    second = await cycle(conn, cfg, deps)
    assert (first.offered, second.offered, second.known, len(chat.posts)) == (3, 0, 3, 3)
    assert await _count(conn, "SELECT count(*) FROM pipeline WHERE status = 'offered'") == 3
    assert await _count(conn, "SELECT count(*) FROM offers WHERE chat_id = '-100123'") == 3


async def test_offer_cap_leaves_the_rest_queued(conn):
    chat = FakeChat()
    cfg = _config(allow_writes=True, pipeline={"max_offers_per_cycle": 2})
    summary = await cycle(conn, cfg, _deps({"one": SAMPLES}, chat=chat))
    assert summary.offered == 2
    assert await _count(conn, "SELECT count(*) FROM pipeline WHERE status = 'pending'") == 1


async def test_with_screening_on_only_suitable_jobs_are_offered(conn):
    cfg = _config(allow_writes=True, pipeline={"screening_enabled": True})
    summary = await cycle(conn, cfg, _deps({"one": SAMPLES}, suitable=False, chat=FakeChat()))
    assert (summary.screened, summary.suitable, summary.offered) == (3, 0, 0)

    chat = FakeChat()
    await conn.execute("TRUNCATE pipeline, screenings, job_searches, job_versions, jobs, scrape_runs CASCADE")
    summary = await cycle(conn, cfg, _deps({"one": SAMPLES}, suitable=True, chat=chat))
    assert (summary.screened, summary.offered) == (3, 3)
    assert "Score 77/100" in chat.posts[0][1]


async def test_rate_limit_requeues_without_spending_attempts(conn):
    cfg = _config(pipeline={"screening_enabled": True})
    await cycle(conn, cfg, _deps({"one": SAMPLES}, rate_limited=True))
    cur = await conn.execute("SELECT status, attempts FROM pipeline")
    rows = await cur.fetchall()
    assert all(r["status"] == "pending" and r["attempts"] == 0 for r in rows)


async def test_one_failing_search_does_not_stop_the_others(conn):
    searches = [{"name": "bad", "run_input": {"query": "x"}}, {"name": "good", "run_input": {"query": "y"}}]
    summary = await cycle(conn, _config(searches=searches), _deps({"good": SAMPLES}, failing={"bad"}))
    assert (summary.failed_searches, summary.new) == (1, 3)
    assert await _count(conn, "SELECT count(*) FROM scrape_runs WHERE status = 'failed'") == 1


# --- poll: trigger replies → proposals -----------------------------------------------------


async def _offered(conn, chat, **deps_over):
    """One offered job, and the poller's cursor set past the offer."""
    cfg = _config(allow_writes=True, pipeline=deps_over.pop("pipeline", {}))
    deps = _deps({"one": SAMPLES[:1]}, chat=chat, **deps_over)
    await cycle(conn, cfg, deps)
    await poll(conn, cfg, deps)  # first poll only sets the cursor
    return cfg, deps, chat.posts[0][0]


def test_trigger_opens_the_reply_and_the_rest_is_instructions():
    triggers = ("+", "go")
    assert parse_trigger("Go", triggers) == ""
    assert parse_trigger("  +\n1. Which cloud?\n2. Timeline? ", triggers) == "1. Which cloud?\n2. Timeline?"
    assert parse_trigger("google it", triggers) is None
    assert parse_trigger("+1", triggers) is None
    assert parse_trigger("can we go with this", triggers) is None  # a trigger word later never fires


async def test_first_poll_never_replays_the_group_history(conn):
    chat = FakeChat()
    chat.say("go", reply_to=1)
    cfg, deps = _config(allow_writes=True), _deps({}, chat=chat)
    summary = await poll(conn, cfg, deps)
    assert summary.requested == 0
    assert await store.get_cursor(conn, chat.chat_id) == chat.last_id


async def test_trigger_reply_gets_a_plain_text_proposal(conn):
    chat = FakeChat()
    cfg, deps, offer_id = await _offered(conn, chat)
    trigger_id = chat.say("go", reply_to=offer_id)
    summary = await poll(conn, cfg, deps)
    assert (summary.requested, summary.drafted, summary.delivered) == (1, 1, 1)
    to_id, texts = chat.replies[-1]
    assert to_id == trigger_id
    assert texts[0].startswith(SAMPLES[0]["url"]) and "P" * 400 in texts[0]
    assert await _count(conn, "SELECT status FROM pipeline") == "delivered"
    assert await _count(conn, "SELECT screening_id FROM proposals") is None
    assert await _count(conn, "SELECT requested_by FROM offers") == 42


async def test_non_triggers_are_ignored(conn):
    chat = FakeChat()
    cfg, deps, offer_id = await _offered(conn, chat)
    chat.say("go", reply_to=offer_id, own=True)  # the agent's own message
    chat.say("go")  # not a reply
    chat.say("google this", reply_to=offer_id)  # no trigger token
    chat.say("go", reply_to=999)  # a reply to something that is not an offer
    summary = await poll(conn, cfg, deps)
    assert (summary.read, summary.requested, len(chat.replies)) == (4, 0, 0)
    assert await store.get_cursor(conn, chat.chat_id) == chat.last_id


async def test_repeat_trigger_gets_a_note_not_a_second_draft(conn):
    chat = FakeChat()
    cfg, deps, offer_id = await _offered(conn, chat)
    chat.say("+", reply_to=offer_id)
    await poll(conn, cfg, deps)
    again = chat.say("+", reply_to=offer_id)
    summary = await poll(conn, cfg, deps)
    assert (summary.requested, summary.drafted) == (0, 0)
    assert chat.replies[-1][0] == again and chat.replies[-1][1][0].startswith("Already sent above.")
    assert await _count(conn, "SELECT count(*) FROM proposals") == 1


async def test_questions_after_the_trigger_reach_the_writer(conn):
    chat = FakeChat()
    cfg, _, offer_id = await _offered(conn, chat)
    prompts: list[str] = []
    chat.say("+ 1. Which clouds have you used?", reply_to=offer_id)
    await poll(conn, cfg, _deps({}, chat=chat, prompts=prompts))
    assert "<operator_instructions>\n1. Which clouds have you used?\n</operator_instructions>" in prompts[-1]
    assert await _count(conn, "SELECT request_text FROM offers") == "1. Which clouds have you used?"


async def test_trigger_with_questions_rewrites_a_delivered_proposal(conn):
    chat = FakeChat()
    cfg, deps, offer_id = await _offered(conn, chat)
    chat.say("+", reply_to=offer_id)
    await poll(conn, cfg, deps)
    again = chat.say("+ also answer: availability?", reply_to=offer_id)
    summary = await poll(conn, cfg, deps)
    assert (summary.requested, summary.delivered) == (1, 1)
    assert chat.replies[-1][0] == again
    assert await _count(conn, "SELECT count(*) FROM proposals") == 2  # every version is kept
    assert await _count(conn, "SELECT revises_id FROM proposals ORDER BY id DESC LIMIT 1") is None


async def test_comments_on_a_proposal_revise_it_round_after_round(conn):
    chat = FakeChat()
    cfg, _, offer_id = await _offered(conn, chat)
    prompts: list[str] = []
    deps = _deps({}, chat=chat, prompts=prompts)
    chat.say("+ Client is Anna", reply_to=offer_id)
    await poll(conn, cfg, deps)
    first_ids = await _count(conn, "SELECT telegram_message_ids FROM proposals")

    comment = chat.say("shorter, drop the plan", reply_to=first_ids[-1])  # no trigger needed
    summary = await poll(conn, cfg, deps)
    assert (summary.requested, summary.drafted, summary.delivered) == (1, 1, 1)
    assert prompts[-1].startswith("Revise the draft in <current_proposal>")
    assert "<operator_instructions>\nClient is Anna\n</operator_instructions>" in prompts[-1]
    assert "<current_proposal>\nV1 " in prompts[-1]
    assert "<operator_feedback>\nRound 1: shorter, drop the plan\n</operator_feedback>" in prompts[-1]
    assert chat.replies[-1][0] == comment and chat.replies[-1][1][0].endswith("V2 " + "P" * 400)

    second_ids = await _count(conn, "SELECT telegram_message_ids FROM proposals ORDER BY id DESC LIMIT 1")
    chat.say("+ mention Kubernetes", reply_to=second_ids[0])  # a leading trigger is dropped
    await poll(conn, cfg, deps)
    assert "<current_proposal>\nV2 " in prompts[-1]
    assert "Round 1: shorter, drop the plan\n\nRound 2: mention Kubernetes\n" in prompts[-1]
    chain = await store.proposal_chain(conn, await _count(conn, "SELECT max(id) FROM proposals"))
    assert [p["request_text"] for p in chain] == ["Client is Anna", "shorter, drop the plan", "mention Kubernetes"]


async def test_comments_while_a_draft_is_in_hand_get_a_note(conn):
    chat = FakeChat()
    cfg, deps, offer_id = await _offered(conn, chat)
    chat.say("+", reply_to=offer_id)
    await poll(conn, cfg, deps)
    ids = await _count(conn, "SELECT telegram_message_ids FROM proposals")
    await conn.execute("UPDATE pipeline SET status = 'drafting'")
    again = chat.say("shorter", reply_to=ids[0])
    summary = await poll(conn, cfg, deps)
    assert summary.requested == 0
    assert chat.replies[-1][0] == again and chat.replies[-1][1][0].startswith("Already writing it.")


async def test_writer_failure_reports_and_a_new_trigger_retries(conn):
    chat = FakeChat()
    cfg, deps, offer_id = await _offered(conn, chat, writer_fails=True, pipeline={"max_attempts": 1})
    trigger_id = chat.say("go", reply_to=offer_id)
    await poll(conn, cfg, deps)
    assert await _count(conn, "SELECT status FROM pipeline") == "error"
    assert chat.replies[-1][0] == trigger_id and "Could not write a proposal" in chat.replies[-1][1][0]

    ok_deps = _deps({}, chat=chat)
    chat.say("go", reply_to=offer_id)
    summary = await poll(conn, cfg, ok_deps)
    assert (summary.requested, summary.delivered) == (1, 1)


async def test_poll_does_nothing_with_writes_off(conn):
    chat = FakeChat()
    summary = await poll(conn, _config(), _deps({}, chat=chat))
    assert summary.read == 0 and await store.get_cursor(conn, chat.chat_id) is None
