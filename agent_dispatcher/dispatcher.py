"""The orchestration loop: plan, dispatch, verify, accept or retry."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .agents import LeadAgent, Verifier, Worker, plan_waves
from .errors import AgentError
from .ledger import ContextLedger
from .models.base import Model
from .types import Attempt, Event, RunReport, Task, TaskRecord, TaskStatus, Verdict


@dataclass(frozen=True)
class DispatchConfig:
    max_attempts: int = 2  # per task, counting the first try
    max_parallel: int = 4  # workers running at once within a wave
    max_tasks: int = 8  # plans larger than this are refused

    def __post_init__(self) -> None:
        if self.max_attempts < 1 or self.max_parallel < 1 or self.max_tasks < 1:
            raise ValueError("max_attempts, max_parallel and max_tasks must be at least 1")


class Dispatcher:
    """Runs a goal to a report.

    The three models may be the same object or three different ones. Giving the verifier
    its own model is the stronger setup; the context separation holds either way because
    every call is stateless and built from a role specific brief.
    """

    def __init__(
        self,
        lead_model: Model,
        worker_model: Model | None = None,
        verifier_model: Model | None = None,
        config: DispatchConfig | None = None,
    ) -> None:
        self.lead_model = lead_model
        self.worker_model = worker_model or lead_model
        self.verifier_model = verifier_model or lead_model
        self.config = config or DispatchConfig()

    def run(self, goal: str) -> RunReport:
        ledger = ContextLedger()
        tasks = LeadAgent(self.lead_model, ledger, self.config.max_tasks).decompose(goal)
        waves = plan_waves(tasks)

        log: list[tuple[str, str, int, str]] = [
            ("plan", "", 0, f"{len(tasks)} tasks in {len(waves)} waves: " + ", ".join(t.id for t in tasks))
        ]
        records: dict[str, TaskRecord] = {}

        for wave in waves:
            runnable: list[Task] = []
            for task in wave:
                failed = tuple(d for d in task.depends_on if records[d].status is not TaskStatus.ACCEPTED)
                if failed:
                    records[task.id] = TaskRecord(task, TaskStatus.BLOCKED, blocked_by=failed)
                else:
                    runnable.append(task)

            def run_one(task: Task) -> tuple[TaskRecord, list[tuple[str, str, int, str]]]:
                # Only accepted outputs of declared dependencies are passed down.
                inputs = {d: records[d].accepted_output or "" for d in task.depends_on}
                return self._run_task(task, inputs, ledger)

            if runnable:
                with ThreadPoolExecutor(max_workers=self.config.max_parallel) as pool:
                    finished = list(pool.map(run_one, runnable))  # results come back in task order
                for record, task_log in finished:
                    records[record.task.id] = record
            else:
                finished = []

            # Merge per task logs in plan order so the event stream never depends on timing.
            done = {record.task.id: task_log for record, task_log in finished}
            for task in wave:
                if task.id in done:
                    log.extend(done[task.id])
                else:
                    blocked = records[task.id].blocked_by
                    log.append(("blocked", task.id, 0, "not started, depends on " + ", ".join(blocked)))

        events = [Event(i, kind, task_id, attempt, detail) for i, (kind, task_id, attempt, detail) in enumerate(log, 1)]
        return RunReport(goal, [records[t.id] for t in tasks], events, ledger)

    def _run_task(
        self, task: Task, inputs: dict[str, str], ledger: ContextLedger
    ) -> tuple[TaskRecord, list[tuple[str, str, int, str]]]:
        log: list[tuple[str, str, int, str]] = []
        record = TaskRecord(task, TaskStatus.REJECTED)
        objections: tuple[str, ...] = ()

        for number in range(1, self.config.max_attempts + 1):
            note = "fresh worker" if number == 1 else f"fresh worker, given {len(objections)} objection(s)"
            log.append(("dispatch", task.id, number, note))
            try:
                # A new Worker and a new Verifier per attempt. Nothing is reused.
                result = Worker(self.worker_model, ledger).run(task, number, inputs, objections)
            except AgentError as exc:
                result = None
                verdict = Verdict(task.id, number, True, (f"worker produced nothing usable: {exc}",), (), "dispatcher")
                log.append(("result", task.id, number, "no usable output"))
            else:
                log.append(("result", task.id, number, f"{len(result.output.split())} words returned"))
                verdict = Verifier(self.verifier_model, ledger).examine(task, number, inputs, result.output)

            record.attempts.append(Attempt(number, result, verdict))
            if not verdict.refuted:
                log.append(("verdict", task.id, number, f"stands, {len(verdict.checks)} checks passed"))
                log.append(("accepted", task.id, number, ""))
                record.status = TaskStatus.ACCEPTED
                record.accepted_output = result.output if result else None
                return record, log
            log.append(("verdict", task.id, number, "refuted: " + "; ".join(verdict.objections)))
            objections = verdict.objections

        log.append(("rejected", task.id, self.config.max_attempts, "attempts used up"))
        return record, log
