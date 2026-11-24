"""Plain data types shared by the agents and the dispatcher."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class Task:
    """One unit of work. A task with no criteria cannot be verified, so the lead rejects it."""

    id: str
    title: str
    instructions: str
    criteria: tuple[str, ...]
    depends_on: tuple[str, ...] = ()

    def public_spec(self) -> dict:
        """The part of a task that both the worker and the verifier are allowed to see."""
        return {
            "id": self.id,
            "title": self.title,
            "instructions": self.instructions,
            "criteria": list(self.criteria),
        }


@dataclass(frozen=True)
class WorkResult:
    """What a worker hands back. Only `output` ever travels on; `notes` stay with the dispatcher."""

    task_id: str
    attempt: int
    output: str
    notes: str = ""


@dataclass(frozen=True)
class Check:
    criterion: str
    passed: bool
    evidence: str = ""


@dataclass(frozen=True)
class Verdict:
    task_id: str
    attempt: int
    refuted: bool
    objections: tuple[str, ...] = ()
    checks: tuple[Check, ...] = ()
    source: str = "verifier"  # "verifier", or "dispatcher" when no verifier call was possible


@dataclass(frozen=True)
class Attempt:
    number: int
    result: WorkResult | None
    verdict: Verdict


@dataclass
class TaskRecord:
    task: Task
    status: TaskStatus
    attempts: list[Attempt] = field(default_factory=list)
    accepted_output: str | None = None
    blocked_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class Event:
    seq: int
    kind: str  # plan | dispatch | result | verdict | accepted | rejected | blocked
    task_id: str = ""
    attempt: int = 0
    detail: str = ""


@dataclass
class RunReport:
    goal: str
    records: list[TaskRecord]
    events: list[Event]
    ledger: "ContextLedger"  # noqa: F821  (see ledger.py; kept loose to avoid an import cycle)

    def record(self, task_id: str) -> TaskRecord:
        for rec in self.records:
            if rec.task.id == task_id:
                return rec
        raise KeyError(task_id)

    @property
    def all_accepted(self) -> bool:
        return all(r.status is TaskStatus.ACCEPTED for r in self.records)

    def counts(self) -> dict[str, int]:
        out = {s.value: 0 for s in TaskStatus}
        for rec in self.records:
            out[rec.status.value] += 1
        return out
