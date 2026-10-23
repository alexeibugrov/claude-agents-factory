"""One Apify actor run per configured search, reduced to a :class:`ScrapeResult`.

Actor facts that shape this module:

* apify-client 3.x returns pydantic models; ``_as_dict`` normalises them to the actor's camelCase.
* The real charge is ``chargedEventCounts`` x ``pricingInfo.pricingPerEvent``. The run's
  ``usageTotalUsd`` under-reports it and is not used.
* Incremental state remembers only emitted jobs, so overflow beyond ``maxResults`` arrives on the
  next run; ``maxAgeMinutes`` in the input bounds how far back a new ``stateKey`` reaches.

* The actor logs Upwork's own count for the search ("total available: N"). Missing or 0 means the
  query is broken (Upwork answers a query over ~90 words with a silent 0), so it is alerted.

Apify enforces two hard caps per run: ``max_items`` (= ``maxResults``) and ``max_total_charge_usd``.
Failures are returned, never raised, so one bad search cannot stop the cycle.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any

from agent.config import ApifyConfig, Search

logger = logging.getLogger(__name__)


@dataclass
class ScrapeResult:
    search_name: str
    run_input: dict[str, Any]
    status: str  # succeeded | failed
    items: list[dict[str, Any]] = field(default_factory=list)
    apify_run_id: str | None = None
    apify_dataset_id: str | None = None
    cost_usd: Decimal | None = None
    error: str | None = None
    upwork_total: int | None = None


def _as_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", by_alias=True)
    return dict(obj)


RESULT_EVENT = "apify-default-dataset-item"


def run_cost(run: dict[str, Any], items_returned: int = 0) -> Decimal | None:
    """Sum of charged events x their per-event price; None when the run does not report them.

    ``chargedEventCounts`` settles a few seconds after the run ends (verified: an immediate re-read
    showed 0 result events for 1 returned item), so the result-event count is floored at the
    number of items actually returned.
    """
    counts = dict(run.get("chargedEventCounts") or {})
    events = ((run.get("pricingInfo") or {}).get("pricingPerEvent") or {}).get("actorChargeEvents") or {}
    if not events or not (counts or items_returned):
        return None
    if RESULT_EVENT in events:
        counts[RESULT_EVENT] = max(int(counts.get(RESULT_EVENT, 0)), items_returned)
    total = Decimal("0")
    for name, count in counts.items():
        price = (events.get(name) or {}).get("eventPriceUsd")
        if price is not None:
            total += Decimal(str(price)) * int(count)
    return total


_TOTAL = re.compile(r"total available: (\d+)")


def upwork_total(log_text: str | None) -> int | None:
    """Upwork's job count for the search, from the actor's run log; None when it never logged one."""
    match = _TOTAL.search(log_text or "")
    return int(match.group(1)) if match else None


def build_run_input(search: Search) -> dict[str, Any]:
    return {**search.run_input, "stateKey": search.state_key}


def _run_sync(client: Any, cfg: ApifyConfig, search: Search) -> ScrapeResult:
    run_input = build_run_input(search)
    result = ScrapeResult(search_name=search.name, run_input=run_input, status="failed")
    try:
        started = client.actor(cfg.actor_id).call(
            run_input=run_input,
            max_items=int(run_input["maxResults"]),
            max_total_charge_usd=Decimal(str(cfg.max_charge_per_run_usd)),
            memory_mbytes=cfg.memory_mbytes,
            run_timeout=timedelta(seconds=cfg.timeout_secs),
        )
        run = _as_dict(started)
        if not run:
            result.error = "actor call returned no run"
            return result
        result.apify_run_id = run.get("id")
        # Re-read the run: the charge fields settle only after it finishes.
        run = _as_dict(client.run(run["id"]).get()) or run
        result.apify_dataset_id = run.get("defaultDatasetId")
        result.cost_usd = run_cost(run)
        if run.get("status") != "SUCCEEDED":
            result.error = f"actor run status {run.get('status')}"
            return result
        result.items = [_as_dict(item) for item in client.dataset(run["defaultDatasetId"]).iterate_items()]
        result.cost_usd = run_cost(run, items_returned=len(result.items))
        result.status = "succeeded"
        try:
            result.upwork_total = upwork_total(client.log(run["id"]).get())
        except Exception as exc:  # noqa: BLE001 — a missing total is alerted, never fatal.
            logger.warning("run log unreadable search=%s run=%s: %s", search.name, run["id"], exc)
    except Exception as exc:  # noqa: BLE001 — a failed search is reported, never fatal to the cycle.
        result.error = f"{type(exc).__name__}: {exc}"
    return result


async def run_search(client: Any, cfg: ApifyConfig, search: Search) -> ScrapeResult:
    """Run one search (the Apify client is blocking, so it runs in a worker thread)."""
    result = await asyncio.to_thread(_run_sync, client, cfg, search)
    if result.status != "succeeded":
        logger.warning("AGENT ALERT scrape failed search=%s error=%s", search.name, result.error)
        return result
    logger.info(
        "scrape ok search=%s items=%d upwork_total=%s cost_usd=%s run=%s",
        search.name,
        len(result.items),
        result.upwork_total,
        result.cost_usd,
        result.apify_run_id,
    )
    if not result.upwork_total:
        logger.warning(
            "AGENT ALERT search=%s upwork_total=%s: Upwork matched nothing; the query is likely broken run=%s",
            search.name,
            result.upwork_total,
            result.apify_run_id,
        )
    return result
