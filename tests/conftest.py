from __future__ import annotations

import json

import pytest

from agent_dispatcher.models.base import ModelRequest
from agent_dispatcher.models.mock import MockModel, MockScript
from agent_dispatcher.parsing import read_brief


class FunctionModel:
    """A Model built from a plain function, for tests that need odd behavior from one role."""

    name = "function"

    def __init__(self, fn, fallback=None):
        self.fn = fn
        self.fallback = fallback or MockModel()
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> str:
        self.requests.append(request)
        reply = self.fn(request, read_brief(request.prompt))
        if reply is None:
            return self.fallback.complete(request)
        return reply if isinstance(reply, str) else json.dumps(reply)


def plan_of(*tasks: dict) -> dict:
    return {"tasks": list(tasks)}


def task(task_id: str, criteria: list[str], depends_on: list[str] | None = None, title: str | None = None) -> dict:
    return {
        "id": task_id,
        "title": title or f"Task {task_id}",
        "instructions": f"Do {task_id}.",
        "criteria": criteria,
        "depends_on": depends_on or [],
    }


@pytest.fixture
def scripted():
    """Build a MockModel for a goal called "goal" from a plan and optional scripted replies."""

    def build(plan: dict, worker_replies=None, verifier_replies=None, fail_roles=()) -> MockModel:
        return MockModel(
            MockScript(
                plans={"goal": plan},
                worker_replies=worker_replies or {},
                verifier_replies=verifier_replies or {},
                fail_roles=frozenset(fail_roles),
            )
        )

    return build
