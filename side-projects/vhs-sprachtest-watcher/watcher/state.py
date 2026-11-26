"""Persisted snapshot of seen courses and the diff that decides what is worth an alert."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from watcher.vhs import Course


@dataclass
class Changes:
    new: list[Course] = field(default_factory=list)
    freed: list[Course] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.new or self.freed)


def load(path: Path) -> dict[str, dict[str, str]] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, courses: list[Course]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    payload = {c.number: c.to_dict() for c in courses}
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def diff(previous: dict[str, dict[str, str]], current: list[Course]) -> Changes:
    changes = Changes()
    for course in current:
        before = previous.get(course.number)
        if before is None:
            changes.new.append(course)
        elif course.is_free and before.get("places", "").lower() == "belegt":
            changes.freed.append(course)
    return changes
