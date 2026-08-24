"""The write gate is the agent's last line of defence; test it directly, not through the model."""

import pytest

from agent.guards import WRITE_TOOLS, build_write_gate

DENY = "deny"


async def _decide(matcher, tool_name):
    return await matcher.hooks[0]({"tool_name": tool_name}, "use-1", None)


async def test_write_tool_denied_when_writes_disallowed():
    if not WRITE_TOOLS:
        pytest.skip("this agent declares no write tools yet")
    gate = build_write_gate(allow_writes=False)
    out = await _decide(gate, f"mcp__agent__{sorted(WRITE_TOOLS)[0]}")
    assert out["hookSpecificOutput"]["permissionDecision"] == DENY


async def test_read_tool_always_allowed():
    gate = build_write_gate(allow_writes=False)
    assert await _decide(gate, "mcp__agent__echo") == {}


async def test_gate_is_inert_when_writes_allowed():
    gate = build_write_gate(allow_writes=True)
    for name in WRITE_TOOLS or {"echo"}:
        assert await _decide(gate, f"mcp__agent__{name}") == {}
