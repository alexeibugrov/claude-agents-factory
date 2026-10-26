"""Promptfoo provider: one dataset case through the real writer (map_record → writer_prompt → run_once).

Only the writer's system_prompt is swapped for the prompt under test; nothing is written anywhere."""

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
from agent.render import writer_prompt  # noqa: E402
from agent.store import map_record  # noqa: E402


async def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    config = options.get("config") or {}
    case_vars = context.get("vars") or {}
    if os.environ.get("ANTHROPIC_API_KEY"):
        return {"output": "", "error": "ANTHROPIC_API_KEY is set; evals run on subscription auth only"}

    cfg = AgentConfig.load(config["agent_config"])
    role = dataclasses.replace(cfg.writer, system_prompt=prompt.strip())
    if role.prompt_sha != config["prompt_sha"]:
        # The run manifest names one prompt version; anything else reaching the agent is a bug.
        return {"output": "", "error": f"prompt changed in transit: {role.prompt_sha} != {config['prompt_sha']}"}

    record = json.loads(case_vars["job_record"])
    job = map_record(record)
    job["job_id"] = str(record.get("jobId") or case_vars["case_id"])
    user_message = writer_prompt(job, None, case_vars.get("operator_instructions") or None)

    # As production: a failed draft is retried as a fresh run, up to pipeline.max_attempts.
    failed: list[str] = []
    for _ in range(cfg.pipeline.max_attempts):
        ctx = RunContext(run_id=f"eval-{uuid.uuid4().hex[:8]}", job_id=job["job_id"], role="writer")
        run = await run_once(user_message, ctx, role, allow_writes=False)
        if run["status"] == "COMPLETED" and ctx.result.get("proposal"):
            break
        failed.append(run.get("error") or "the writer finished without a successful submit_proposal")
        if _is_rate_limit(run.get("error")):
            break

    proposal = ctx.result.get("proposal")
    notes = ctx.result.get("notes_for_operator")
    metadata = {
        "case_id": case_vars["case_id"],
        "prompt_sha": role.prompt_sha,
        "model": run["model"],
        "effort": role.effort,
        "agent_run_id": run["run_id"],
        "status": run["status"],
        "duration_s": run["duration_s"],
        "num_turns": run["num_turns"],
        "failed_attempts": failed,
        "submit_attempts": sum(1 for e in run["tool_executions"] if e["tool"] == "submit_proposal"),
        "user_message": user_message,
        "proposal": proposal,
        "notes_for_operator": notes,
        "words": len(proposal.split()) if proposal else None,
    }
    if run["status"] != "COMPLETED" or not proposal:
        error = run.get("error") or "the writer finished without a successful submit_proposal"
        return {"output": "", "error": error, "metadata": metadata}
    # Exactly the draft Telegram delivers; notes, if a prompt still writes them, stay in metadata.
    output = proposal
    return {"output": output, "cost": run["cost_usd"], "latencyMs": int(run["duration_s"] * 1000), "metadata": metadata}
