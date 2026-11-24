"""Plain text and JSON views of a run."""

from __future__ import annotations

from .types import RunReport, TaskStatus


def render_timeline(report: RunReport) -> str:
    lines = []
    for event in report.events:
        where = f"{event.task_id} a{event.attempt}" if event.attempt else event.task_id
        lines.append(f"{event.seq:>3}  {event.kind:<9} {where:<7} {event.detail}".rstrip())
    return "\n".join(lines)


def render_summary(report: RunReport) -> str:
    lines = []
    for rec in report.records:
        tries = len(rec.attempts)
        if rec.status is TaskStatus.BLOCKED:
            extra = "depends on " + ", ".join(rec.blocked_by)
        else:
            extra = f"{tries} attempt{'s' if tries != 1 else ''}"
        lines.append(f"{rec.task.id:<4} {rec.status.value:<9} {rec.task.title}  ({extra})")
    counts = report.counts()
    lines.append("")
    lines.append(", ".join(f"{counts[s.value]} {s.value}" for s in TaskStatus))
    return "\n".join(lines)


def render_accepted(report: RunReport) -> str:
    blocks = []
    for rec in report.records:
        if rec.status is TaskStatus.ACCEPTED:
            body = "\n".join("    " + line for line in (rec.accepted_output or "").splitlines())
            blocks.append(f"[{rec.task.id}] {rec.task.title}\n{body}")
    return "\n\n".join(blocks)


def to_dict(report: RunReport, include_contexts: bool = False) -> dict:
    data = {
        "goal": report.goal,
        "counts": report.counts(),
        "tasks": [
            {
                "id": rec.task.id,
                "title": rec.task.title,
                "criteria": list(rec.task.criteria),
                "depends_on": list(rec.task.depends_on),
                "status": rec.status.value,
                "blocked_by": list(rec.blocked_by),
                "accepted_output": rec.accepted_output,
                "attempts": [
                    {
                        "number": att.number,
                        "output": att.result.output if att.result else None,
                        "worker_notes": att.result.notes if att.result else None,
                        "refuted": att.verdict.refuted,
                        "verdict_source": att.verdict.source,
                        "objections": list(att.verdict.objections),
                        "checks": [
                            {"criterion": c.criterion, "passed": c.passed, "evidence": c.evidence}
                            for c in att.verdict.checks
                        ],
                    }
                    for att in rec.attempts
                ],
            }
            for rec in report.records
        ],
        "events": [
            {"seq": e.seq, "kind": e.kind, "task_id": e.task_id, "attempt": e.attempt, "detail": e.detail}
            for e in report.events
        ],
    }
    if include_contexts:
        data["contexts"] = [
            {
                "role": e.role,
                "agent_id": e.agent_id,
                "task_id": e.task_id,
                "attempt": e.attempt,
                "prompt": e.prompt,
                "response": e.response,
            }
            for e in report.ledger.entries()
        ]
    return data
