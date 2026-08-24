"""Per-run binding for the agent's tools.

Every tool handler takes the run's context explicitly instead of reading module globals. The
agent loop is async and may have several runs in flight, so globals would let one run's state
leak into another's tool calls — a class of bug that is silent and very hard to trace.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RunContext:
    """One run's binding: the clients and identifiers its tools are allowed to touch."""

    run_id: str
    # TEMPLATE: replace with the real per-run dependencies (an API client, a DB handle, ...).
    client: Any = None
