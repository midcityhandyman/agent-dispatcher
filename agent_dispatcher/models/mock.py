"""Deterministic offline model.

It plays all three roles from the brief in the prompt and nothing else. In particular
the verifier branch only reads the verifier brief, so it cannot use anything the
dispatcher did not put there. Same inputs always give the same reply.
"""

from __future__ import annotations

import json
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Union

from ..errors import ModelError
from ..parsing import read_brief
from . import rules
from .base import ModelRequest

# A scripted worker reply: a dict (sent as JSON), a raw string (sent as is, so tests can
# script malformed replies), or a function of the worker brief returning either.
Reply = Union[dict, str, Callable[[dict], Union[dict, str]]]

_SPLIT = re.compile(r";|,|\bthen\b|\band\b", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9-]{2,}")
_STOP = {"the", "and", "then", "for", "with", "that", "this", "from", "into", "write", "make", "draft"}


@dataclass
class MockScript:
    """What the mock should say. Anything not scripted falls back to a compliant default."""

    plans: dict[str, dict] = field(default_factory=dict)  # goal -> lead reply
    worker_replies: dict[str, list[Reply]] = field(default_factory=dict)  # task id -> one per attempt
    verifier_replies: dict[str, list[str]] = field(default_factory=dict)  # task id -> raw replies, in call order
    fail_roles: frozenset[str] = frozenset()  # roles whose calls raise ModelError


class MockModel:
    name = "mock"

    def __init__(self, script: MockScript | None = None) -> None:
        self.script = script or MockScript()
        self.calls: Counter[str] = Counter()
        self._verifier_seen: Counter[str] = Counter()
        self._lock = threading.Lock()

    def complete(self, request: ModelRequest) -> str:
        with self._lock:
            self.calls[request.role] += 1
        if request.role in self.script.fail_roles:
            raise ModelError(f"mock outage for role {request.role}")
        brief = read_brief(request.prompt)
        if request.role == "lead":
            return self._lead(brief)
        if request.role == "worker":
            return self._worker(brief)
        if request.role == "verifier":
            return self._verifier(brief)
        raise ModelError(f"mock has no behavior for role {request.role!r}")

    # lead -----------------------------------------------------------------

    def _lead(self, brief: dict) -> str:
        goal = brief["goal"]
        if goal in self.script.plans:
            return json.dumps(self.script.plans[goal])
        return json.dumps(generic_plan(goal, int(brief.get("max_tasks", 8))))

    # worker ---------------------------------------------------------------

    def _worker(self, brief: dict) -> str:
        task = brief["task"]
        scripted = self.script.worker_replies.get(task["id"])
        if scripted:
            reply = scripted[min(brief["attempt"], len(scripted)) - 1]
            if callable(reply):
                reply = reply(brief)
            return reply if isinstance(reply, str) else json.dumps(reply)
        return json.dumps({"output": compliant_output(task), "notes": "built from the criteria"})

    # verifier -------------------------------------------------------------

    def _verifier(self, brief: dict) -> str:
        task = brief["task"]
        scripted = self.script.verifier_replies.get(task["id"])
        if scripted:
            with self._lock:
                index = self._verifier_seen[task["id"]]
                self._verifier_seen[task["id"]] += 1
            return scripted[min(index, len(scripted) - 1)]
        output = brief["claimed_output"]
        checks, objections = [], []
        for criterion in task["criteria"]:
            passed, evidence = rules.evaluate(criterion, output)
            checks.append({"criterion": criterion, "passed": passed, "evidence": evidence})
            if not passed:
                objections.append(f"{criterion} -> {evidence}")
        return json.dumps(
            {
                "verdict": "refuted" if objections else "stands",
                "objections": objections,
                "checks": checks,
            }
        )


def generic_plan(goal: str, max_tasks: int) -> dict:
    """Split an arbitrary goal into independent tasks with criteria the mock can check."""
    parts = [p.strip(" .") for p in _SPLIT.split(goal)]
    parts = [p for p in parts if len(p) > 3][:max_tasks] or [goal.strip() or "the goal"]
    tasks = []
    for number, part in enumerate(parts, start=1):
        words = [w for w in _WORD.findall(part) if w.lower() not in _STOP]
        keyword = max(words, key=len) if words else part
        tasks.append(
            {
                "id": f"T{number}",
                "title": part[:1].upper() + part[1:],
                "instructions": f"Produce a short deliverable for: {part}.",
                "criteria": [f"include: {keyword}", "min_bullets: 2", "max_words: 80"],
                "depends_on": [],
            }
        )
    return {"tasks": tasks}


def compliant_output(task: dict) -> str:
    """An output that satisfies every rule-form criterion of the task."""
    lines = [task["title"]]
    bullets_needed = 0
    priced = False
    for criterion in task["criteria"]:
        kind, arg = rules.split_criterion(criterion)
        if kind == "include":
            lines.append(f"- {arg}")
        elif kind == "min_bullets" and arg.isdigit():
            bullets_needed = int(arg)
        elif kind == "total_matches_items":
            priced = True
    if priced:
        lines += ["- first item: 10", "- second item: 5"]
    have = sum(1 for line in lines if line.startswith("- "))
    lines += [f"- step {n}" for n in range(1, bullets_needed - have + 1)]
    if priced:
        lines.append("Total: 15")
    return "\n".join(lines)
