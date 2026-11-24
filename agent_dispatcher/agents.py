"""The three agent roles. Each call is one stateless model request built from a brief."""

from __future__ import annotations

from .errors import AgentError, ModelError, ParseError, PlanError
from .ledger import ContextEntry, ContextLedger
from .models.base import Model, ModelRequest
from .parsing import extract_json
from . import prompts
from .types import Check, Task, Verdict, WorkResult


def _call(
    model: Model,
    ledger: ContextLedger,
    *,
    role: str,
    agent_id: str,
    task_id: str,
    attempt: int,
    system: str,
    prompt: str,
) -> str:
    """Make the call and write down exactly what was sent, even when the call fails."""
    logged = "[no reply]"
    try:
        reply = model.complete(ModelRequest(role=role, system=system, prompt=prompt))
        logged = reply
        return reply
    except ModelError as exc:
        logged = f"[model error] {exc}"
        raise
    finally:
        ledger.record(ContextEntry(role, agent_id, task_id, attempt, system, prompt, logged))


class LeadAgent:
    def __init__(self, model: Model, ledger: ContextLedger, max_tasks: int = 8) -> None:
        self.model, self.ledger, self.max_tasks = model, ledger, max_tasks

    def decompose(self, goal: str) -> list[Task]:
        if not goal or not goal.strip():
            raise PlanError("goal is empty")
        reply = _call(
            self.model,
            self.ledger,
            role="lead",
            agent_id="lead",
            task_id="",
            attempt=0,
            system=prompts.LEAD_SYSTEM,
            prompt=prompts.lead_prompt(goal, self.max_tasks),
        )
        try:
            data = extract_json(reply)
        except ParseError as exc:
            raise PlanError(f"lead reply unusable: {exc}") from exc
        return validate_plan(data, self.max_tasks)


def validate_plan(data: dict, max_tasks: int) -> list[Task]:
    """Turn the lead's JSON into tasks, refusing plans that cannot be run or verified."""
    raw = data.get("tasks")
    if not isinstance(raw, list) or not raw:
        raise PlanError("plan has no tasks")
    if len(raw) > max_tasks:
        raise PlanError(f"plan has {len(raw)} tasks, limit is {max_tasks}")
    tasks: list[Task] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise PlanError("task entry is not an object")
        task_id = str(item.get("id", "")).strip()
        title = str(item.get("title", "")).strip()
        if not task_id or not title:
            raise PlanError("task is missing id or title")
        if task_id in seen:
            raise PlanError(f"duplicate task id {task_id}")
        seen.add(task_id)
        criteria = item.get("criteria") or []
        if not isinstance(criteria, list):
            raise PlanError(f"task {task_id}: criteria must be a list")
        criteria = tuple(str(c).strip() for c in criteria if str(c).strip())
        if not criteria:
            raise PlanError(f"task {task_id} has no acceptance criteria, so it could never be verified")
        depends = item.get("depends_on") or []
        if not isinstance(depends, list):
            raise PlanError(f"task {task_id}: depends_on must be a list")
        tasks.append(
            Task(
                id=task_id,
                title=title,
                instructions=str(item.get("instructions", "")).strip() or title,
                criteria=criteria,
                depends_on=tuple(str(d).strip() for d in depends),
            )
        )
    for task in tasks:
        for dep in task.depends_on:
            if dep not in seen:
                raise PlanError(f"task {task.id} depends on unknown task {dep}")
            if dep == task.id:
                raise PlanError(f"task {task.id} depends on itself")
    plan_waves(tasks)  # raises on cycles
    return tasks


def plan_waves(tasks: list[Task]) -> list[list[Task]]:
    """Group tasks into waves; every task's dependencies sit in an earlier wave."""
    remaining = list(tasks)
    placed: set[str] = set()
    waves: list[list[Task]] = []
    while remaining:
        wave = [t for t in remaining if all(d in placed for d in t.depends_on)]
        if not wave:
            raise PlanError("dependency cycle among: " + ", ".join(t.id for t in remaining))
        waves.append(wave)
        placed.update(t.id for t in wave)
        remaining = [t for t in remaining if t.id not in placed]
    return waves


