"""scripts/check.py: every step runs, a failed or missing one is named, and the exit code says so."""

import sys

from scripts import check

OK = [sys.executable, "-c", "print('ran-ok')"]
BAD = [sys.executable, "-c", "raise SystemExit(3)"]


def test_all_steps_pass(capfd):
    assert check.run([("one", OK), ("two", OK)]) == 0
    assert "== all 2 checks passed" in capfd.readouterr().out


def test_failed_step_is_named_and_later_steps_still_run(capfd):
    assert check.run([("one", BAD), ("two", OK)]) == 1
    out = capfd.readouterr().out
    assert "ran-ok" in out
    assert out.rstrip().endswith("== FAILED: one")


def test_missing_tool_fails_its_step(capfd):
    assert check.run([("one", ["party-hud-no-such-tool"]), ("two", OK)]) == 1
    out = capfd.readouterr().out
    assert "party-hud-no-such-tool: command not found" in out
    assert out.rstrip().endswith("== FAILED: one")
