"""Offline demo. No keys, no network, same output every time.

    python demo/run_demo.py > demo/output.txt

Runs the scripted scenario and prints the timeline, the outcome, and the isolation audit.
Two of the seven tasks are meant to end rejected and blocked, so this script exits 0
whenever the run completes; use `python -m agent_dispatcher demo` if you want the exit
code to reflect the outcome.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_dispatcher import Dispatcher  # noqa: E402
from agent_dispatcher.cli import print_report  # noqa: E402
from agent_dispatcher.models import MockModel  # noqa: E402
from agent_dispatcher.scenarios import garden_day  # noqa: E402


def main() -> int:
    goal, script = garden_day()
    # Separate model objects for the workers and the verifier, as you would run it for real.
    report = Dispatcher(MockModel(script), MockModel(script), MockModel(script)).run(goal)
    print_report(report)

    t3 = report.record("T3").attempts[0]
    print("== A CLOSER LOOK: T3, ATTEMPT 1 ==")
    print("worker said (never shown to the verifier):")
    print(f"    {t3.result.notes}")
    print("verifier found:")
    for check in t3.verdict.checks:
        print(f"    [{'pass' if check.passed else 'FAIL'}] {check.criterion}: {check.evidence}")
    print("the line in the output addressed to the reviewer changed nothing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
