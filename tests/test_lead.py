import pytest

from agent_dispatcher.agents import LeadAgent, plan_waves, validate_plan
from agent_dispatcher.errors import PlanError
from agent_dispatcher.ledger import ContextLedger
from agent_dispatcher.models.mock import MockModel, generic_plan

from conftest import FunctionModel, plan_of, task


def test_valid_plan_becomes_tasks_and_waves():
    tasks = validate_plan(
        plan_of(task("A", ["include: a"]), task("B", ["include: b"], ["A"]), task("C", ["include: c"], ["A", "B"])),
        max_tasks=8,
    )
    assert [t.id for t in tasks] == ["A", "B", "C"]
    assert [[t.id for t in wave] for wave in plan_waves(tasks)] == [["A"], ["B"], ["C"]]


@pytest.mark.parametrize(
    "plan,message",
    [
        ({}, "no tasks"),
        ({"tasks": []}, "no tasks"),
        ({"tasks": ["x"]}, "not an object"),
        (plan_of(task("A", ["include: a"]), task("A", ["include: a"])), "duplicate"),
        (plan_of(task("A", [])), "no acceptance criteria"),
        (plan_of(task("A", ["  "])), "no acceptance criteria"),
        (plan_of(task("A", ["include: a"], ["Z"])), "unknown task"),
        (plan_of(task("A", ["include: a"], ["A"])), "depends on itself"),
        (plan_of(task("A", ["include: a"], ["B"]), task("B", ["include: b"], ["A"])), "cycle"),
        (plan_of({"id": "", "title": "x", "criteria": ["c"]}), "missing id or title"),
    ],
)
def test_bad_plans_are_refused(plan, message):
    with pytest.raises(PlanError, match=message):
        validate_plan(plan, max_tasks=8)


def test_plan_over_the_task_limit_is_refused():
    plan = plan_of(*[task(f"T{i}", ["include: x"]) for i in range(4)])
    with pytest.raises(PlanError, match="limit is 3"):
        validate_plan(plan, max_tasks=3)


def test_lead_sees_only_the_goal_and_logs_its_call():
    ledger = ContextLedger()
    tasks = LeadAgent(MockModel(), ledger).decompose("draft the agenda, then list the action items")
    assert len(tasks) == 2
    (entry,) = ledger.entries(role="lead")
    assert "draft the agenda" in entry.prompt


def test_lead_reply_that_is_not_json_is_a_plan_error():
    model = FunctionModel(lambda request, brief: "I would rather chat about it.")
    with pytest.raises(PlanError, match="lead reply unusable"):
        LeadAgent(model, ContextLedger()).decompose("anything")


def test_empty_goal_is_refused_before_any_model_call():
    model = MockModel()
    with pytest.raises(PlanError):
        LeadAgent(model, ContextLedger()).decompose("   ")
    assert model.calls["lead"] == 0


def test_generic_plan_is_bounded_and_checkable():
    plan = generic_plan("one thing, another thing, a third thing, a fourth thing", max_tasks=2)
    assert len(plan["tasks"]) == 2
    assert all(t["criteria"] for t in plan["tasks"])
    validate_plan(plan, max_tasks=2)
