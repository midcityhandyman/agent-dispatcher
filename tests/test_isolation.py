"""The claims in the README about who sees what, checked against the literal prompts."""

from agent_dispatcher import Dispatcher
from agent_dispatcher.audit import audit_isolation
from agent_dispatcher.ledger import ContextEntry
from agent_dispatcher.models.mock import MockModel
from agent_dispatcher.parsing import read_brief, wrap_brief
from agent_dispatcher.scenarios import garden_day

from conftest import plan_of, task

SECRET = "WORKER-PRIVATE-7731"
DRAFT = "first draft with a flaw"


def run_garden():
    goal, script = garden_day()
    return Dispatcher(MockModel(script), MockModel(script), MockModel(script)).run(goal)


def test_verifier_brief_has_exactly_three_fields():
    report = run_garden()
    verifier_entries = report.ledger.entries(role="verifier")
    assert verifier_entries
    for entry in verifier_entries:
        brief = read_brief(entry.prompt)
        assert set(brief) == {"task", "inputs", "claimed_output"}
        assert set(brief["task"]) == {"id", "title", "instructions", "criteria"}


def test_worker_notes_never_reach_any_other_agent(scripted):
    plan = plan_of(task("A", ["include: alpha"]), task("B", ["include: beta"], ["A"]))
    model = scripted(
        plan,
        worker_replies={
            "A": [{"output": DRAFT, "notes": SECRET}, {"output": "- alpha", "notes": SECRET + "-2"}],
        },
    )
    report = Dispatcher(model).run("goal")
    assert report.all_accepted
    assert report.record("A").attempts[0].result.notes == SECRET  # the dispatcher kept them
    for entry in report.ledger.entries():
        assert SECRET not in entry.prompt, f"{entry.agent_id} was shown private worker notes"


def test_verifier_cannot_tell_a_retry_from_a_first_attempt(scripted):
    same = {"output": "- alpha", "notes": ""}
    plan = plan_of(task("A", ["include: alpha"]))
    report = Dispatcher(scripted(plan, worker_replies={"A": ["garbage", same]})).run("goal")
    retry_verifier = report.ledger.entries(role="verifier", task_id="A")[0]
    assert retry_verifier.attempt == 2

    fresh = Dispatcher(scripted(plan, worker_replies={"A": [same]})).run("goal")
    first_verifier = fresh.ledger.entries(role="verifier", task_id="A")[0]
    assert retry_verifier.prompt == first_verifier.prompt
    assert retry_verifier.system == first_verifier.system


def test_retry_worker_gets_objections_but_not_the_rejected_draft(scripted):
    plan = plan_of(task("A", ["include: alpha"]))
    model = scripted(plan, worker_replies={"A": [{"output": DRAFT, "notes": ""}, {"output": "- alpha", "notes": ""}]})
    report = Dispatcher(model).run("goal")
    first, retry = report.ledger.entries(role="worker", task_id="A")
    assert read_brief(first.prompt)["prior_objections"] == []
    retry_brief = read_brief(retry.prompt)
    assert retry_brief["prior_objections"] and retry_brief["attempt"] == 2
    assert DRAFT not in retry.prompt


def test_workers_only_receive_outputs_of_declared_dependencies():
    report = run_garden()
    by_task = {r.task.id: r.task for r in report.records}
    for entry in report.ledger.entries(role="worker"):
        brief = read_brief(entry.prompt)
        assert set(brief["inputs"]) == set(by_task[entry.task_id].depends_on)
    t2_prompt = report.ledger.entries(role="worker", task_id="T2")[0].prompt
    assert "compost" not in t2_prompt  # T1's content, which T2 does not depend on


def test_every_agent_call_has_its_own_identity():
    report = run_garden()
    ids = [e.agent_id for e in report.ledger.entries() if e.role != "lead"]
    assert len(ids) == len(set(ids))


def test_audit_is_clean_on_a_normal_run():
    assert audit_isolation(run_garden()) == []


def test_audit_catches_a_leak_when_one_is_planted():
    report = run_garden()
    attempt = report.record("T1").attempts[0]
    leaked = wrap_brief(
        {
            "task": report.record("T1").task.public_spec(),
            "inputs": {},
            "claimed_output": attempt.result.output,
            "worker_notes": attempt.result.notes,
        }
    )
    report.ledger.record(ContextEntry("verifier", "verifier-leaky", "T1", 9, "", leaked, ""))
    findings = audit_isolation(report)
    assert any("unexpected fields" in f for f in findings)
    assert any("contains worker notes" in f for f in findings)
