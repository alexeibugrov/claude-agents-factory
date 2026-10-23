"""Per-run binding for the agent's tools.

Every tool handler takes the run's context explicitly instead of reading module globals. Each run
screens or drafts exactly one job, and its submit tool records the answer on this run's
``result`` holder — so one run's verdict can never land on another run's job.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RunContext:
    """One run's binding: which job, which role, and where the submit tool records its answer."""

    run_id: str
    job_id: str
    role: str  # "screener" | "writer"
    # Filled by the role's submit tool; the pipeline persists it after run_once returns.
    result: dict[str, Any] = field(default_factory=dict)
