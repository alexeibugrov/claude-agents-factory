"""The prompt editor: one reviewed batch in, one candidate prompt out (candidates/<id>/), never adopted."""

from __future__ import annotations

import asyncio
import difflib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, create_sdk_mcp_server, query, tool

from evals.common import CANDIDATES_DIR, next_version, EVALS_DIR, EvalError, prompt_problems, prompt_sha, rel, settings
from evals.review import APPROVED, FORMAT, REJECTED

SERVER = "editor"
# Cited instead of a case id for a change the operator asked for directly (propose --note).
OPERATOR = "operator"
_REVIEWED = (APPROVED, REJECTED)

_CITED = {"type": "array", "items": {"type": "string"}, "description": "case ids from the batch"}
SCHEMA = {
    "type": "object",
    "properties": {
        "revised_prompt": {"type": "string", "description": "the complete new prompt text"},
        "summary": {"type": "string", "description": "two or three sentences: what changes and why"},
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "change": {"type": "string", "description": "what the prompt now says differently"},
                    "rationale": {"type": "string", "description": "the reusable rule inferred from the feedback"},
                    "cases": _CITED,
                },
                "required": ["change", "rationale", "cases"],
            },
        },
        "preserved": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"behavior": {"type": "string"}, "cases": _CITED},
                "required": ["behavior", "cases"],
            },
        },
        "conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"description": {"type": "string"}, "resolution": {"type": "string"}, "cases": _CITED},
                "required": ["description", "cases"],
            },
        },
        "beyond_prompt": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"issue": {"type": "string"}, "suggested_fix": {"type": "string"}, "cases": _CITED},
                "required": ["issue", "cases"],
            },
        },
    },
    "required": ["revised_prompt", "summary", "changes", "preserved", "conflicts", "beyond_prompt"],
}


def check_submission(args: dict[str, Any], package: dict[str, Any]) -> list[str]:
    """Problems with a submission, phrased for the editor model to fix and resubmit."""
    errors = []
    current = package["prompt"]["text"] or ""
    revised = (args.get("revised_prompt") or "").strip()
    if not revised:
        errors.append("revised_prompt is empty")
    elif revised == current.strip():
        errors.append("revised_prompt is identical to the current prompt")
    errors += [f"revised_prompt contains {p}" for p in prompt_problems(revised)] if revised else []
    all_ids = {c["case_id"] for c in package["cases"]}
    reviewed = {c["case_id"] for c in package["cases"] if c["review"]["verdict"] in _REVIEWED}
    if package.get("operator_note"):
        all_ids, reviewed = all_ids | {OPERATOR}, reviewed | {OPERATOR}
    if not args.get("changes"):
        errors.append("changes is empty: list every change with the cases behind it")
    for i, change in enumerate(args.get("changes") or []):
        cited = set(change.get("cases") or [])
        if not cited:
            errors.append(f"changes[{i}] cites no case")
        if cited - all_ids:
            errors.append(f"changes[{i}] cites unknown cases {sorted(cited - all_ids)}")
        elif cited and not cited & reviewed:
            errors.append(f"changes[{i}] cites only unreviewed or failed runs; a change needs a reviewed case")
    for key in ("preserved", "conflicts", "beyond_prompt"):
        for i, item in enumerate(args.get(key) or []):
            unknown = set(item.get("cases") or []) - all_ids
            if unknown:
                errors.append(f"{key}[{i}] cites unknown cases {sorted(unknown)}")
    return errors


def _block(tag: str, text: str | None) -> str:
    return f"<{tag}>\n{(text or '').strip()}\n</{tag}>"


