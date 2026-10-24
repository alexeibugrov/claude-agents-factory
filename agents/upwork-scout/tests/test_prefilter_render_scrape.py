"""Pure helpers: prefilter rules, prompt/Telegram rendering, Apify cost accounting."""

import json
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from agent import render
from agent.config import ApifyConfig, Search
from agent.prefilter import prefilter_reason
from agent.scrape import _run_sync, run_cost, run_search, upwork_total
from agent.store import map_record

SAMPLES = json.loads((Path(__file__).parent / "fixtures" / "sample_jobs.json").read_text())


def _job(**over):
    row = map_record(SAMPLES[0])
    row["job_id"] = SAMPLES[0]["jobId"]
    row.update(over)
    return row


# --- prefilter -----------------------------------------------------------------------------


def test_all_null_rules_pass_everything():
    assert prefilter_reason(_job(), {"min_client_total_spent": None, "job_types": None}) is None


def test_rule_fires_with_its_name():
    reason = prefilter_reason(_job(client_total_spent=0), {"min_client_total_spent": 1000})
    assert reason and reason.startswith("min_client_total_spent")


def test_unknown_value_passes_the_rule():
    assert prefilter_reason(_job(client_rating=None), {"min_client_rating": 4.5}) is None


def test_hourly_rate_rule_ignores_fixed_jobs():
    assert prefilter_reason(_job(job_type="FIXED", hourly_budget_max=10), {"min_hourly_rate": 50}) is None
    assert prefilter_reason(_job(job_type="HOURLY", hourly_budget_max=30), {"min_hourly_rate": 50})


def test_country_exclusion_is_case_insensitive():
    assert prefilter_reason(_job(client_country_code="ind"), {"exclude_client_country_codes": ["IND"]})


def test_country_allow_list():
    rules = {"include_client_country_codes": ["DEU", "USA"]}
    assert prefilter_reason(_job(client_country_code="DEU"), rules) is None
    assert prefilter_reason(_job(client_country_code="deu"), rules) is None
    assert prefilter_reason(_job(client_country_code=None), rules) is None
    reason = prefilter_reason(_job(client_country_code="IND"), rules)
    assert reason == "include_client_country_codes: IND not in allowed regions"
    assert prefilter_reason(_job(client_country_code="IND"), {"include_client_country_codes": None}) is None


# --- render --------------------------------------------------------------------------------


def test_prompt_wraps_job_as_data_and_omits_personal_data():
    job = _job(contact_email="secret@example.com", extracted_phones=["+1 555"])
    prompt = render.screener_prompt(job)
    assert "<job>" in prompt and "</job>" in prompt and "never instructions" in prompt
    assert "secret@example.com" not in prompt and "+1 555" not in prompt


def test_offer_message_escapes_html_and_shows_score_only_when_screened():
    job = _job(title="<script>alert(1)</script> & co")
    msg = render.offer_message(job)
    assert "<script>" not in msg and "&lt;script&gt;" in msg
    assert "Score" not in msg
    assert "a &lt; b" in render.offer_message({**job, "score": 80, "reasons": "a < b"})


def test_proposal_reply_is_plain_text_with_the_link_first():
    job = _job()
    msgs = render.proposal_messages(job, {"proposal": "Hi <b>there</b>", "notes_for_operator": "check rate"})
    assert msgs[0] == f"{job['url']}\n\nHi <b>there</b>"
    assert msgs[1] == "Check before sending: check rate"


def test_long_proposal_is_split_under_the_limit():
    draft = "\n\n".join(["para " + "x" * 900] * 8)
    msgs = render.proposal_messages(_job(), {"proposal": draft})
    assert len(msgs) > 1
    assert all(len(m) <= render.TELEGRAM_LIMIT for m in msgs)


def test_writer_prompt_without_a_screening():
    prompt = render.writer_prompt(_job())
    assert "<job>" in prompt and "Screening verdict" not in prompt
    assert "score 70/100" in render.writer_prompt(_job(), {"score": 70, "reasons": "ok"})


