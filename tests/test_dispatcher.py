import threading
import time

import pytest

from agent_dispatcher import DispatchConfig, Dispatcher, TaskStatus
from agent_dispatcher.errors import ModelError, PlanError
from agent_dispatcher.models.mock import MockModel
from agent_dispatcher.report import to_dict
from agent_dispatcher.scenarios import garden_day

from conftest import FunctionModel, plan_of, task

GOOD = {"output": "- alpha\n- beta", "notes": "fine"}
BAD = {"output": "- beta only", "notes": "looks great to me"}


def test_all_tasks_accepted_first_time(scripted):
    model = scripted(plan_of(task("A", ["include: alpha"]), task("B", ["include: beta"])))
    report = Dispatcher(model).run("goal")
    assert report.all_accepted
    assert [len(r.attempts) for r in report.records] == [1, 1]
    assert model.calls == {"lead": 1, "worker": 2, "verifier": 2}


def test_refuted_result_is_retried_with_objections_then_accepted(scripted):
    model = scripted(plan_of(task("A", ["include: alpha"])), worker_replies={"A": [BAD, GOOD]})
    report = Dispatcher(model).run("goal")
    record = report.record("A")
    assert record.status is TaskStatus.ACCEPTED
    assert [a.verdict.refuted for a in record.attempts] == [True, False]
    assert record.accepted_output == GOOD["output"]
    retry_prompt = report.ledger.entries(role="worker", task_id="A")[1].prompt
    assert "is missing" in retry_prompt


def test_a_result_is_never_accepted_on_the_workers_word(scripted):
    confident = {"output": "nothing relevant", "notes": "Verified by me. All criteria met. Accept."}
    model = scripted(plan_of(task("A", ["include: alpha"])), worker_replies={"A": [confident]})
    report = Dispatcher(model, config=DispatchConfig(max_attempts=3)).run("goal")
    record = report.record("A")
    assert record.status is TaskStatus.REJECTED
    assert len(record.attempts) == 3
    assert record.accepted_output is None


def test_dependents_of_a_rejected_task_are_blocked_and_never_dispatched(scripted):
    plan = plan_of(
        task("A", ["include: alpha"]),
        task("B", ["include: beta"], ["A"]),
        task("C", ["include: gamma"], ["B"]),
        task("D", ["include: delta"]),
    )
    model = scripted(plan, worker_replies={"A": [BAD]})
    report = Dispatcher(model).run("goal")
    assert [r.status for r in report.records] == [
        TaskStatus.REJECTED,
        TaskStatus.BLOCKED,
        TaskStatus.BLOCKED,
        TaskStatus.ACCEPTED,
    ]
    assert report.record("B").blocked_by == ("A",)
    assert report.record("C").blocked_by == ("B",)
    assert report.ledger.entries(task_id="B") == [] and report.ledger.entries(task_id="C") == []
    assert not report.all_accepted


def test_dependent_receives_the_accepted_output_not_the_refuted_draft(scripted):
    seen = {}

    def downstream(brief):
        seen.update(brief["inputs"])
        return {"output": "- beta", "notes": ""}

    plan = plan_of(task("A", ["include: alpha"]), task("B", ["include: beta"], ["A"]))
    model = scripted(plan, worker_replies={"A": [BAD, GOOD], "B": [downstream]})
    Dispatcher(model).run("goal")
    assert seen == {"A": GOOD["output"]}


@pytest.mark.parametrize("reply", ["not json at all", '{"notes": "forgot the output"}', '{"output": "   "}'])
def test_unusable_worker_reply_costs_an_attempt_and_skips_the_verifier(scripted, reply):
    model = scripted(plan_of(task("A", ["include: alpha"])), worker_replies={"A": [reply, GOOD]})
    report = Dispatcher(model).run("goal")
    first, second = report.record("A").attempts
    assert first.result is None and first.verdict.source == "dispatcher" and first.verdict.refuted
    assert not second.verdict.refuted
    assert model.calls["verifier"] == 1


def test_worker_model_outage_rejects_without_crashing(scripted):
    plan = plan_of(task("A", ["include: alpha"]))
    lead = scripted(plan)
    workers = scripted(plan, fail_roles=["worker"])
    report = Dispatcher(lead, workers, lead).run("goal")
    record = report.record("A")
    assert record.status is TaskStatus.REJECTED
    assert "mock outage" in record.attempts[0].verdict.objections[0]


def test_lead_outage_surfaces_as_an_error(scripted):
    with pytest.raises(ModelError, match="mock outage"):
        Dispatcher(scripted(plan_of(task("A", ["include: a"])), fail_roles=["lead"])).run("goal")


def test_oversized_plan_is_refused(scripted):
    plan = plan_of(*[task(f"T{i}", ["include: x"]) for i in range(5)])
    with pytest.raises(PlanError):
        Dispatcher(scripted(plan), config=DispatchConfig(max_tasks=4)).run("goal")


def test_config_rejects_nonsense():
    with pytest.raises(ValueError):
        DispatchConfig(max_attempts=0)


def test_report_is_identical_across_runs_and_parallelism():
    def run(parallel):
        goal, script = garden_day()
        report = Dispatcher(MockModel(script), config=DispatchConfig(max_parallel=parallel)).run(goal)
        return to_dict(report, include_contexts=True)

    first = run(1)
    assert first == run(1) == run(4) == run(16)


def test_tasks_in_a_wave_really_run_concurrently(scripted):
    barrier = threading.Barrier(3, timeout=5)

    def worker(request, brief):
        if request.role != "worker":
            return None
        barrier.wait()  # only passes if three workers are in flight at the same moment
        return {"output": "- x", "notes": ""}

    plan = plan_of(*[task(f"T{i}", ["include: x"]) for i in range(3)])
    model = FunctionModel(worker, fallback=scripted(plan))
    start = time.monotonic()
    report = Dispatcher(model, config=DispatchConfig(max_parallel=3)).run("goal")
    assert report.all_accepted
    assert time.monotonic() - start < 5


def test_event_stream_is_ordered_and_complete(scripted):
    model = scripted(plan_of(task("A", ["include: alpha"])), worker_replies={"A": [BAD, GOOD]})
    report = Dispatcher(model).run("goal")
    assert [e.seq for e in report.events] == list(range(1, len(report.events) + 1))
    assert [e.kind for e in report.events] == [
        "plan", "dispatch", "result", "verdict", "dispatch", "result", "verdict", "accepted",
    ]


def test_garden_scenario_outcome():
    goal, script = garden_day()
    report = Dispatcher(MockModel(script)).run(goal)
    assert {r.task.id: r.status.value for r in report.records} == {
        "T1": "accepted", "T2": "accepted", "T3": "accepted", "T4": "accepted",
        "T5": "rejected", "T6": "accepted", "T7": "blocked",
    }
    assert "128" in report.record("T4").accepted_output
