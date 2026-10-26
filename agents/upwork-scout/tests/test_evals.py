"""Eval tooling, offline: dataset parsing, prompt identity, verdicts from Promptfoo exports, editor checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.config import AgentConfig
from evals import dataset as datasets
from evals.common import AGENT_CONFIG, AGENT_DIR, EVALS_DIR, EvalError, live_prompt, prompt_problems, prompt_sha, rel
from evals.editor import check_submission, user_message
from evals.experiment import build_config, manifest
from evals.review import APPROVED, ERROR, REJECTED, UNREVIEWED, case_record, review_of

SMOKE = EVALS_DIR / "datasets" / "smoke.yaml"


def test_smoke_dataset_loads_and_is_labelled():
    ds = datasets.load(SMOKE)
    assert ds.split == "smoke"
    assert [c.id for c in ds.cases] == ["smoke-ai-agent-hourly", "smoke-terraform-fixed", "smoke-rag-questions"]
    assert all(c.job["_smoke_fixture"].startswith("SYNTHETIC") for c in ds.cases)
    assert ds.cases[2].operator_instructions.startswith("1. Which Azure")


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "d.yaml"
    path.write_text(body)
    return path


@pytest.mark.parametrize(
    "body, message",
    [
        ("dataset: {id: x, version: 1, split: train}\ncases: []", "split"),
        ("dataset: {id: x, split: tuning}\ncases: []", "version"),
        ("dataset: {id: x, version: 1, split: tuning}\ncases: []", "no cases"),
        (
            "dataset: {id: x, version: 1, split: tuning}\ncases:\n"
            "  - {id: a, job: {title: t, description: d}}\n  - {id: a, job: {title: t, description: d}}",
            "duplicate",
        ),
        ("dataset: {id: x, version: 1, split: tuning}\ncases:\n  - {id: a}", "exactly one"),
        ("dataset: {id: x, version: 1, split: tuning}\ncases:\n  - {id: a, job: {title: t}}", "description"),
    ],
)
def test_dataset_rejects_bad_files(tmp_path, body, message):
    with pytest.raises(EvalError, match=message):
        datasets.load(_write(tmp_path, body))


def test_dataset_sha_covers_fixture_contents(tmp_path):
    fixture = tmp_path / "job.json"
    fixture.write_text(json.dumps({"title": "t", "description": "d"}))
    path = _write(tmp_path, "dataset: {id: x, version: 1, split: tuning}\ncases:\n  - {id: a, job_file: job.json}")
    before = datasets.load(path).sha256
    fixture.write_text(json.dumps({"title": "t", "description": "changed"}))
    assert datasets.load(path).sha256 != before


def test_add_records_drops_personal_data(tmp_path):
    path = _write(tmp_path, "dataset: {id: x, version: 1, split: tuning}\ncases: []\n")
    record = {"jobId": "42", "title": "t", "description": "d", "contactEmail": "a@b.c", "extractedPhones": ["1"]}
    assert datasets.add_records(path, [record, record], tmp_path / "fx") == ["job-42"]
    ds = datasets.load(path)
    assert ds.cases[0].id == "job-42"
    assert "contactEmail" not in ds.cases[0].job and "extractedPhones" not in ds.cases[0].job


def test_prompt_identity_matches_production():
    text = live_prompt().read_text()
    assert prompt_sha(text) == AgentConfig.load(AGENT_CONFIG).writer.prompt_sha
    assert prompt_problems(text) == []


def test_every_writer_version_can_be_rerun():
    """Retired versions stay beside the live one, so any of them can be rerun for a comparison."""
    versions = sorted((AGENT_DIR / "prompts" / "writer").glob("v*.md"))
    assert live_prompt() in versions and len(versions) >= 2
    assert all(prompt_problems(v.read_text()) == [] for v in versions)


def test_prompt_problems_catch_promptfoo_rewrites():
    assert prompt_problems("a\n---\nb")
    assert prompt_problems("Hi {{name}}")
    assert prompt_problems("{% if x %}")
    assert prompt_problems("Hi {Name},") == []


def test_generated_config_runs_the_prompt_verbatim_and_marks_review_pending():
    ds = datasets.load(SMOKE)
    live = live_prompt()
    text = live.read_text()
    m = manifest("r1", live, text, ds, cache=False)
    cfg = build_config(m, text, ds, concurrency=2)
    assert cfg["prompts"] == [{"raw": text, "label": f"{rel(live)}@{prompt_sha(text)}"}]
    assert cfg["providers"][0]["config"]["prompt_sha"] == prompt_sha(text)
    assert cfg["metadata"]["experiment"]["dataset"]["sha256"] == ds.sha256
    assert "Awaiting human review" in cfg["defaultTest"]["assert"][0]["value"]
    assert [t["vars"]["case_id"] for t in cfg["tests"]] == [c.id for c in ds.cases]
    assert json.loads(cfg["tests"][0]["vars"]["job_record"])["jobId"] == "smoke-0001"


def _result(components, *, comment=None, failure=1, case="c1"):
    return {
        "id": "res-" + case,
        "vars": {"case_id": case, "operator_instructions": ""},
        "testCase": {"metadata": {"case_id": case, "job_source": "f.json", "reference": ""}},
        "response": {"metadata": {"prompt_sha": "abc", "proposal": "p", "words": 1, "user_message": "u"}},
        "failureReason": failure,
        "gradingResult": {"comment": comment, "componentResults": components},
    }


MARKER = {"pass": False, "assertion": {"type": "javascript"}}


def test_verdict_comes_only_from_the_human_component():
    human_pass = {"pass": True, "score": 1, "assertion": {"type": "human"}}
    human_fail = {"pass": False, "score": 0, "assertion": {"type": "human"}}
    assert review_of(_result([MARKER, human_pass]))["verdict"] == APPROVED
    assert review_of(_result([MARKER, human_fail], comment="too long"))["verdict"] == REJECTED
    # A comment without a thumb, or no rating at all, is not approval.
    assert review_of(_result([MARKER], comment="nice"))["verdict"] == UNREVIEWED
    assert review_of(_result([]))["verdict"] == UNREVIEWED
    assert review_of(_result([], failure=2))["verdict"] == ERROR


def test_highlight_prefix_is_stripped_from_comments():
    r = review_of(_result([MARKER], comment="!highlight check the rate"))
    assert r == {"verdict": UNREVIEWED, "score": None, "comment": "check the rate", "highlighted": True}


def _package(cases):
    return {
        "prompt": {"text": "old prompt", "path": "prompts/writer.md", "sha": "abc"},
        "experiment": {
            "prompt": {"path": "prompts/writer.md", "sha": "abc"},
            "dataset": {"id": "t", "version": "1", "split": "tuning"},
            "agent": {"writer": {"model": "m", "effort": "medium"}},
        },
        "summary": {"total": 2, "approved": 1, "rejected": 0, "unreviewed": 1, "error": 0},
        "cases": cases,
    }


def test_editor_submission_must_cite_reviewed_cases():
    approved = case_record(_result([MARKER, {"pass": True, "score": 1, "assertion": {"type": "human"}}], case="a"))
    unrated = case_record(_result([MARKER], case="b"))
    package = _package([approved, unrated])
    good = {
        "revised_prompt": "new prompt",
        "summary": "s",
        "changes": [{"change": "c", "rationale": "r", "cases": ["a"]}],
    }
    assert check_submission(good, package) == []
    assert check_submission({**good, "revised_prompt": "old prompt"}, package)
    assert check_submission({**good, "revised_prompt": "a\n---\nb"}, package)
    assert check_submission({**good, "changes": [{"change": "c", "rationale": "r", "cases": ["b"]}]}, package)
    assert check_submission({**good, "changes": [{"change": "c", "rationale": "r", "cases": ["zz"]}]}, package)
    assert check_submission({**good, "changes": []}, package)


def test_editor_message_carries_prompt_inputs_outputs_and_reviews():
    approved = case_record(
        _result(
            [MARKER, {"pass": True, "score": 1, "assertion": {"type": "human"}}], comment="keep the opening", case="a"
        )
    )
    text = user_message(_package([approved]))
    assert "<current_prompt>\nold prompt\n</current_prompt>" in text
    assert '<case id="a">' in text and '<review verdict="approved" score="1">\nkeep the opening' in text


def test_text_import_parses_the_submitted_proposals_source():
    from evals.textimport import parse

    jobs = parse(EVALS_DIR / "datasets" / "source" / "upwork-submitted-2026-10-24.txt")
    assert sorted(jobs) == list(range(1, 21))
    with_instructions = sorted(n for n, (_, case) in jobs.items() if case["operator_instructions"])
    assert with_instructions == [2, 7, 19]
    record, case = jobs[19]
    assert (record["jobType"], record["budgetAmount"]) == ("FIXED", 75.0)
    assert "SCREENING" not in record["description"] and "Budget:" not in record["description"]
    assert case["operator_instructions"].splitlines()[1].startswith("2. Please list any certifications")
    record, case = jobs[3]
    assert (record["hourlyBudgetMin"], record["hourlyBudgetMax"]) == (80.0, 130.0)
    assert case["metadata"]["questions"] == "in_description"
    assert record["description"].rstrip().endswith("one working session?")


def test_real_datasets_are_disjoint_and_keep_their_headers():
    tuning = datasets.load(EVALS_DIR / "datasets" / "tuning.yaml")
    validation = datasets.load(EVALS_DIR / "datasets" / "validation.yaml")
    assert (tuning.split, validation.split) == ("tuning", "validation")
    assert not {c.job["jobId"] for c in tuning.cases} & {c.job["jobId"] for c in validation.cases}
    assert len(tuning.cases) + len(validation.cases) == 20


def test_add_records_keeps_the_header_comment(tmp_path):
    path = _write(tmp_path, "# REAL data, keep me\ndataset: {id: x, version: 1, split: tuning}\ncases: []\n")
    datasets.add_records(path, [{"jobId": "1", "title": "t", "description": "d"}], tmp_path / "fx")
    assert path.read_text().startswith("# REAL data, keep me\n")


def test_next_version_follows_the_highest_existing_file():
    from evals.common import next_version

    nxt = next_version()
    existing = [int(p.stem[1:]) for p in nxt.parent.glob("v*.md")]
    assert nxt.name == f"v{max(existing) + 1}.md" and not nxt.exists()
