"""Submit tools: validate, record on the run's context, and never raise."""

import json

from agent.context import RunContext
from agent.tools import TOOL_SPECS, _submit_proposal, _submit_screening, _wrap


def _ctx(role="screener"):
    return RunContext(run_id="r1", job_id="j1", role=role)


def test_screening_recorded_on_context():
    ctx = _ctx()
    out = _submit_screening(ctx, suitable=True, score=80, reasons="fits", matched_criteria=["python"])
    assert out == {"success": True, "job_id": "j1"}
    assert ctx.result == {"suitable": True, "score": 80, "reasons": "fits", "matched_criteria": ["python"]}


def test_screening_rejects_out_of_range_score():
    ctx = _ctx()
    assert _submit_screening(ctx, suitable=True, score=101, reasons="x")["success"] is False
    assert ctx.result == {}


def test_screening_rejects_empty_reasons():
    assert _submit_screening(_ctx(), suitable=False, score=10, reasons="  ")["success"] is False


def test_proposal_length_bounds():
    ctx = _ctx("writer")
    assert _submit_proposal(ctx, proposal="too short")["success"] is False
    assert _submit_proposal(ctx, proposal="x" * 400, notes_for_operator="check rate")["success"] is True
    assert ctx.result["notes_for_operator"] == "check rate"


def test_proposal_must_stay_below_350_words():
    ctx = _ctx("writer")
    result = _submit_proposal(ctx, proposal="word " * 350)
    assert result["success"] is False and "got 350" in result["error"]
    assert _submit_proposal(ctx, proposal="word " * 349)["success"] is True


async def test_wrapper_never_raises_on_bad_arguments():
    run = _wrap("submit_screening", _submit_screening, _ctx())
    out = await run({"unexpected": 1})
    payload = json.loads(out["content"][0]["text"])
    assert payload["success"] is False and "TypeError" in payload["error"]


def test_each_role_exposes_only_its_own_tool():
    assert [s[0] for s in TOOL_SPECS["screener"]] == ["submit_screening"]
    assert [s[0] for s in TOOL_SPECS["writer"]] == ["submit_proposal"]