def user_message(package: dict[str, Any]) -> str:
    exp, s = package["experiment"], package["summary"]
    parts = [
        f"CURRENT PROMPT ({exp['prompt']['path']}@{exp['prompt']['sha']})",
        _block("current_prompt", package["prompt"]["text"]),
        "",
        f"REVIEWED BATCH: dataset {exp['dataset']['id']}@{exp['dataset']['version']} ({exp['dataset']['split']}),"
        f" writer {exp['agent']['writer']['model']} effort {exp['agent']['writer']['effort']}."
        f" {s['total']} outputs: {s['approved']} approved, {s['rejected']} rejected,"
        f" {s['unreviewed']} unreviewed, {s['error']} errors.",
    ]
    for c in package["cases"]:
        r = c["review"]
        review = (
            f'<review verdict="{r["verdict"]}"' + (f' score="{r["score"]}"' if r["score"] is not None else "") + ">"
        )
        parts += [
            "",
            f'<case id="{c["case_id"]}">',
            _block("input", c["input"]["user_message"]),
            _block("proposal", c["output"]["proposal"] or f"(no proposal: {c['output']['error']})"),
            _block("notes_for_operator", c["output"]["notes_for_operator"]),
        ]
        if c["source"].get("reference"):
            parts.append(_block("reference_proposal", c["source"]["reference"]))
        parts += [f"{review}\n{r['comment'] or '(no comment)'}\n</review>", "</case>"]
    if package.get("operator_note"):
        parts += ["", _block("operator_directions", package["operator_note"])]
    parts += ["", "Propose one candidate prompt now and call submit_candidate exactly once."]
    return "\n".join(parts)


async def _ask(
    package: dict[str, Any], model: str, effort: str | None, max_turns: int, timeout_s: float
) -> dict[str, Any]:
    submitted: dict[str, Any] = {}

    async def submit(args: dict[str, Any]) -> dict[str, Any]:
        try:
            errors = check_submission(args, package)
        except Exception as exc:  # a raising tool would end the session; report instead.
            errors = [f"{type(exc).__name__}: {exc}"]
        if errors:
            result = {"success": False, "errors": errors}
        else:
            submitted.update(args)
            result = {"success": True}
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    server = create_sdk_mcp_server(
        name=SERVER,
        version="0.1.0",
        tools=[tool("submit_candidate", "Submit the one candidate prompt with its explained changes.", SCHEMA)(submit)],
    )
    options: dict[str, Any] = dict(
        system_prompt=(EVALS_DIR / "editor_prompt.txt").read_text(encoding="utf-8"),
        tools=[],  # no shell, files or web: the editor only reads the message and submits
        mcp_servers={SERVER: server},
        allowed_tools=[f"mcp__{SERVER}__submit_candidate"],
        permission_mode="dontAsk",
        model=model,
        max_turns=max_turns,
        setting_sources=[],
    )
    if effort:
        options["effort"] = effort
    result: ResultMessage | None = None
    async with asyncio.timeout(timeout_s):
        async for msg in query(prompt=user_message(package), options=ClaudeAgentOptions(**options)):
            if isinstance(msg, ResultMessage):
                result = msg
    if not submitted:
        subtype = getattr(result, "subtype", None)
        raise EvalError(f"the editor finished without an accepted submit_candidate (result: {subtype})")
    return submitted


def _changes_md(meta: dict[str, Any], proposal: dict[str, Any], current: str) -> str:
    def cited(item: dict[str, Any]) -> str:
        return ", ".join(item.get("cases") or []) or "-"

    lines = [
        f"# Candidate {meta['candidate_id']}",
        "",
        f"- Base prompt: `{meta['base_prompt']['path']}@{meta['base_prompt']['sha']}`",
        f"- Candidate prompt: `{meta['candidate_prompt']['path']}@{meta['candidate_prompt']['sha']}`",
        f"- From feedback: `{meta['feedback']['path']}` (eval `{meta['feedback']['eval_id']}`,"
        f" dataset `{meta['feedback']['dataset']}`, {meta['feedback']['split']})",
        *([f"- Operator directions: {meta['operator_note']}"] if meta.get("operator_note") else []),
        f"- Editor: `{meta['editor']['model']}`, effort `{meta['editor']['effort']}`",
        "- Status: **not adopted**. Run it on the same cases, compare, and adopt it by hand if it wins:",
        f"  `cp {meta['candidate_prompt']['path']} {meta['adopt_as']}`, then point"
        f" `writer.system_prompt_file` in agent_config.yaml at `{meta['adopt_as']}`.",
        "",
        "## Summary",
        "",
        proposal["summary"].strip(),
        "",
        "## Changes",
        "",
    ]
    lines += [
        f"1. {c['change'].strip()}\n   - Why: {c['rationale'].strip()}\n   - Cases: {cited(c)}"
        for c in proposal["changes"]
    ]
    for title, key, text_key, extra in (
        ("Preserved behaviour", "preserved", "behavior", None),
        ("Conflicting feedback", "conflicts", "description", "resolution"),
        ("Beyond the prompt", "beyond_prompt", "issue", "suggested_fix"),
    ):
        lines += ["", f"## {title}", ""]
        items = proposal.get(key) or []
        if not items:
            lines.append("None reported.")
        for item in items:
            more = f" {item[extra].strip()}" if extra and item.get(extra) else ""
            lines.append(f"- {item[text_key].strip()}{more} (cases: {cited(item)})")
    diff = difflib.unified_diff(
        current.strip().splitlines(),
        proposal["revised_prompt"].strip().splitlines(),
        fromfile=meta["base_prompt"]["path"],
        tofile=meta["candidate_prompt"]["path"],
        lineterm="",
    )
    lines += ["", "## Diff", "", "```diff", *diff, "```", ""]
    return "\n".join(lines)


