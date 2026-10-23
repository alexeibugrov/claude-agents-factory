"""Config-gated safety veto — a sanctioned ``PreToolUse`` deny hook.

This is the factory's standard pattern for "the agent may read freely, but must not change the
world until someone says so". It denies the tools listed in :data:`WRITE_TOOLS` while
``agent.allow_writes`` is false, and goes inert when it is true — so enabling writes is a config
flip and a redeploy of that config, never a code change.

It is a deliberate guard, not a workaround, and `/task-review` should treat it as sanctioned.
Note it holds even under ``permission_mode="dontAsk"``: the permission mode auto-approves tools,
the hook still vetoes them.
"""

from __future__ import annotations

import logging

from claude_agent_sdk import HookJSONOutput, HookMatcher

logger = logging.getLogger(__name__)

# TEMPLATE: list the tools that create or mutate state. Reads and pure computation stay out —
# they are always allowed, which is what makes the agent useful while writes are still gated.
WRITE_TOOLS: set[str] = set()

_DENY_REASON = (
    "write gate: a state-changing tool was blocked while agent.allow_writes=false. "
    "Set allow_writes: true in agent_config.yaml to permit it."
)


def build_write_gate(*, allow_writes: bool) -> HookMatcher:
    """A ``PreToolUse`` matcher that denies write tools unless ``allow_writes`` (else a no-op)."""

    async def gate(input_data, tool_use_id, context) -> HookJSONOutput:  # HookCallback signature
        if allow_writes:
            return {}
        tool_name = (input_data.get("tool_name") or "") if isinstance(input_data, dict) else ""
        if not tool_name:
            # Safety-critical: an empty name here means the hook payload shape changed (an SDK
            # upgrade). Surface it rather than failing open. Logs keys only, never values.
            logger.warning(
                "write gate: empty tool_name in PreToolUse input (shape changed?); keys=%s",
                list(input_data) if isinstance(input_data, dict) else type(input_data).__name__,
            )
        if tool_name.split("__")[-1] in WRITE_TOOLS:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": _DENY_REASON,
                }
            }
        return {}

    return HookMatcher(hooks=[gate])
