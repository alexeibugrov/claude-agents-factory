"""The write gate is the agent's last line of defence; test it directly, not through the model."""

import logging

import pytest

from agent.guards import WRITE_TOOLS, build_write_gate, delivery_allowed
from agent.tools import tool_names

DENY = "deny"


async def _decide(matcher, tool_name):
    return await matcher.hooks[0]({"tool_name": tool_name}, "use-1", None)


def test_model_tools_are_pure_so_write_tools_is_empty():
    """Both submit tools only record on RunContext; a new state-changing tool must be listed."""
    assert WRITE_TOOLS == set()
    assert tool_names() == {"submit_screening", "submit_proposal"}


async def test_write_tool_denied_when_writes_disallowed():
    if not WRITE_TOOLS:
        pytest.skip("this agent declares no write tools")
    gate = build_write_gate(allow_writes=False)
    out = await _decide(gate, f"mcp__agent__{sorted(WRITE_TOOLS)[0]}")
    assert out["hookSpecificOutput"]["permissionDecision"] == DENY


async def test_read_tool_always_allowed():
    gate = build_write_gate(allow_writes=False)
    assert await _decide(gate, "mcp__agent__submit_screening") == {}


async def test_gate_is_inert_when_writes_allowed():
    gate = build_write_gate(allow_writes=True)
    for name in WRITE_TOOLS or {"submit_proposal"}:
        assert await _decide(gate, f"mcp__agent__{name}") == {}


def test_delivery_suppressed_and_logged_when_writes_off(caplog):
    with caplog.at_level(logging.INFO):
        assert delivery_allowed(allow_writes=False, job_id="123") is False
    assert "WRITE GATE: delivery suppressed job=123" in caplog.text


def test_delivery_allowed_when_writes_on():
    assert delivery_allowed(allow_writes=True, job_id="123") is True