class Worker:
    """One worker per task attempt. It holds no state, so there is nothing to carry over."""

    def __init__(self, model: Model, ledger: ContextLedger) -> None:
        self.model, self.ledger = model, ledger

    def run(
        self,
        task: Task,
        attempt: int,
        inputs: dict[str, str],
        prior_objections: tuple[str, ...] = (),
    ) -> WorkResult:
        try:
            reply = _call(
                self.model,
                self.ledger,
                role="worker",
                agent_id=f"worker-{task.id}-a{attempt}",
                task_id=task.id,
                attempt=attempt,
                system=prompts.WORKER_SYSTEM,
                prompt=prompts.worker_prompt(task, attempt, inputs, prior_objections),
            )
            data = extract_json(reply)
        except ModelError as exc:
            raise AgentError(f"model call failed: {exc}") from exc
        except ParseError as exc:
            raise AgentError(f"reply was not the expected JSON: {exc}") from exc
        output = data.get("output")
        if not isinstance(output, str) or not output.strip():
            raise AgentError("reply had no output")
        notes = data.get("notes")
        return WorkResult(task.id, attempt, output, notes if isinstance(notes, str) else "")


class Verifier:
    """Tries to refute a claimed output. Fails closed: anything short of a complete,
    consistent 'stands' with every criterion checked counts as refuted."""

    def __init__(self, model: Model, ledger: ContextLedger) -> None:
        self.model, self.ledger = model, ledger

    def examine(self, task: Task, attempt: int, inputs: dict[str, str], claimed_output: str) -> Verdict:
        # `attempt` is bookkeeping for the ledger and the verdict. It is not put in the prompt.
        def refuted(*reasons: str, checks: tuple[Check, ...] = ()) -> Verdict:
            return Verdict(task.id, attempt, True, tuple(reasons), checks)

        try:
            reply = _call(
                self.model,
                self.ledger,
                role="verifier",
                agent_id=f"verifier-{task.id}-a{attempt}",
                task_id=task.id,
                attempt=attempt,
                system=prompts.VERIFIER_SYSTEM,
                prompt=prompts.verifier_prompt(task, inputs, claimed_output),
            )
            data = extract_json(reply)
        except ModelError as exc:
            return refuted(f"verifier unavailable, result not accepted: {exc}")
        except ParseError as exc:
            return refuted(f"verifier reply unusable, result not accepted: {exc}")

        checks = _read_checks(data.get("checks"))
        verdict = data.get("verdict")
        raw_objections = data.get("objections")
        objections = [str(o) for o in raw_objections if str(o).strip()] if isinstance(raw_objections, list) else []

        if verdict == "refuted":
            return refuted(*(objections or ["verifier refuted without stating an objection"]), checks=checks)
        if verdict != "stands":
            return refuted(f"verifier gave no usable verdict ({verdict!r})", checks=checks)

        # The verifier says it stands. Hold it to its own evidence before believing that.
        # Every failed check counts, including a duplicate entry for a criterion that also
        # has a passing one, and a check for something that is not a criterion at all.
        checked = {_norm(c.criterion) for c in checks}
        problems = [f"verifier did not check: {c}" for c in task.criteria if _norm(c) not in checked]
        problems += [
            f"verifier said stands but its own check failed: {c.criterion}" for c in checks if not c.passed
        ]
        if problems:
            return refuted(*problems, checks=checks)
        return Verdict(task.id, attempt, False, (), checks)


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _read_checks(raw: object) -> tuple[Check, ...]:
    if not isinstance(raw, list):
        return ()
    checks = []
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("criterion"), str):
            checks.append(
                Check(item["criterion"], item.get("passed") is True, str(item.get("evidence", "")))
            )
    return tuple(checks)
