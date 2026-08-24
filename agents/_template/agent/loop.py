"""One agent run: a single ``query()`` against the Claude Agent SDK, reduced to a result dict.

Each run is stateless — a fresh in-process tool server bound to this run's context, no session
carried between runs. That is what makes a crashed or retried run harmless.

The options here are the factory's default posture and are worth understanding before changing:

``tools=[]``                disables every BUILT-IN tool (file access, bash, web). The agent gets
                            exactly the tools declared in :mod:`agent.tools` and nothing else.
``setting_sources=[]``      ignores any ``.claude/`` config and MCP servers on disk, so the running
                            agent can never inherit the developer machine's tooling.
``permission_mode``         "dontAsk" auto-approves the declared tools — there is no human at the
                            other end of a container. The write gate still vetoes; see guards.py.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

from agent.config import AgentConfig
from agent.context import RunContext
from agent.guards import build_write_gate
from agent.tools import SERVER_NAME, build_server

logger = logging.getLogger(__name__)


def _parse_tool_result(content: Any) -> Any:
    """Pull the JSON payload our tool handlers emit out of a ToolResultBlock.content shape."""
    payload = content
    if isinstance(payload, list) and payload:
        first = payload[0]
        text = first.get("text") if isinstance(first, dict) else getattr(first, "text", None)
        if text is not None:
            payload = text
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return {"raw": payload}
    return payload


async def run_once(prompt: str, ctx: RunContext, cfg: AgentConfig) -> dict:
    """Run one request through the agent and return a structured result.

    Never raises: a failed run is reported as ``status="ERROR"`` with the reason, because the
    caller is a long-lived loop that must survive one bad request.
    """
    options_kwargs: dict[str, Any] = dict(
        system_prompt=cfg.system_prompt,
        tools=[],
        mcp_servers={SERVER_NAME: build_server(ctx)},
        allowed_tools=[f"mcp__{SERVER_NAME}__*"],
        permission_mode="dontAsk",
        model=cfg.model,
        max_turns=cfg.max_turns,
        setting_sources=[],
        hooks={"PreToolUse": [build_write_gate(allow_writes=cfg.allow_writes)]},
    )
    if cfg.fallback_model:
        options_kwargs["fallback_model"] = cfg.fallback_model
    if cfg.max_budget_usd is not None:
        options_kwargs["max_budget_usd"] = cfg.max_budget_usd

    started = time.time()
    text_parts: list[str] = []
    calls: list[dict] = []
    results: dict[str, Any] = {}
    result_msg: ResultMessage | None = None
    raised: str | None = None

    logger.info("run %s start: model=%s max_turns=%s", ctx.run_id, cfg.model, cfg.max_turns)
    try:
        async for msg in query(prompt=prompt, options=ClaudeAgentOptions(**options_kwargs)):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, ToolUseBlock):
                        short = (block.name or "").split("__")[-1]
                        calls.append({"id": block.id, "name": short, "input": block.input})
                        logger.info("run %s tool call: %s args=%s", ctx.run_id, short, block.input)
                    elif isinstance(block, TextBlock) and block.text.strip():
                        text_parts.append(block.text)
                        logger.info("run %s assistant: %s", ctx.run_id, block.text)
            elif isinstance(msg, UserMessage):
                for block in msg.content if isinstance(msg.content, list) else []:
                    if isinstance(block, ToolResultBlock):
                        results[block.tool_use_id] = _parse_tool_result(block.content)
            elif isinstance(msg, ResultMessage):
                result_msg = msg
    except Exception as exc:  # noqa: BLE001 — see docstring: the caller loop must survive this.
        raised = f"{type(exc).__name__}: {exc}"
        logger.warning("run %s raised: %s", ctx.run_id, raised)

    executions = [{"tool": c["name"], "args": c["input"], "result": results.get(c["id"], {})} for c in calls]

    if raised:
        status, error = "ERROR", raised
    elif result_msg is None:
        status, error = "ERROR", "no ResultMessage from query()"
    elif result_msg.is_error or (result_msg.subtype and result_msg.subtype != "success"):
        status, error = "ERROR", f"agent did not complete (subtype={result_msg.subtype})"
    else:
        status, error = "COMPLETED", None

    if status != "COMPLETED":
        # A greppable marker so journald-based alerting has a single string to watch for.
        logger.warning("AGENT ALERT run=%s status=%s error=%s", ctx.run_id, status, error)

    return {
        "run_id": ctx.run_id,
        "status": status,
        "error": error,
        "content": "\n".join(text_parts) or None,
        "tool_executions": executions,
        "duration_s": round(time.time() - started, 2),
        "cost_usd": getattr(result_msg, "total_cost_usd", None),
        "num_turns": getattr(result_msg, "num_turns", None),
    }