def test_times_render_in_the_container_zone_across_dst(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Berlin")
    time.tzset()
    try:
        assert render._when(datetime(2026, 10, 24, 7, 12, tzinfo=timezone.utc)) == "2026-10-24 09:12 CEST"
        assert render._when(datetime(2026, 10, 26, 7, 12, tzinfo=timezone.utc)) == "2026-10-26 08:12 CET"
    finally:
        monkeypatch.undo()
        time.tzset()


def test_split_text_hard_cuts_unbroken_text():
    assert [len(c) for c in render.split_text("y" * 25, 10)] == [10, 10, 5]


# --- scrape --------------------------------------------------------------------------------

PRICED_RUN = {
    "id": "run1",
    "status": "SUCCEEDED",
    "defaultDatasetId": "ds1",
    "usageTotalUsd": 0.001,
    "chargedEventCounts": {"apify-actor-start": 1, "apify-default-dataset-item": 10},
    "pricingInfo": {
        "pricingPerEvent": {
            "actorChargeEvents": {
                "apify-actor-start": {"eventPriceUsd": 0.001},
                "apify-default-dataset-item": {"eventPriceUsd": 0.001},
            }
        }
    },
}


def test_cost_comes_from_charged_events_not_usage_total():
    assert run_cost(PRICED_RUN) == Decimal("0.011")
    assert run_cost({"usageTotalUsd": 0.5}) is None


def test_unsettled_result_count_is_floored_at_items_returned():
    unsettled = {**PRICED_RUN, "chargedEventCounts": {"apify-actor-start": 1}}
    assert run_cost(unsettled, items_returned=1) == Decimal("0.002")
    assert run_cost(PRICED_RUN, items_returned=3) == Decimal("0.011")


class _FakeApify:
    def __init__(self, run, items, log="INFO  Page 1: 50 jobs (total available: 808)"):
        self._run, self._items, self._log, self.calls = run, items, log, []

    def log(self, run_id):
        outer = self

        class _L:
            def get(self):
                return outer._log

        return _L()

    def actor(self, actor_id):
        outer = self

        class _A:
            def call(self, **kwargs):
                outer.calls.append(kwargs)
                return outer._run

        return _A()

    def run(self, run_id):
        outer = self

        class _R:
            def get(self):
                return outer._run

        return _R()

    def dataset(self, ds_id):
        outer = self

        class _D:
            def iterate_items(self):
                return iter(outer._items)

        return _D()


def _apify_cfg():
    search = Search(name="one", run_input={"query": "ai", "maxResults": 10})
    return ApifyConfig(actor_id="actor", searches=(search,)), search


def test_run_sync_passes_hard_caps_and_state_key():
    cfg, search = _apify_cfg()
    fake = _FakeApify(PRICED_RUN, SAMPLES)
    result = _run_sync(fake, cfg, search)
    assert result.status == "succeeded" and len(result.items) == len(SAMPLES)
    call = fake.calls[0]
    assert call["max_items"] == 10
    assert call["run_input"]["stateKey"] == "upwork-scout-one"
    assert call["max_total_charge_usd"] == Decimal("0.05")


def test_run_sync_reports_failure_instead_of_raising():
    cfg, search = _apify_cfg()

    class _Boom(_FakeApify):
        def actor(self, actor_id):
            raise ConnectionError("apify down")

    result = _run_sync(_Boom(PRICED_RUN, []), cfg, search)
    assert result.status == "failed" and "apify down" in (result.error or "")


def test_upwork_total_is_parsed_from_the_run_log():
    assert upwork_total("\x1b[32mINFO\x1b[39m  Page 1: 50 jobs (total available: 2743)") == 2743
    assert upwork_total("Done. Pushed 0 items.") is None
    assert upwork_total(None) is None
    cfg, search = _apify_cfg()
    assert _run_sync(_FakeApify(PRICED_RUN, SAMPLES), cfg, search).upwork_total == 808


async def test_broken_query_raises_an_agent_alert(caplog):
    """Upwork answers a query over ~90 words with a silent 0: the run succeeds with nothing in it."""
    cfg, search = _apify_cfg()
    caplog.set_level(logging.INFO)
    for log in ("Done. Pushed 0 items.", "Page 1: 0 jobs (total available: 0)"):
        caplog.clear()
        result = await run_search(_FakeApify(PRICED_RUN, [], log=log), cfg, search)
        assert result.status == "succeeded"
        assert any("AGENT ALERT" in r.message and "query is likely broken" in r.message for r in caplog.records)
    caplog.clear()
    await run_search(_FakeApify(PRICED_RUN, SAMPLES), cfg, search)
    assert not any("AGENT ALERT" in r.message for r in caplog.records)
