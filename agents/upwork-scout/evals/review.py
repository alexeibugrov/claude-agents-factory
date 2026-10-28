"""The operator's review, read back from Promptfoo: only a 👍/👎 (a ``human`` component) is a verdict."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.common import FEEDBACK_DIR, HUMAN, RUNS_DIR, EvalError, export_eval

FORMAT = "upwork-scout-writer-feedback/v1"
SCREENER_FORMAT = "upwork-scout-screener-feedback/v1"
APPROVED, REJECTED, UNREVIEWED, ERROR = "approved", "rejected", "unreviewed", "error"
_HIGHLIGHT = "!highlight"
_ERROR_REASON = 2  # Promptfoo ResultFailureReason.ERROR: the provider failed, nothing to review
# Submits per draft at or above this, or any failed run, is flagged: each retry is a paid generation.
HEAVY_SUBMITS = 3
# A screener review comment starts with the operator's own mark: "2 — mostly frontend".
_MARK = re.compile(r"^\s*([0-5])(?![\d.])")


def _results(export: dict[str, Any]) -> list[dict[str, Any]]:
    return export["results"]["results"]


def experiment(export: dict[str, Any]) -> dict[str, Any]:
    exp = ((export.get("config") or {}).get("metadata") or {}).get("experiment")
    if not exp:
        raise EvalError(
            f"eval {export.get('evalId')} was not started by `python -m evals run` (no experiment metadata)"
        )
    return exp


def review_of(result: dict[str, Any]) -> dict[str, Any]:
    grading = result.get("gradingResult") or {}
    comment = (grading.get("comment") or "").strip()
    highlighted = comment.startswith(_HIGHLIGHT)
    if highlighted:
        comment = comment[len(_HIGHLIGHT) :].strip()
    human = next(
        (c for c in grading.get("componentResults") or [] if (c.get("assertion") or {}).get("type") == HUMAN), None
    )
    if result.get("failureReason") == _ERROR_REASON:
        verdict = ERROR
    elif human is None:
        verdict = UNREVIEWED
    else:
        verdict = APPROVED if human.get("pass") else REJECTED
    return {
        "verdict": verdict,
        "score": human.get("score") if human else None,
        "comment": comment or None,
        "highlighted": highlighted,
    }


def operator_score(review: dict[str, Any], agent_score: int | None) -> int | None:
    """The screener mark the operator stands by: the agent's on a 👍, the comment's leading digit on a 👎."""
    if review["verdict"] == APPROVED:
        return agent_score
    match = _MARK.match(review["comment"] or "")
    return int(match.group(1)) if review["verdict"] == REJECTED and match else None


def case_record(result: dict[str, Any]) -> dict[str, Any]:
    meta = (result.get("response") or {}).get("metadata") or {}
    test_meta = (result.get("testCase") or {}).get("metadata") or {}
    case_vars = result.get("vars") or {}
    record = {
        "case_id": case_vars.get("case_id") or test_meta.get("case_id"),
        "result_id": result.get("id"),
        "repeat_index": (result.get("metadata") or {}).get("repeatIndex"),
        "prompt_sha": meta.get("prompt_sha"),
        "input": {
            "operator_instructions": case_vars.get("operator_instructions") or None,
            # Exactly what the writer received as its user message, job text included.
            "user_message": meta.get("user_message"),
        },
        "source": {"job_source": test_meta.get("job_source"), "reference": test_meta.get("reference") or None},
        "case_metadata": {k: v for k, v in test_meta.items() if k not in ("case_id", "job_source", "reference")},
        "output": {
            "proposal": meta.get("proposal"),
            "notes_for_operator": meta.get("notes_for_operator"),
            "words": meta.get("words"),
            "error": result.get("error") if result.get("failureReason") == _ERROR_REASON else None,
            "model": meta.get("model"),
            "submits": meta.get("submit_attempts"),
            "failed_runs": len(meta.get("failed_attempts") or []),
            "duration_s": meta.get("duration_s"),
        },
        "review": review_of(result),
    }
    if meta.get("role") == "screener":
        record["output"].update(score=meta.get("score"), reason=meta.get("reason"))
        record["review"]["operator_score"] = operator_score(record["review"], meta.get("score"))
    return record


def summarize(cases: list[dict[str, Any]]) -> dict[str, int]:
    counts = {v: 0 for v in (APPROVED, REJECTED, UNREVIEWED, ERROR)}
    for c in cases:
        counts[c["review"]["verdict"]] += 1
    counts["total"] = len(cases)
    counts["commented"] = sum(1 for c in cases if c["review"]["comment"])
    return counts


def load(eval_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], Path]:
    """Export the eval from Promptfoo's database (latest saved ratings) next to its run record."""
    tmp = RUNS_DIR / "_exports" / f"{eval_id.replace(':', '-')}.json"
    export = export_eval(eval_id, tmp)
    exp = experiment(export)
    final = RUNS_DIR / exp["run_id"] / "promptfoo-export.json"
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp.replace(final)
    cases = sorted(
        (case_record(r) for r in _results(export)), key=lambda c: (c["case_id"] or "", c["repeat_index"] or 0)
    )
    return export, cases, final


