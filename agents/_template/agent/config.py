"""Parse the committed, secret-free ``agent_config.yaml`` into an :class:`AgentConfig`.

Secrets are deliberately absent from this file and from the image: they arrive as environment
variables from the gitignored ``.env.<agent>`` on the VM. The config carries only what is safe
to version — model, limits, the system prompt, and the agent's own knobs.

Loading fails fast. A missing model or an unparseable file should stop the container at startup,
where it is obvious, rather than surface as a confusing failure on the first real request.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# The compose file bind-mounts the config here; AGENT_CONFIG overrides it so one image can serve
# several stacks (e.g. a dev and a prod variant that differ only by config).
_DEFAULT_CONFIG = Path(__file__).parent.parent / "agent_config.yaml"


class AgentConfigError(RuntimeError):
    """Raised when ``agent_config.yaml`` is missing, unparseable, or incomplete."""


@dataclass(frozen=True)
class AgentConfig:
    model: str
    system_prompt: str
    fallback_model: str | None = None
    max_turns: int = 15
    max_budget_usd: float | None = None
    allow_writes: bool = False
    settings: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "AgentConfig":
        cfg_path = Path(path or os.environ.get("AGENT_CONFIG") or _DEFAULT_CONFIG)
        if not cfg_path.is_file():
            raise AgentConfigError(f"agent config not found: {cfg_path}")
        try:
            raw = yaml.safe_load(cfg_path.read_text()) or {}
        except yaml.YAMLError as exc:
            raise AgentConfigError(f"agent config is not valid YAML: {cfg_path}: {exc}") from exc

        agent = raw.get("agent") or {}
        model = agent.get("model")
        if not model:
            raise AgentConfigError(f"agent.model is required in {cfg_path}")
        prompt = (raw.get("system_prompt") or "").strip()
        if not prompt:
            raise AgentConfigError(f"system_prompt is required in {cfg_path}")

        return cls(
            model=model,
            system_prompt=prompt,
            fallback_model=agent.get("fallback_model"),
            max_turns=int(agent.get("max_turns", 15)),
            max_budget_usd=agent.get("max_budget_usd"),
            allow_writes=bool(agent.get("allow_writes", False)),
            settings=raw.get("settings") or {},
        )
