"""The config contract: it must fail loudly at startup rather than half-load."""

import pytest
import yaml

from agent.config import AgentConfig, AgentConfigError


def _write(tmp_path, data):
    path = tmp_path / "agent_config.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_loads_the_committed_config():
    """The config shipped with the agent must always be loadable — CI ships it verbatim."""
    cfg = AgentConfig.load()
    assert cfg.model
    assert cfg.system_prompt


def test_missing_model_is_rejected(tmp_path):
    path = _write(tmp_path, {"agent": {}, "system_prompt": "hi"})
    with pytest.raises(AgentConfigError, match="agent.model"):
        AgentConfig.load(path)


def test_missing_prompt_is_rejected(tmp_path):
    path = _write(tmp_path, {"agent": {"model": "claude-opus-5"}})
    with pytest.raises(AgentConfigError, match="system_prompt"):
        AgentConfig.load(path)


def test_missing_file_is_rejected(tmp_path):
    with pytest.raises(AgentConfigError, match="not found"):
        AgentConfig.load(tmp_path / "nope.yaml")


def test_write_gate_defaults_closed(tmp_path):
    """A config that forgets allow_writes must NOT end up permitting writes."""
    path = _write(tmp_path, {"agent": {"model": "claude-opus-5"}, "system_prompt": "hi"})
    assert AgentConfig.load(path).allow_writes is False