def _heavy(c: dict[str, Any]) -> bool:
    return (c["output"]["submits"] or 0) >= HEAVY_SUBMITS or c["output"]["failed_runs"] > 0


def _retry_text(c: dict[str, Any]) -> str:
    return f"{c['output']['submits'] or 0} submits, {c['output']['failed_runs']} failed runs"


def _indented(text: str, prefix: str) -> list[str]:
    return [prefix + line for line in text.strip().splitlines() if line.strip()]


def status_lines(eval_id: str) -> list[str]:
    export, cases, _ = load(eval_id)
    exp = experiment(export)
    s = summarize(cases)
    lines = [
        f"eval {export['evalId']}  run {exp['run_id']}",
        f"prompt {exp['prompt']['path']}@{exp['prompt']['sha']}"
        f"  dataset {exp['dataset']['id']}@{exp['dataset']['version']} ({exp['dataset']['split']})",
        f"{s['total']} outputs: {s[APPROVED]} approved, {s[REJECTED]} rejected, {s[UNREVIEWED]} unreviewed,"
        f" {s[ERROR]} errors; {s['commented']} with comments",
    ]
    heavy = [c for c in cases if _heavy(c)]
    if heavy:
        lines.append(f"retries: {len(heavy)} of {len(cases)} drafts needed {HEAVY_SUBMITS}+ submits or a fresh run")
        lines += [f"  {c['case_id']}: {_retry_text(c)}" for c in heavy]
    for c in cases:
        r = c["review"]
        if r["verdict"] in (UNREVIEWED, ERROR):
            note = " (has a comment, but no 👍/👎)" if r["comment"] else ""
            lines.append(f"  {r['verdict']:<10} {c['case_id']}{note}")
    if exp.get("role") == "screener":
        lines.append("")
        lines.append(f"{'case':<44} {'agent':<6} {'yours':<6} verdict")
        for c in cases:
            agent, yours = c["output"].get("score"), c["review"].get("operator_score")
            unmarked = c["review"]["verdict"] == REJECTED and yours is None
            flag = "  (👎 without a leading mark in the comment)" if unmarked else ""
            lines.append(f"{c['case_id']:<44} {_dash(agent):<6} {_dash(yours):<6} {c['review']['verdict']}{flag}")
    return lines


def _dash(value: Any) -> str:
    return "-" if value is None else str(value)


