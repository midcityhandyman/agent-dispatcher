"""Command line entry point.

    python -m agent_dispatcher demo
    python -m agent_dispatcher run --goal "draft the agenda, then list the action items"
    python -m agent_dispatcher run --goal "..." --model claude --json run-report.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .audit import audit_isolation
from .dispatcher import DispatchConfig, Dispatcher
from .errors import DispatchError
from .models.mock import MockModel
from .report import render_accepted, render_summary, render_timeline, to_dict
from .scenarios import garden_day
from .types import RunReport

EXIT_OK, EXIT_NOT_ALL_ACCEPTED, EXIT_ERROR = 0, 2, 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-dispatcher", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--max-attempts", type=int, default=2, help="tries per task (default 2)")
        p.add_argument("--max-parallel", type=int, default=4, help="workers at once (default 4)")
        p.add_argument("--json", metavar="PATH", help="also write the full report, with every prompt, as JSON")

    demo = sub.add_parser("demo", help="run the scripted offline scenario")
    common(demo)

    run = sub.add_parser("run", help="run a goal of your own")
    run.add_argument("--goal", required=True)
    run.add_argument("--model", choices=["mock", "claude"], default="mock")
    run.add_argument("--max-tasks", type=int, default=8)
    common(run)
    return parser


def print_report(report: RunReport, out=None) -> None:
    out = out or sys.stdout
    findings = audit_isolation(report)
    notes = sum(1 for r in report.records for a in r.attempts if a.result and a.result.notes.strip())
    sections = [
        ("GOAL", report.goal),
        ("TIMELINE", render_timeline(report)),
        ("RESULT", render_summary(report)),
        ("ACCEPTED OUTPUTS", render_accepted(report) or "(none)"),
        (
            "ISOLATION AUDIT",
            f"{len(report.ledger.entries(role='worker'))} worker calls, "
            f"{len(report.ledger.entries(role='verifier'))} verifier calls, {notes} sets of worker notes\n"
            + ("clean: no prompt contained anything outside its brief" if not findings else "\n".join(findings)),
        ),
    ]
    for title, body in sections:
        print(f"== {title} ==\n{body}\n", file=out)


def _claude_models():
    from .models.claude import ClaudeModel

    main = ClaudeModel()
    verifier_name = os.environ.get("AGENT_DISPATCHER_VERIFIER_MODEL")
    return main, (ClaudeModel(verifier_name) if verifier_name else main)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "demo":
            goal, script = garden_day()
            model = verifier = MockModel(script)
            max_tasks = 8
        else:
            goal, max_tasks = args.goal, args.max_tasks
            if args.model == "claude":
                model, verifier = _claude_models()
            else:
                model = verifier = MockModel()
        config = DispatchConfig(args.max_attempts, args.max_parallel, max_tasks)
        report = Dispatcher(model, model, verifier, config).run(goal)
    except (DispatchError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print_report(report)
    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(to_dict(report, include_contexts=True), handle, indent=2)
            handle.write("\n")
    return EXIT_OK if report.all_accepted else EXIT_NOT_ALL_ACCEPTED
