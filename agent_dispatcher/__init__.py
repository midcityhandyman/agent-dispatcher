"""Lead, worker and verifier orchestration with model access behind an interface."""

from .dispatcher import DispatchConfig, Dispatcher
from .types import (
    Attempt,
    Event,
    RunReport,
    Task,
    TaskRecord,
    TaskStatus,
    Verdict,
    WorkResult,
)

__all__ = [
    "Attempt",
    "DispatchConfig",
    "Dispatcher",
    "Event",
    "RunReport",
    "Task",
    "TaskRecord",
    "TaskStatus",
    "Verdict",
    "WorkResult",
]
