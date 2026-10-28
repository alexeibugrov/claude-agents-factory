"""Promptfoo provider: one dataset case through the real writer or screener (map_record → prompt → run_once).

Only the role's system prompt, and optionally ABOUT ME, are swapped for the versions under test;
nothing is written anywhere."""

from __future__ import annotations

import dataclasses
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.config import AgentConfig  # noqa: E402
from agent.context import RunContext  # noqa: E402
from agent.loop import run_once  # noqa: E402
from agent.pipeline import _is_rate_limit  # noqa: E402
from agent.render import screener_prompt, writer_prompt  # noqa: E402
from agent.store import map_record  # noqa: E402

# Per role: the submit tool, and the result key a successful submit records.
_SUBMIT = {"writer": ("submit_proposal", "proposal"), "screener": ("submit_screening", "score")}


async def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    config = options.get("config") or {}
    case_vars = context.get("vars") or {}
    if os.environ.get("ANTHROPIC_API_KEY"):
        return {"output": "", "error": "ANTHROPIC_API_KEY is set; evals run on subscription auth only"}

    cfg = AgentConfig.load(config["agent_config"])
    role_name = config.get("role") or "writer"
    about_me_file = config.get("about_me_file")
    about_me = Path(about_me_file).read_text(encoding="utf-8").strip() if about_me_file else None
    role = dataclasses.replace(getattr(cfg, role_name), system_prompt=prompt.strip(), about_me=about_me)
    if role.prompt_sha != config["prompt_sha"]:
        # The run manifest names one prompt version; anything else reaching the agent is a bug.
        return {"output": "", "error": f"prompt changed in transit: {role.prompt_sha} != {config['prompt_sha']}"}

    record = json.loads(case_vars["job_record"])
    job = map_record(record)
    job["job_id"] = str(record.get("jobId") or case_vars["case_id"])
    if role_name == "screener":
        user_message = screener_prompt(job)
    else:
        user_message = writer_prompt(job, case_vars.get("operator_instructions") or None)
    tool, key = _SUBMIT[role_name]

    # As production: a failed run is retried as a fresh run, up to pipeline.max_attempts.
    failed: list[str] = []
    for _ in range(cfg.pipeline.max_attempts):
        ctx = RunContext(run_id=f"eval-{uuid.uuid4().hex[:8]}", job_id=job["job_id"], role=role_name)
        run = await run_once(user_message, ctx, role, allow_writes=False)
        if run["status"] == "COMPLETED" and key in ctx.result:
            break
        failed.append(run.get("error") or f"the {role_name} finished without a successful {tool}")
        if _is_rate_limit(run.get("error")):
            break

    metadata = {
        "case_id": case_vars["case_id"],
        "role": role_name,
        "prompt_sha": role.prompt_sha,
        "model": run["model"],
        "effort": role.effort,
        "agent_run_id": run["run_id"],
        "status": run["status"],
        "duration_s": run["duration_s"],
        "num_turns": run["num_turns"],
        "failed_attempts": failed,
        "submit_attempts": sum(1 for e in run["tool_executions"] if e["tool"] == tool),
        "user_message": user_message,
    }
    if role_name == "screener":
        score, reason = ctx.result.get("score"), ctx.result.get("reason")
        metadata.update(score=score, reason=reason)
        # The rating line as the offer message shows it.
        output = f"Match {score}/5 — {reason}" if score is not None else None
    else:
        proposal = ctx.result.get("proposal")
        metadata.update(proposal=proposal, words=len(proposal.split()) if proposal else None)
        output = proposal  # exactly the draft Telegram delivers
    if run["status"] != "COMPLETED" or not output:
        error = run.get("error") or f"the {role_name} finished without a successful {tool}"
        return {"output": "", "error": error, "metadata": metadata}
    return {"output": output, "cost": run["cost_usd"], "latencyMs": int(run["duration_s"] * 1000), "metadata": metadata}
