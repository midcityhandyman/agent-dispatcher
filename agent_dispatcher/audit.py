"""Checks the context separation from the ledger, after the fact.

Returns a list of findings. Empty means every prompt that was actually sent respected
the boundaries. It reads literal prompt text, so it works for any Model implementation.
"""

from __future__ import annotations

from .parsing import read_brief
from .types import RunReport

_VERIFIER_KEYS = {"task", "inputs", "claimed_output"}
_TASK_KEYS = {"id", "title", "instructions", "criteria"}


def audit_isolation(report: RunReport) -> list[str]:
    findings: list[str] = []
    ledger = report.ledger

    notes = [
        (rec.task.id, att.number, att.result.notes)
        for rec in report.records
        for att in rec.attempts
        if att.result and att.result.notes.strip()
    ]

    for entry in ledger.entries(role="verifier"):
        where = f"verifier prompt for {entry.task_id} attempt {entry.attempt}"
        brief = read_brief(entry.prompt)
        extra = set(brief) - _VERIFIER_KEYS
        if extra:
            findings.append(f"{where} has unexpected fields: {sorted(extra)}")
        extra = set(brief.get("task", {})) - _TASK_KEYS
        if extra:
            findings.append(f"{where} task spec has unexpected fields: {sorted(extra)}")
        for task_id, number, text in notes:
            if text in entry.prompt:
                findings.append(f"{where} contains worker notes from {task_id} attempt {number}")

    for rec in report.records:
        allowed = set(rec.task.depends_on)
        for entry in ledger.entries(role="worker", task_id=rec.task.id):
            where = f"worker prompt for {entry.task_id} attempt {entry.attempt}"
            brief = read_brief(entry.prompt)
            extra = set(brief.get("inputs", {})) - allowed
            if extra:
                findings.append(f"{where} was given outputs it does not depend on: {sorted(extra)}")
            for task_id, number, text in notes:
                if text in entry.prompt:
                    findings.append(f"{where} contains worker notes from {task_id} attempt {number}")
            for att in rec.attempts:
                # A retry gets the objections, not the rejected draft.
                if att.result and att.number < entry.attempt and att.result.output in entry.prompt:
                    findings.append(f"{where} contains the rejected output of attempt {att.number}")
    return findings
