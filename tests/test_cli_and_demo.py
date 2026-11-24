import json
import subprocess
import sys
from pathlib import Path

from agent_dispatcher.cli import main

ROOT = Path(__file__).resolve().parent.parent


def test_demo_command_reports_and_signals_incomplete(capsys):
    assert main(["demo"]) == 2  # the scenario ends with one rejected and one blocked task
    out = capsys.readouterr().out
    assert "5 accepted, 1 rejected, 1 blocked" in out
    assert "clean: no prompt contained anything outside its brief" in out


def test_run_with_mock_on_a_free_goal(capsys):
    assert main(["run", "--goal", "draft the agenda, then list the action items"]) == 0
    assert "2 accepted, 0 rejected, 0 blocked" in capsys.readouterr().out


def test_json_report_includes_every_prompt(tmp_path, capsys):
    path = tmp_path / "report.json"
    main(["demo", "--json", str(path)])
    capsys.readouterr()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["counts"] == {"accepted": 5, "rejected": 1, "blocked": 1}
    assert len(data["contexts"]) == 19  # 1 lead + 9 workers + 9 verifiers
    assert data["tasks"][0]["attempts"][0]["refuted"] is True


def test_bad_arguments_exit_with_an_error(capsys):
    assert main(["run", "--goal", "   "]) == 1
    assert main(["demo", "--max-attempts", "0"]) == 1
    assert "error:" in capsys.readouterr().err


def test_more_attempts_do_not_rescue_a_task_that_never_fixes_itself(capsys):
    assert main(["demo", "--max-attempts", "4"]) == 2
    assert "T5   rejected  Sponsor banner text  (4 attempts)" in capsys.readouterr().out


def test_demo_script_matches_the_captured_output():
    result = subprocess.run(
        [sys.executable, str(ROOT / "demo" / "run_demo.py")], capture_output=True, text=True, check=True
    )
    captured = (ROOT / "demo" / "output.txt").read_text(encoding="utf-8")
    assert result.stdout.splitlines() == captured.splitlines()


def test_module_entry_point():
    result = subprocess.run(
        [sys.executable, "-m", "agent_dispatcher", "run", "--goal", "write a haiku about rain"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "1 accepted" in result.stdout
