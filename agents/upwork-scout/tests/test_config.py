"""The config contract: it must fail loudly at startup rather than half-load."""

import copy

import pytest
import yaml

from agent.config import AgentConfig, AgentConfigError

BASE = {
    "agent": {"allow_writes": False},
    "screener": {"model": "claude-sonnet-5", "system_prompt": "screen"},
    "writer": {"model": "claude-opus-5", "system_prompt": "write"},
    "settings": {
        "apify": {
            "actor_id": "actor",
            "defaults_input": {"maxResults": 10, "sort": "recency"},
            "searches": [{"name": "one", "run_input": {"query": "ai agent"}}],
        }
    },
}


def _cfg(**overrides):
    data = copy.deepcopy(BASE)
    for dotted, value in overrides.items():
        node = data
        *path, last = dotted.split(".")
        for key in path:
            node = node.setdefault(key, {})
        node[last] = value
    return data


def test_loads_the_committed_config():
    """The config shipped with the agent must always be loadable — CI ships it verbatim."""
    cfg = AgentConfig.load()
    assert cfg.screener.system_prompt and cfg.writer.system_prompt
    assert cfg.apify.searches
    assert all(int(s.run_input["maxResults"]) <= 10 for s in cfg.apify.searches)


def test_missing_file_is_rejected(tmp_path):
    with pytest.raises(AgentConfigError, match="not found"):
        AgentConfig.load(tmp_path / "nope.yaml")


def test_load_from_file(tmp_path):
    path = tmp_path / "agent_config.yaml"
    path.write_text(yaml.safe_dump(BASE))
    assert AgentConfig.load(path).screener.model == "claude-sonnet-5"


@pytest.mark.parametrize("role", ["screener", "writer"])
def test_each_role_is_required(role):
    data = _cfg()
    del data[role]
    with pytest.raises(AgentConfigError, match=role):
        AgentConfig.from_dict(data)


def test_prompt_file_is_relative_to_the_config(tmp_path):
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "writer.txt").write_text("Write well.\n")
    data = _cfg()
    data["writer"] = {"model": "m", "system_prompt_file": "prompts/writer.txt"}
    path = tmp_path / "agent_config.yaml"
    path.write_text(yaml.safe_dump(data))
    assert AgentConfig.load(path).writer.system_prompt == "Write well."


def test_missing_prompt_file_fails_at_load(tmp_path):
    data = _cfg()
    data["writer"] = {"model": "m", "system_prompt_file": "prompts/nope.txt"}
    with pytest.raises(AgentConfigError, match="system_prompt_file not found"):
        AgentConfig.from_dict(data, base_dir=tmp_path)


def test_prompt_inline_and_file_together_is_rejected():
    with pytest.raises(AgentConfigError, match="not both"):
        AgentConfig.from_dict(_cfg(**{"writer.system_prompt_file": "prompts/writer.txt"}))


def test_effort_is_validated_and_optional():
    assert AgentConfig.from_dict(_cfg()).writer.effort is None
    assert AgentConfig.from_dict(_cfg(**{"writer.effort": "max"})).writer.effort == "max"
    with pytest.raises(AgentConfigError, match="writer.effort"):
        AgentConfig.from_dict(_cfg(**{"writer.effort": "extreme"}))


def test_role_prompt_is_required():
    with pytest.raises(AgentConfigError, match="writer.system_prompt"):
        AgentConfig.from_dict(_cfg(**{"writer.system_prompt": " "}))


def test_write_gate_defaults_closed():
    data = _cfg()
    del data["agent"]
    assert AgentConfig.from_dict(data).allow_writes is False


def test_defaults_merge_under_search_input():
    search = AgentConfig.from_dict(_cfg()).apify.searches[0]
    assert search.run_input == {"maxResults": 10, "sort": "recency", "query": "ai agent"}
    assert search.state_key == "upwork-scout-one"


def test_state_suffix_separates_a_local_run(monkeypatch):
    monkeypatch.setenv("APIFY_STATE_SUFFIX", "local")
    assert AgentConfig.from_dict(_cfg()).apify.searches[0].state_key == "upwork-scout-one-local"
    monkeypatch.setenv("APIFY_STATE_SUFFIX", "Not A Slug")
    with pytest.raises(AgentConfigError, match="APIFY_STATE_SUFFIX"):
        AgentConfig.from_dict(_cfg())


def test_max_results_above_ten_is_rejected():
    data = _cfg(**{"settings.apify.searches": [{"name": "one", "run_input": {"query": "x", "maxResults": 11}}]})
    with pytest.raises(AgentConfigError, match="maxResults"):
        AgentConfig.from_dict(data)


def test_duplicate_search_names_are_rejected():
    searches = [{"name": "one", "run_input": {"query": "a"}}, {"name": "one", "run_input": {"query": "b"}}]
    with pytest.raises(AgentConfigError, match="duplicate"):
        AgentConfig.from_dict(_cfg(**{"settings.apify.searches": searches}))


def test_search_needs_query_or_url():
    with pytest.raises(AgentConfigError, match="searchUrl"):
        AgentConfig.from_dict(_cfg(**{"settings.apify.searches": [{"name": "one", "run_input": {}}]}))


def test_search_name_must_be_a_slug():
    with pytest.raises(AgentConfigError, match="slug"):
        AgentConfig.from_dict(_cfg(**{"settings.apify.searches": [{"name": "Bad Name", "run_input": {"query": "a"}}]}))


def test_allow_writes_requires_a_chat():
    with pytest.raises(AgentConfigError, match="chat_id"):
        AgentConfig.from_dict(_cfg(**{"agent.allow_writes": True}))


def test_unknown_prefilter_key_is_rejected():
    with pytest.raises(AgentConfigError, match="prefilter"):
        AgentConfig.from_dict(_cfg(**{"settings.prefilter": {"min_budget_typo": 5}}))


def test_prompt_sha_tracks_prompt_text():
    a = AgentConfig.from_dict(_cfg()).screener.prompt_sha
    b = AgentConfig.from_dict(_cfg(**{"screener.system_prompt": "screen v2"})).screener.prompt_sha
    assert a != b


def _url_search(query):
    from urllib.parse import quote

    return [
        {"name": "one", "run_input": {"searchUrl": f"https://www.upwork.com/nx/search/jobs/?q={quote(query)}&t=0,1"}}
    ]


def test_query_over_80_words_is_rejected():
    """Upwork silently returns 0 above ~90 words; the measured failure was 49 terms / 93 words."""
    terms = " OR ".join([f'"term{i} word"' for i in range(44)] + [f'"single{i}"' for i in range(5)])
    with pytest.raises(AgentConfigError, match="93 words"):
        AgentConfig.from_dict(_cfg(**{"settings.apify.searches": _url_search(terms)}))
    with pytest.raises(AgentConfigError, match="81 words"):
        AgentConfig.from_dict(_cfg(**{"settings.apify.searches": [{"name": "q", "run_input": {"query": "w " * 81}}]}))


def test_query_words_count_hyphen_and_slash_parts():
    from agent.config import query_words

    assert query_words('"multi-agent" OR "ai/ml" OR ("rag")') == 5
    cfg = AgentConfig.from_dict(_cfg(**{"settings.apify.searches": _url_search(" OR ".join(['"a b"'] * 40))}))
    assert cfg.apify.searches


def test_committed_queries_stay_under_the_limit():
    from agent.config import MAX_QUERY_WORDS, query_words, search_query

    for search in AgentConfig.load().apify.searches:
        assert 0 < query_words(search_query(search.run_input)) <= MAX_QUERY_WORDS