def feedback_package(eval_id: str, *, partial: bool = False, out: Path | None = None) -> tuple[Path, dict[str, Any]]:
    export, cases, export_path = load(eval_id)
    exp = experiment(export)
    s = summarize(cases)
    if s[UNREVIEWED] and not partial:
        missing = ", ".join(c["case_id"] for c in cases if c["review"]["verdict"] == UNREVIEWED)
        raise EvalError(
            f"{s[UNREVIEWED]} output(s) have no 👍/👎 yet: {missing}. Finish the review, or pass --partial"
            " to export anyway (unreviewed outputs are marked and the editor is told to ignore them)."
        )
    wrong = sorted({c["prompt_sha"] for c in cases if c["prompt_sha"] and c["prompt_sha"] != exp["prompt"]["sha"]})
    if wrong:
        raise EvalError(f"results carry prompt versions {wrong}, not the run's {exp['prompt']['sha']}")
    prompts = export["results"].get("prompts") or []
    package = {
        "format": SCREENER_FORMAT if exp.get("role") == "screener" else FORMAT,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "eval_id": export["evalId"],
        "experiment": exp,
        "prompt": {**exp["prompt"], "text": prompts[0]["raw"] if prompts else None},
        "summary": s,
        "cases": cases,
    }
    out = out or FEEDBACK_DIR / f"{exp['run_id']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(package, indent=2, ensure_ascii=False) + "\n")
    return out, package


def compare_lines(base_id: str, cand_id: str) -> list[str]:
    """Pair two evals by case id: verdicts, comments and length, base first."""
    exports = [load(base_id), load(cand_id)]
    exps = [experiment(e) for e, _, _ in exports]
    by_case = [{c["case_id"]: c for c in cases} for _, cases, _ in exports]
    lines = []
    for label, exp, (export, cases, _) in zip(("A", "B"), exps, exports, strict=True):
        s = summarize(cases)
        lines.append(
            f"{label}: {export['evalId']}  {exp['prompt']['path']}@{exp['prompt']['sha']}  {s[APPROVED]} approved,"
            f" {s[REJECTED]} rejected, {s[UNREVIEWED]} unreviewed, {s[ERROR]} errors"
        )
    if exps[0]["dataset"]["sha256"] != exps[1]["dataset"]["sha256"]:
        lines.append("WARNING: the two runs used different dataset contents; compare only the shared cases.")
    if exps[0]["agent"]["config_sha256"] != exps[1]["agent"]["config_sha256"]:
        lines.append("WARNING: agent_config.yaml differed between the runs; not only the prompt changed.")
    shared = sorted(set(by_case[0]) & set(by_case[1]))
    for label, (_, cases, _) in zip(("A", "B"), exports, strict=True):
        if len(cases) > len({c["case_id"] for c in cases}):
            lines.append(
                f"WARNING: {label} ran cases more than once (--repeat); only the last draft per case is compared."
            )
    only = sorted(set(by_case[0]) ^ set(by_case[1]))
    if only:
        lines.append(f"Not in both runs (skipped): {', '.join(only)}")
    lines.append("")
    # The screener's comparable number is its score; the writer's is the draft's length.
    size = "score" if exps[0].get("role") == "screener" else "words"
    lines.append(f"{'case':<44} {'A':<11} {'B':<11} {size + ' A/B':<10} submits A/B")
    for case_id in shared:
        a, b = by_case[0][case_id], by_case[1][case_id]
        mark = "  <- changed" if a["review"]["verdict"] != b["review"]["verdict"] else ""
        words = f"{_dash(a['output'].get(size))}/{_dash(b['output'].get(size))}"
        submits = f"{a['output']['submits'] or '-'}/{b['output']['submits'] or '-'}"
        verdicts = f"{a['review']['verdict']:<11} {b['review']['verdict']:<11}"
        lines.append(f"{case_id:<44} {verdicts} {words:<10} {submits}{mark}")
        for label, c in (("A", a), ("B", b)):
            if c["review"]["comment"]:
                lines.append(f"    {label}:")
                lines += _indented(c["review"]["comment"], "      ")
    return lines
