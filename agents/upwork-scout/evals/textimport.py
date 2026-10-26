"""Postings copied from Upwork as text (datasets/source/*.txt) → actor-shaped records for a dataset.

Formal screening questions become ``operator_instructions``; questions in the description stay there."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from evals.common import EvalError

_JOB = re.compile(r"^JOB (\d+) / \d+$", re.MULTILINE)
_TRAILING = (
    "Workload:",
    "Budget:",
    "Rate:",
    "Experience level:",
    "Project Type:",
    "Skills and Expertise:",
    "Preferred qualifications:",
    "Attachment:",
    "Contract-to-hire opportunity",
)
_LEVELS = {"Entry": "EntryLevel", "Intermediate": "IntermediateLevel", "Expert": "ExpertLevel"}


def _money(text: str) -> float:
    return float(text.replace("$", "").replace(",", ""))


def _slug(title: str) -> str:
    slug = ""
    for word in re.sub(r"[^a-z0-9]+", " ", title.lower()).split():
        if len(slug) + len(word) + 1 > 40:
            break
        slug = f"{slug}-{word}" if slug else word
    return slug


def parse_job(number: int, block: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """One job block → (actor-shaped record, case fields: id, operator_instructions, metadata)."""
    head, _, rest = block.partition("\n" + "-" * 20)
    fields = dict(re.findall(r"^(Title|URL|Proposal submitted): (.*)$", head, re.MULTILINE))
    if not {"Title", "URL"} <= fields.keys():
        raise EvalError(f"job {number:02d}: missing Title or URL")
    rest = rest.split("\n", 1)[1] if "\n" in rest else ""  # drop the rest of the dashed line
    body_part, marker, questions_part = rest.partition("SCREENING QUESTIONS")
    lines = body_part.rstrip().splitlines()
    if marker and lines and lines[-1].strip() == "===":
        lines.pop()

    trailing: list[str] = []
    while lines and (not lines[-1].strip() or lines[-1].startswith(_TRAILING)):
        line = lines.pop().strip()
        if line:
            trailing.insert(0, line)
    description = "\n".join(lines).strip()
    info: dict[str, str] = {}
    for line in trailing:
        key = next((k for k in _TRAILING if line.startswith(k)), None)
        if key:
            info[key.rstrip(":")] = line[len(key) :].strip()

    record: dict[str, Any] = {
        "jobId": fields["URL"].rsplit("~", 1)[-1].removeprefix("02"),
        "title": fields["Title"].strip(),
        "url": fields["URL"].strip(),
        "description": description,
        "descriptionMarkdown": description,
        "jobType": None,
        "experienceLevel": _LEVELS.get(info.get("Experience level", ""), info.get("Experience level")),
        "skills": [s.strip() for s in info.get("Skills and Expertise", "").split(",") if s.strip()],
        "source": "upwork-text-import",
    }
    workload = info.get("Workload", "")
    if "Hourly" in workload:
        record["jobType"] = "HOURLY"
        record["engagementType"] = "FULL_TIME" if workload.startswith("More than 30") else "PART_TIME"
        duration = re.search(r"Duration: (.+)$", workload)
        record["engagementDuration"] = duration.group(1).strip() if duration else None
    rate = re.match(r"\$([\d,.]+) - \$([\d,.]+) Hourly", info.get("Rate", ""))
    if rate:
        record["jobType"] = "HOURLY"
        record["hourlyBudgetMin"], record["hourlyBudgetMax"] = _money(rate.group(1)), _money(rate.group(2))
    budget = re.match(r"\$([\d,.]+) Fixed-price", info.get("Budget", ""))
    if budget:
        record["jobType"] = "FIXED"
        record["budgetAmount"], record["budgetCurrency"] = _money(budget.group(1)), "USD"

    formal = (
        re.findall(r"^\s*\d+\.\s.+$", questions_part, re.MULTILINE) if "You will be asked" in questions_part else []
    )
    if formal:
        questions = "formal"
    elif "inside the description" in questions_part:
        questions = "in_description"
    else:
        questions = "none"
    case = {
        "id": f"j{number:02d}-{_slug(record['title'])}",
        "operator_instructions": "\n".join(q.strip() for q in formal) or None,
        "metadata": {
            "title": record["title"],
            "questions": questions,
            "submitted": fields.get("Proposal submitted"),
            "project_type": info.get("Project Type"),
            "preferred_qualifications": info.get("Preferred qualifications"),
            "contract_to_hire": "Contract-to-hire opportunity" in info,
            "attachment": info.get("Attachment"),
        },
    }
    case["metadata"] = {k: v for k, v in case["metadata"].items() if v not in (None, False)}
    if not description:
        raise EvalError(f"job {number:02d}: empty description")
    return record, case


def parse(path: Path) -> dict[int, tuple[dict[str, Any], dict[str, Any]]]:
    text = path.read_text(encoding="utf-8")
    starts = list(_JOB.finditer(text))
    if not starts:
        raise EvalError(f"{path}: no 'JOB NN / M' blocks found")
    jobs = {}
    for i, match in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        block = text[match.end() : end].split("\n" + "=" * 20)[0]
        jobs[int(match.group(1))] = parse_job(int(match.group(1)), block)
    return jobs