def propose(
    feedback_path: Path,
    *,
    model: str | None = None,
    effort: str | None = None,
    allow_validation: bool = False,
    note: str | None = None,
) -> Path:
    package = json.loads(feedback_path.read_text())
    if (package.get("experiment") or {}).get("role") == "screener":
        raise EvalError("the editor only revises the writer prompt; edit the screener prompt by hand from the review")
    if package.get("format") != FORMAT:
        raise EvalError(f"{feedback_path} is not a feedback package ({FORMAT})")
    split = package["experiment"]["dataset"]["split"]
    if split == "validation" and not allow_validation:
        raise EvalError(
            "this batch is from the validation split; tuning on it spoils it as a check."
            " Pass --allow-validation only if you mean it."
        )
    if not any(c["review"]["verdict"] in _REVIEWED for c in package["cases"]):
        raise EvalError("the package has no reviewed outputs: nothing to learn from")
    if note:
        package["operator_note"] = note.strip()
    if os.environ.get("ANTHROPIC_API_KEY"):
        raise EvalError("ANTHROPIC_API_KEY is set; the editor runs on subscription auth only. Unset it.")
    os.environ.pop("CLAUDECODE", None)

    cfg = settings().get("editor") or {}
    model = model or cfg["model"]
    effort = effort or cfg.get("effort")
    proposal = asyncio.run(
        _ask(package, model, effort, int(cfg.get("max_turns", 6)), float(cfg.get("timeout_s", 1800)))
    )

    base = package["experiment"]["prompt"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base_path = Path(base["path"])
    # prompts/writer/v2.md → writer-v2, so the id says which role and version it grew from.
    name = f"{base_path.parent.name}-{base_path.stem}" if base_path.stem[:1] == "v" else base_path.stem
    candidate_id = f"{stamp}-{name}"
    out_dir = CANDIDATES_DIR / candidate_id
    out_dir.mkdir(parents=True)
    # Same extension as the base prompt; adopting copies it into the next prompts/<role>/v<N>.md.
    prompt_path = out_dir / f"prompt{Path(base['path']).suffix or '.md'}"
    revised = proposal["revised_prompt"].strip() + "\n"
    prompt_path.write_text(revised, encoding="utf-8")
    meta = {
        "candidate_id": candidate_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_prompt": {"path": base["path"], "sha": base["sha"]},
        "candidate_prompt": {"path": rel(prompt_path), "sha": prompt_sha(revised)},
        "adopt_as": rel(next_version()),
        "feedback": {
            "path": rel(feedback_path),
            "eval_id": package["eval_id"],
            "run_id": package["experiment"]["run_id"],
            "dataset": f"{package['experiment']['dataset']['id']}@{package['experiment']['dataset']['version']}",
            "split": split,
            "summary": package["summary"],
        },
        "operator_note": package.get("operator_note"),
        "editor": {
            "model": model,
            "effort": effort,
            "instructions_sha": prompt_sha((EVALS_DIR / "editor_prompt.txt").read_text()),
        },
    }
    (out_dir / "proposal.json").write_text(
        json.dumps({**meta, "proposal": proposal}, indent=2, ensure_ascii=False) + "\n"
    )
    (out_dir / "CHANGES.md").write_text(_changes_md(meta, proposal, package["prompt"]["text"] or ""))
    return out_dir
