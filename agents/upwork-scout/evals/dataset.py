"""Eval datasets: a YAML `dataset:` header (id, version, split) and `cases` (format: README, Prompt evals).

Each case is one Upwork job record (as in ``jobs.raw``) plus optional instructions, reference and metadata."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from evals.common import EvalError, rel

SPLITS = ("smoke", "tuning", "validation")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@dataclass(frozen=True)
class Case:
    id: str
    job: dict[str, Any]
    job_source: str  # the fixture path, or "inline"
    operator_instructions: str | None = None
    reference: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Dataset:
    path: Path
    id: str
    version: str
    split: str
    description: str
    cases: tuple[Case, ...]
    sha256: str  # over the dataset file and every fixture it reads

    def manifest(self) -> dict[str, Any]:
        return {
            "path": rel(self.path),
            "id": self.id,
            "version": self.version,
            "split": self.split,
            "sha256": self.sha256,
            "case_ids": [c.id for c in self.cases],
        }


def load(path: Path) -> Dataset:
    if not path.is_file():
        raise EvalError(f"dataset not found: {path}")
    digest = hashlib.sha256(path.read_bytes())
    raw = yaml.safe_load(path.read_text()) or {}
    head = raw.get("dataset") or {}
    where = rel(path)

    dataset_id = str(head.get("id") or "")
    if not _SLUG.match(dataset_id):
        raise EvalError(f"{where}: dataset.id must be a lowercase slug")
    split = head.get("split")
    if split not in SPLITS:
        raise EvalError(f"{where}: dataset.split must be one of {', '.join(SPLITS)}")
    if head.get("version") is None:
        raise EvalError(f"{where}: dataset.version is required")

    cases: list[Case] = []
    for i, entry in enumerate(raw.get("cases") or []):
        case_id = str(entry.get("id") or "")
        if not _SLUG.match(case_id):
            raise EvalError(f"{where}: case #{i + 1} needs an id that is a lowercase slug")
        if any(c.id == case_id for c in cases):
            raise EvalError(f"{where}: duplicate case id {case_id!r}")
        if bool(entry.get("job")) == bool(entry.get("job_file")):
            raise EvalError(f"{where}: case {case_id!r} needs exactly one of job / job_file")
        if entry.get("job_file"):
            fixture = (path.parent / entry["job_file"]).resolve()
            if not fixture.is_file():
                raise EvalError(f"{where}: case {case_id!r}: job_file not found: {fixture}")
            digest.update(fixture.read_bytes())
            job, source = json.loads(fixture.read_text()), rel(fixture)
        else:
            job, source = entry["job"], "inline"
        if (
            not isinstance(job, dict)
            or not job.get("title")
            or not (job.get("description") or job.get("descriptionMarkdown"))
        ):
            raise EvalError(f"{where}: case {case_id!r}: the job record needs a title and a description")
        cases.append(
            Case(
                id=case_id,
                job=job,
                job_source=source,
                operator_instructions=(entry.get("operator_instructions") or "").strip() or None,
                reference=(entry.get("reference") or "").strip() or None,
                metadata=dict(entry.get("metadata") or {}),
            )
        )
    if not cases:
        raise EvalError(f"{where}: no cases")
    return Dataset(
        path=path.resolve(),
        id=dataset_id,
        version=str(head["version"]),
        split=split,
        description=str(head.get("description") or ""),
        cases=tuple(cases),
        sha256=digest.hexdigest(),
    )


def add_records(
    path: Path,
    records: list[dict[str, Any]],
    fixtures_dir: Path,
    cases: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Append actor records as new cases, one fixture each, without personal-data fields; returns the new ids."""
    raw = yaml.safe_load(path.read_text()) if path.is_file() else None
    if not raw:
        raise EvalError(f"{path}: create the dataset header first (dataset: id, version, split)")
    entries = raw.get("cases") or []
    raw["cases"] = entries
    known = {c.get("id") for c in entries}
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    added = []
    for record in records:
        job_id = str(record.get("jobId") or "")
        if not job_id:
            raise EvalError("every record needs a jobId")
        extra = (cases or {}).get(job_id) or {}
        case_id = extra.get("id") or f"job-{job_id}"
        if case_id in known:
            continue
        clean = {
            k: v for k, v in record.items() if not k.startswith(("contact", "extracted")) and k != "socialProfiles"
        }
        fixture = fixtures_dir / f"{case_id}.json"
        fixture.write_text(json.dumps(clean, indent=2, ensure_ascii=False) + "\n")
        entry: dict[str, Any] = {"id": case_id, "job_file": os.path.relpath(fixture.resolve(), path.parent.resolve())}
        if extra.get("operator_instructions"):
            entry["operator_instructions"] = extra["operator_instructions"]
        entry["metadata"] = extra.get("metadata") or {"title": record.get("title")}
        entries.append(entry)
        known.add(case_id)
        added.append(case_id)
    # safe_dump drops comments; keep the file's header block, which says what the dataset is.
    original = path.read_text().splitlines(keepends=True)
    body_start = next((i for i, line in enumerate(original) if not line.startswith("#")), len(original))
    header = "".join(original[:body_start])
    path.write_text(header + yaml.safe_dump(raw, sort_keys=False, allow_unicode=True, width=100))
    return added
