"""The agent's tool surface: in-process MCP tools bound to one :class:`RunContext`.

Two rules hold for every tool in the factory:

1. **Bind, don't globalise.** ``build_server(ctx)`` closes over the run's context so concurrent
   runs cannot cross-contaminate each other's state.
2. **Never raise.** A raising ``@tool`` handler tears down the Claude session, losing the whole
   run. Every failure degrades to ``{"success": False, "error": ...}`` instead, which the model
   can read and react to, and which the loop can report.

Each role gets exactly one tool, its submit tool. Both are pure: they validate the answer and
record it on ``ctx.result``; the deterministic pipeline persists it after the run. The job itself
arrives in the prompt, so no lookup tool is needed.

Tools are addressed by the model as ``mcp__<SERVER_NAME>__<tool name>``.
"""

from __future__ import annotations

import functools
import json
from typing import Any, Callable

from claude_agent_sdk import create_sdk_mcp_server, tool

from agent.context import RunContext

SERVER_NAME = "agent"

MAX_REASONS_CHARS = 600
MIN_PROPOSAL_CHARS = 300
MAX_PROPOSAL_CHARS = 5000
# Operator rule: a proposal stays below 350 words. Enforced here, so an over-long draft goes back
# to the model with the count instead of reaching the operator.
MAX_PROPOSAL_WORDS = 350


def _submit_screening(
    ctx: RunContext,
    *,
    suitable: bool,
    score: int,
    reasons: str,
    matched_criteria: list[str] | None = None,
) -> dict:
    """Record the screener's verdict for this run's job."""
    if not isinstance(suitable, bool):
        return {"success": False, "error": "suitable must be true or false"}
    if not isinstance(score, int) or not 0 <= score <= 100:
        return {"success": False, "error": "score must be an integer 0-100"}
    reasons = (reasons or "").strip()
    if not reasons:
        return {"success": False, "error": "reasons must not be empty"}
    if len(reasons) > MAX_REASONS_CHARS:
        return {"success": False, "error": f"reasons must be at most {MAX_REASONS_CHARS} characters"}
    ctx.result.update(
        suitable=suitable,
        score=score,
        reasons=reasons,
        matched_criteria=[str(c) for c in (matched_criteria or [])],
    )
    return {"success": True, "job_id": ctx.job_id}


def _submit_proposal(ctx: RunContext, *, proposal: str, notes_for_operator: str | None = None) -> dict:
    """Record the writer's draft proposal for this run's job."""
    proposal = (proposal or "").strip()
    if not MIN_PROPOSAL_CHARS <= len(proposal) <= MAX_PROPOSAL_CHARS:
        return {
            "success": False,
            "error": f"proposal must be {MIN_PROPOSAL_CHARS}-{MAX_PROPOSAL_CHARS} characters (got {len(proposal)})",
        }
    words = len(proposal.split())
    if words >= MAX_PROPOSAL_WORDS:
        return {
            "success": False,
            "error": f"proposal must stay below {MAX_PROPOSAL_WORDS} words (got {words}); shorten it and resubmit",
        }
    ctx.result.update(proposal=proposal, notes_for_operator=(notes_for_operator or "").strip() or None)
    return {"success": True, "job_id": ctx.job_id}


# role -> one entry per tool the model may call — (name, description, JSON schema, handler).
# The handler takes (ctx, **arguments) and returns a JSON-serialisable dict.
TOOL_SPECS: dict[str, list[tuple[str, str, dict[str, Any], Callable[..., dict]]]] = {
    "screener": [
        (
            "submit_screening",
            "Submit your verdict on the job. Call exactly once, after deciding.",
            {
                "type": "object",
                "properties": {
                    "suitable": {"type": "boolean", "description": "true if the operator should apply"},
                    "score": {"type": "integer", "minimum": 0, "maximum": 100, "description": "fit, 0-100"},
                    "reasons": {
                        "type": "string",
                        "maxLength": MAX_REASONS_CHARS,
                        "description": "why, in one or two sentences, citing the criteria",
                    },
                    "matched_criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "short names of the criteria the job meets",
                    },
                },
                "required": ["suitable", "score", "reasons"],
            },
            _submit_screening,
        )
    ],
    "writer": [
        (
            "submit_proposal",
            f"Submit the finished draft proposal. Call exactly once, with the full text"
            f" (below {MAX_PROPOSAL_WORDS} words).",
            {
                "type": "object",
                "properties": {
                    "proposal": {
                        "type": "string",
                        "minLength": MIN_PROPOSAL_CHARS,
                        "maxLength": MAX_PROPOSAL_CHARS,
                        "description": "the proposal text, ready to paste into Upwork",
                    },
                    "notes_for_operator": {
                        "type": "string",
                        "description": (
                            "optional: what the operator must check before sending, as a few short points."
                            " No heading: it is shown under 'Check before sending'."
                        ),
                    },
                },
                "required": ["proposal"],
            },
            _submit_proposal,
        )
    ],
}


def _wrap(name: str, handler: Callable[..., dict], ctx: RunContext):
    """Adapt a plain handler into the SDK's @tool coroutine contract, with the never-raise guard."""

    async def run(args: dict[str, Any]) -> dict:
        try:
            result = handler(ctx, **args)
        except Exception as exc:  # noqa: BLE001 — a raising tool would kill the session, see module docstring.
            result = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}

    return functools.wraps(handler)(run)


def build_server(ctx: RunContext):
    """Build the in-process MCP server exposing ``ctx.role``'s tools, bound to ``ctx``."""
    handlers = [
        tool(name, description, schema)(_wrap(name, handler, ctx))
        for name, description, schema, handler in TOOL_SPECS[ctx.role]
    ]
    return create_sdk_mcp_server(name=SERVER_NAME, version="0.1.0", tools=handlers)


def tool_names() -> set[str]:
    """Short names of every declared tool — used by the guard to classify a tool call."""
    return {spec[0] for specs in TOOL_SPECS.values() for spec in specs}
