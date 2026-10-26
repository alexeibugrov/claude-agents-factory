"""One batch: a fixed prompt version over one dataset, recorded in runs/<run_id>/ and in the eval's metadata."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from agent.config import AgentConfig
from agent.render import job_facts
from agent.store import map_record
from evals import dataset as datasets
from evals.common import (
    AGENT_CONFIG,
    EVALS_DIR,
    REVIEW_METRIC,
    RUNS_DIR,
    EvalError,
    file_sha256,
    git_state,
    load_prompt,
    prompt_sha,
    promptfoo,
    promptfoo_version,
    rel,
    settings,
)

# Fails every output until the operator rates it; a 👍/👎 in the viewer overrides it. So the
# viewer's "Passes" are human approvals only, and an unrated output never looks approved.
PENDING_REVIEW = "({pass: false, score: 0, reason: 'Awaiting human review: rate it with thumbs up or down'})"


def _job_display(case: datasets.Case) -> str:
    """The job as the reviewer reads it in the viewer: the facts block and the description."""
    job = map_record(case.job)
    description = job.get("description_markdown") or job.get("description") or ""
    return f"{job_facts(job)}\n\n{description}"


def _test(case: datasets.Case, ds: datasets.Dataset) -> dict[str, Any]:
    return {
        "description": case.id,
        "vars": {
            "case_id": case.id,
            "job": _job_display(case),
            "operator_instructions": case.operator_instructions or "",
            "job_record": json.dumps(case.job, sort_keys=True, ensure_ascii=False),
        },
        "metadata": {
            **case.metadata,
            "case_id": case.id,
            "dataset": f"{ds.id}@{ds.version}",
            "split": ds.split,
            "job_source": case.job_source,
            "reference": case.reference or "",
        },
    }


def manifest(run_id: str, prompt_path: Path, prompt_text: str, ds: datasets.Dataset, cache: bool) -> dict[str, Any]:
    cfg = AgentConfig.load(AGENT_CONFIG)
    w = cfg.writer
    return {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "role": "writer",
        "prompt": {"path": rel(prompt_path), "sha": prompt_sha(prompt_text), "sha256": file_sha256(prompt_path)},
        "dataset": ds.manifest(),
        "agent": {
            "config_path": rel(AGENT_CONFIG),
            "config_sha256": file_sha256(AGENT_CONFIG),
            "writer": {
                "model": w.model,
                "fallback_model": w.fallback_model,
                "effort": w.effort,
                "max_turns": w.max_turns,
                "timeout_s": w.timeout_s,
                "max_budget_usd": w.max_budget_usd,
            },
        },
        "git": git_state(),
        "promptfoo": {"version": promptfoo_version(), "cache": cache},
    }


def build_config(m: dict[str, Any], prompt_text: str, ds: datasets.Dataset, concurrency: int) -> dict[str, Any]:
    s = settings().get("provider") or {}
    p, d = m["prompt"], m["dataset"]
    return {
        "description": f"writer {p['path']}@{p['sha']} on {d['id']}@{d['version']} ({d['split']}) {m['run_id']}",
        "tags": {
            "run_id": m["run_id"],
            "prompt": f"{p['path']}@{p['sha']}",
            "dataset": f"{d['id']}@{d['version']}",
            "split": d["split"],
        },
        "metadata": {"experiment": m},
        # Inline, so the generated config is itself a full record of the prompt this batch ran.
        "prompts": [{"raw": prompt_text, "label": f"{p['path']}@{p['sha']}"}],
        "providers": [
            {
                "id": f"file://{(EVALS_DIR / 'provider.py').resolve()}",
                "label": "upwork-scout writer",
                "config": {
                    "agent_config": str(AGENT_CONFIG.resolve()),
                    "prompt_sha": p["sha"],
                    "timeout": int(s.get("timeout_ms", 1_500_000)),
                    "workers": concurrency,
                },
            }
        ],
        "defaultTest": {"assert": [{"type": "javascript", "metric": REVIEW_METRIC, "value": PENDING_REVIEW}]},
        "tests": [_test(c, ds) for c in ds.cases],
        "evaluateOptions": {"maxConcurrency": concurrency, "cache": m["promptfoo"]["cache"]},
        "sharing": False,
    }


def run(
    prompt_path: Path,
    dataset_path: Path,
    *,
    concurrency: int | None = None,
    cache: bool = False,
    cases: list[str] | None = None,
    repeat: int = 1,
) -> dict[str, Any]:
    prompt_text = load_prompt(prompt_path)
    ds = datasets.load(dataset_path)
    if cases:
        unknown = set(cases) - {c.id for c in ds.cases}
        if unknown:
            raise EvalError(f"unknown case ids: {', '.join(sorted(unknown))}")
    concurrency = concurrency or int((settings().get("provider") or {}).get("concurrency", 2))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # A candidate is candidates/<id>/prompt.md: name the run after the candidate, not "prompt".
    if prompt_path.stem == "prompt":
        name = prompt_path.parent.name  # candidates/<id>/prompt.md: the candidate id
    elif re.fullmatch(r"v\d+", prompt_path.stem):
        name = f"{prompt_path.parent.name}-{prompt_path.stem}"  # prompts/writer/v2.md: writer-v2
    else:
        name = prompt_path.stem
    run_id = f"{stamp}-{ds.id}-{name}-{prompt_sha(prompt_text)[:8]}"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True)

    m = manifest(run_id, prompt_path, prompt_text, ds, cache)
    m["filter_cases"] = cases or None
    m["repeat"] = repeat
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(m, indent=2) + "\n")
    config_path = run_dir / "promptfooconfig.yaml"
    config_path.write_text(
        yaml.safe_dump(build_config(m, prompt_text, ds, concurrency), sort_keys=False, allow_unicode=True)
    )

    results = run_dir / "results.json"
    args = ["eval", "-c", str(config_path), "-o", str(results), "--no-progress-bar", "--no-table"]
    if not cache:
        args.append("--no-cache")
    if repeat > 1:
        args += ["--repeat", str(repeat)]
    if cases:
        args += ["--filter-pattern", "^(" + "|".join(cases) + ")$"]
    # 100 = some test "failed": expected, every output fails the pending-review marker until rated.
    code = promptfoo(*args, check=False)
    if code not in (0, 100) or not results.is_file():
        raise EvalError(f"promptfoo eval exited with {code}; run directory: {rel(run_dir)}")

    m["eval_id"] = json.loads(results.read_text()).get("evalId")
    manifest_path.write_text(json.dumps(m, indent=2) + "\n")
    return m
