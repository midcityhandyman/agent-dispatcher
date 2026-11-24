"""A record of exactly what every agent was shown and what it said back.

The ledger is how the isolation claims in the README are checked rather than asserted:
tests and the audit read the literal prompts.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

_ROLE_RANK = {"lead": 0, "worker": 1, "verifier": 2}


@dataclass(frozen=True)
class ContextEntry:
    role: str
    agent_id: str
    task_id: str
    attempt: int
    system: str
    prompt: str
    response: str


class ContextLedger:
    def __init__(self) -> None:
        self._entries: list[ContextEntry] = []
        self._lock = threading.Lock()

    def record(self, entry: ContextEntry) -> None:
        with self._lock:
            self._entries.append(entry)

    def entries(self, role: str | None = None, task_id: str | None = None) -> list[ContextEntry]:
        """Entries in a stable order that does not depend on thread scheduling."""
        with self._lock:
            items = list(self._entries)
        if role is not None:
            items = [e for e in items if e.role == role]
        if task_id is not None:
            items = [e for e in items if e.task_id == task_id]
        return sorted(items, key=lambda e: (e.task_id, e.attempt, _ROLE_RANK.get(e.role, 9)))

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
