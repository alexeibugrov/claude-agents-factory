"""The agent's tool surface: in-process MCP tools bound to one :class:`RunContext`.

Two rules hold for every tool in the factory:

1. **Bind, don't globalise.** ``build_server(ctx)`` closes over the run's context so concurrent
   runs cannot cross-contaminate each other's state.
2. **Never raise.** A raising ``@tool`` handler tears down the Claude session, losing the whole
   run. Every failure degrades to ``{"success": False, "error": ...}`` instead, which the model
   can read and react to, and which the loop can report.

Tools are addressed by the model as ``mcp__<SERVER_NAME>__<tool name>``.
"""

from __future__ import annotations

import functools
import json
from typing import Any, Callable

from claude_agent_sdk import create_sdk_mcp_server, tool

from agent.context import RunContext

SERVER_NAME = "agent"

# TEMPLATE: one entry per tool the model may call — (name, description, JSON schema, handler).
# The handler takes (ctx, **arguments) and returns a JSON-serialisable dict.
TOOL_SPECS: list[tuple[str, str, dict[str, Any], Callable[..., dict]]] = []


def _echo(ctx: RunContext, *, text: str) -> dict:
    """Placeholder tool proving the wiring end to end. Replace it with the agent's real tools."""
    return {"success": True, "run_id": ctx.run_id, "echo": text}


TOOL_SPECS.append(
    (
        "echo",
        "Echo a string back. Placeholder tool — replace with this agent's real capabilities.",
        {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Text to echo back"}},
            "required": ["text"],
        },
        _echo,
    )
)


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
    """Build the in-process MCP server exposing this agent's tools, bound to ``ctx``."""
    handlers = [
        tool(name, description, schema)(_wrap(name, handler, ctx)) for name, description, schema, handler in TOOL_SPECS
    ]
    return create_sdk_mcp_server(name=SERVER_NAME, version="0.1.0", tools=handlers)


def tool_names() -> set[str]:
    """Short names of every declared tool — used by the guard to classify a tool call."""
    return {spec[0] for spec in TOOL_SPECS}
