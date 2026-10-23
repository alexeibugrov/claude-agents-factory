"""Manual scrape test: one Apify run per search, using the agent's own config and scrape code.

Run input, caps (maxResults <= 10, $0.05 per run, memory, timeout) and cost maths come straight
from agent_config.yaml + agent/scrape.py, so this is what the agent sends. Only the stateKey
differs (suffix "-manual"), so manual runs never consume the agent's incremental state. Nothing
is written to Postgres or Telegram.

    export APIFY_TOKEN=...            # in your shell, never in a file
    cd agents/upwork-scout
    uv run python scripts/try_scrape.py                    # every configured search
    uv run python scripts/try_scrape.py --fresh            # ignore incremental state: latest jobs again
    uv run python scripts/try_scrape.py --max 3 --out /tmp/jobs.json

Experiments (never saved to the config): --url replaces the search URL, --set overrides one
actor input field (JSON value, repeatable), --find reports whether a job containing TEXT came back.

    uv run python scripts/try_scrape.py --fresh --url 'https://www.upwork.com/nx/search/jobs/?q=n8n' --find n8n
    uv run python scripts/try_scrape.py --fresh --set maxAgeMinutes=240 --find n8n

SEARCH_URL in the environment is the default for --url. Each search ends with one
"SUMMARY {json}" line (Upwork's total, the actor's post-fetch count, the jobs) for comparing runs.
On a host with Docker only, scripts/try_scrape.sh runs this inside the agent image.
"""

import argparse
import json
import os
import re
import sys
from dataclasses import replace
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))

from apify_client import ApifyClient  # noqa: E402

from agent.config import MAX_RESULTS_LIMIT, AgentConfig  # noqa: E402
from agent.render import budget_line, client_line  # noqa: E402
from agent.scrape import _run_sync  # noqa: E402
from agent.store import map_record  # noqa: E402


def log_counts(client: ApifyClient, run_id: str | None) -> dict:
    """Upwork's total for the search and the actor's post-fetch kept/collected, from the run log."""
    text = (client.log(run_id).get() if run_id else None) or ""
    total = re.search(r"total available: (\d+)", text)
    kept = re.search(r"Post-fetch filters kept (\d+)/(\d+)", text)
    return {
        "upwork_total": int(total.group(1)) if total else None,
        "post_fetch_kept": int(kept.group(1)) if kept else None,
        "collected": int(kept.group(2)) if kept else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--search", help="only this search name (default: all)")
    parser.add_argument("--max", type=int, help=f"maxResults override, 1-{MAX_RESULTS_LIMIT}")
    parser.add_argument("--fresh", action="store_true", help="incrementalMode off for this run")
    parser.add_argument("--out", type=Path, help="write raw records to this JSON file")
    parser.add_argument(
        "--url", default=os.environ.get("SEARCH_URL") or None, help="replace searchUrl (and drop query) for this run"
    )
    parser.add_argument("--set", action="append", default=[], metavar="KEY=JSON", help="override an input field")
    parser.add_argument("--find", metavar="TEXT", help="report whether a returned job contains TEXT")
    parser.add_argument(
        "--state-suffix", default="manual", help="stateKey suffix, so incremental experiments do not share state"
    )
    args = parser.parse_args()
    overrides = {}
    for pair in args.set:
        key, sep, raw = pair.partition("=")
        if not sep:
            parser.error(f"--set needs KEY=VALUE, got {pair!r}")
        try:
            overrides[key] = json.loads(raw)
        except json.JSONDecodeError:
            overrides[key] = raw
    if "maxResults" in overrides:
        parser.error("use --max for maxResults")
    if args.max is not None and not 1 <= args.max <= MAX_RESULTS_LIMIT:
        parser.error(f"--max must be 1-{MAX_RESULTS_LIMIT}")
    if not os.environ.get("APIFY_TOKEN"):
        parser.error("export APIFY_TOKEN first")

    cfg = AgentConfig.load(AGENT_DIR / "agent_config.yaml")
    searches = [s for s in cfg.apify.searches if args.search in (None, s.name)]
    if not searches:
        parser.error(f"no search named {args.search!r}")

    client = ApifyClient(os.environ["APIFY_TOKEN"])
    all_items = []
    for search in searches:
        run_input = dict(search.run_input)
        if args.max is not None:
            run_input["maxResults"] = args.max
        if args.fresh:
            run_input["incrementalMode"] = False
        if args.url:
            run_input.pop("query", None)
            run_input["searchUrl"] = args.url
        run_input.update(overrides)
        manual = replace(search, name=f"{search.name}-{args.state_suffix}", run_input=run_input)

        print(f"\n== {search.name}  (stateKey={manual.state_key})")
        print(json.dumps({k: v for k, v in run_input.items() if k != "proxyConfiguration"}, indent=2))
        result = _run_sync(client, cfg.apify, manual)
        print(f"status={result.status} items={len(result.items)} cost_usd={result.cost_usd} run={result.apify_run_id}")
        if result.error:
            print(f"error: {result.error}")
        for item in result.items:
            job = map_record(item)
            print(f"\n- {job.get('title')}\n  {job.get('url')}")
            print(f"  {budget_line(job)} | {job.get('experience_level') or '?'} | published {job.get('published_at')}")
            print(f"  client: {client_line(job)} | applicants: {job.get('total_applicants')}")
            print(f"  skills: {', '.join(job.get('skills') or [])}")
        all_items.extend(result.items)
        summary = {
            "search": search.name,
            "search_url": run_input.get("searchUrl"),
            "query": run_input.get("query"),
            "status": result.status,
            "run_id": result.apify_run_id,
            "cost_usd": str(result.cost_usd) if result.cost_usd is not None else None,
            **log_counts(client, result.apify_run_id),
            "jobs": [
                {"jobId": i.get("jobId"), "publishTime": i.get("publishTime"), "title": i.get("title")}
                for i in result.items
            ],
        }
        print(f"\nSUMMARY {json.dumps(summary)}")

    if args.find:
        needle = args.find.lower()
        hits = [i for i in all_items if needle in f"{i.get('title')} {i.get('description')}".lower()]
        print(f"\nfind {args.find!r}: {len(hits)} of {len(all_items)} jobs")
        for item in hits:
            print(f"  HIT {item.get('title')}  {item.get('url')}")
    if args.out:
        args.out.write_text(json.dumps(all_items, indent=2, default=str))
        print(f"\nwrote {len(all_items)} records to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
