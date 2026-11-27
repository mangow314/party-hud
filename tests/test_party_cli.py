"""party.py main: each sub-command imports only what it needs, and the resident ones leave without teardown."""

import fcntl
import io
import json
import os
import pty
import select
import struct
import subprocess
import sys
import termios
import time

import pytest

import party
from party_hud import ui

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sidebar.json")
PARTY = os.path.join(ROOT, "party.py")

IMPORT_CHILD = """
import importlib, json, sys
argv, targets = json.loads(sys.argv[1]), json.loads(sys.argv[2])
sys.argv = ["party.py", *argv]
sys.path.insert(0, @ROOT@)
import party
calls = []
def fake(name):
    return lambda *a, **k: calls.append([name, list(a)]) or (0, "", "")
for t in targets:
    mod, _, name = t.rpartition(".")
    setattr(importlib.import_module(mod), name, fake(t))
    if mod == "party_hud.ui":
        importlib.import_module(mod).leave_without_teardown = lambda: None
rc = 0
try:
    party.main()
except SystemExit as e:
    rc = e.code
print(json.dumps({"calls": calls, "rc": rc, "loaded": [m for m in ("argparse", "shutil", "typing", "traceback", "party_hud.ui", "party_hud.render") if m in sys.modules]}))
""".replace("@ROOT@", repr(ROOT))


def run_main(argv, target):
    """Run party.main in a fresh interpreter with target replaced by a recorder: its calls, exit code and modules loaded."""
    r = subprocess.run(
        [sys.executable, "-c", IMPORT_CHILD, json.dumps(argv), json.dumps([target])],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert r.returncode == 0, r.stderr[-300:]
    return json.loads(r.stdout)


LONG_RUN = ("argparse", "shutil", "typing", "traceback")
SHORT = ("party_hud.ui", "party_hud.render")
UI = "party_hud.ui."

CASES = [
    (["--sidebar"], UI + "run_ui", [], LONG_RUN),
    (["--select"], UI + "run_menu", [], LONG_RUN),
    (["--report"], UI + "run_report", [None], LONG_RUN),
    (["--report", "%5"], UI + "run_report", ["%5"], LONG_RUN),
    (["--ensure", "@1"], "party.ensure", ["@1"], SHORT),
    (["--reflow", "@1"], "party.reflow", ["@1"], SHORT),
    (["--nudge"], "party.nudge", [""], SHORT),
    (["--nudge", "@2"], "party.nudge", ["@2"], SHORT),
    (["--tidy"], "party.tidy", [], SHORT),
    (["--restore-begin"], "party.restore_begin", [], SHORT),
    (["--restore-end"], "party.restore_end", [[]], SHORT),
    (["--restore-end", "a:1.1", "b:2.1"], "party.restore_end", [["a:1.1", "b:2.1"]], SHORT),
    (["--remember-width"], "party.remember_width", [], SHORT),
    (["--toggle"], "party.toggle", [], SHORT),
    (["--ask", "%5", "hi"], "party.ask", ["%5", "hi"], SHORT),
    (["--dismiss", "%5"], "party.dismiss", ["%5"], SHORT),
    (["--summon", "codex"], "party.summon", ["codex", None, False, 60, False, False, None], SHORT),
    (
        ["--summon", "codex", "--model", "m-1", "--read-only", "--cwd", "/d", "--here"],
        "party.summon",
        ["codex", "/d", False, 60, True, True, "m-1"],
        SHORT,
    ),
    (["--report-text", "%5"], "party.report_text", ["%5", False, 600, None, {}], SHORT),
    (["--open-report", "%5"], "party.open_report_pane", ["", "%5"], SHORT),
    (["--sidebar", "--fixture", "F"], UI + "run_ui", ["F"], ()),
    (["--select", "--fixture", "F"], UI + "run_menu", ["F"], ()),
    (["--report", "%1", "--fixture", "F"], UI + "run_report", ["%1", "F"], ()),
    (["--report", "--fixture", "F"], UI + "run_report", [None, "F"], ()),
    (["--report", ""], UI + "run_report", [None], LONG_RUN),
]


@pytest.mark.parametrize(("argv", "target", "args", "forbidden"), CASES, ids=[" ".join(c[0]) or "''" for c in CASES])
def test_each_sub_command_calls_its_function_and_loads_only_what_it_needs(argv, target, args, forbidden):
    out = run_main(argv, target)
    assert out["calls"] == [[target, args]]
    assert out["rc"] in (0, None, 5, 6, 7)
    assert not [m for m in out["loaded"] if m in forbidden]


def test_model_without_summon_is_rc_2_and_runs_nothing():
    out = run_main(["--ask", "%5", "hi", "--model", "m-1"], "party.ask")
    assert out["rc"] == 2
    assert out["calls"] == []


def test_fixture_goes_through_argparse():
    assert "argparse" in run_main(["--report", "%1", "--fixture", "F"], UI + "run_report")["loaded"]


def test_help_prints_the_usage_description_and_exit_codes():
    r = subprocess.run([sys.executable, PARTY, "--help"], capture_output=True, text=True, cwd=ROOT, check=False)
    flat = " ".join(r.stdout.split())
    assert r.returncode == 0
    assert flat.startswith("usage: party.py")
    assert "tmux party sidebar: sessions as squads, agents as members" in flat
    assert "Exit code 6: the rules do not allow it (stderr says which one)." in flat
    assert "--model MODEL with --summon: start the agent on MODEL" in flat
    assert "exit code 8: the member hit its usage limit" in flat


def test_a_mistyped_flag_is_rc_2_and_named():
    r = subprocess.run([sys.executable, PARTY, "--sidbar"], capture_output=True, text=True, cwd=ROOT, check=False)
    assert r.returncode == 2
    assert "unrecognized arguments: --sidbar" in r.stderr


def list_json(*argv):
    return subprocess.run(
        [sys.executable, PARTY, *argv, "--fixture", FIXTURE], capture_output=True, text=True, cwd=ROOT, check=False
    )


def test_list_json_prints_every_agent_with_the_six_keys_and_a_null_lead():
    r = list_json("--list", "--json")
    agents = json.loads(r.stdout)
    assert r.returncode == 0
    assert [list(a) for a in agents] == [["pane", "kind", "name", "status", "cwd", "lead"]] * 3
    assert {a["pane"] for a in agents} == {"%1", "%2", "%4"}
    assert next(a for a in agents if a["pane"] == "%2") == {
        "pane": "%2",
        "kind": "claude",
        "name": "審查員",
        "status": "waiting",
        "cwd": "/r/studio/src",
        "lead": None,
    }


def test_list_json_gives_a_summoned_member_its_lead_pane(tmp_path):
    with open(FIXTURE, encoding="utf-8") as f:
        fixture = json.load(f)
    next(p for p in fixture["panes"] if p["pane_id"] == "%2")["@party_lead"] = "%1"
    path = tmp_path / "crew.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, PARTY, "--list", "--json", "--fixture", str(path)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert r.returncode == 0
    assert {a["pane"]: a["lead"] for a in json.loads(r.stdout)} == {"%1": None, "%2": "%1", "%4": None}


@pytest.mark.parametrize(("flag", "message"), [("--list", "--list needs --json"), ("--json", "--json needs --list")])
def test_list_and_json_without_each_other_are_rc_2_and_print_nothing(flag, message):
    r = list_json(flag)
    assert r.returncode == 2
    assert r.stdout == ""
    assert r.stderr.splitlines()[-1] == f"party.py: error: {message}"


class Stream(io.StringIO):
    def __init__(self, name, events):
        super().__init__()
        self.name = name
        self.events = events

    def flush(self):
        self.events.append(self.name + " flush")


@pytest.fixture
def main_with(monkeypatch):
    """party.main with the screens replaced by one that writes and may raise; events is filled in order."""

    def run(argv, events, screen_error=None):

        def screen(*a, **k):
            events.append("screen")
            sys.stdout.write("last bytes")
            if screen_error:
                raise screen_error

        for name in ("run_ui", "run_menu", "run_report"):
            monkeypatch.setattr(ui, name, screen)
        monkeypatch.setattr(os, "_exit", lambda rc: events.append(f"exit {rc}"))
        monkeypatch.setattr(sys, "stdout", Stream("out", events))
        monkeypatch.setattr(sys, "stderr", Stream("err", events))
        monkeypatch.setattr(sys, "argv", ["party.py", *argv])
        party.main()

    return run


RESIDENT = [["--sidebar"], ["--select"], ["--report"], ["--report", "%5"]]


@pytest.mark.parametrize("argv", RESIDENT, ids=" ".join)
def test_resident_sub_command_flushes_both_streams_then_exits_0_after_its_screen(main_with, argv):
    events = []
    main_with(argv, events)
    assert events == ["screen", "out flush", "err flush", "exit 0"]


@pytest.mark.parametrize("argv", RESIDENT, ids=" ".join)
def test_resident_screen_that_raises_propagates_and_does_not_exit_early(main_with, argv):
    events = []
    with pytest.raises(RuntimeError, match="boom"):
        main_with(argv, events, RuntimeError("boom"))
    assert events == ["screen"]


@pytest.mark.parametrize(
    "argv",
    [["--sidebar", "--fixture", "F"], ["--select", "--fixture", "F"], ["--report", "%1", "--fixture", "F"]],
    ids=" ".join,
)
def test_the_argparse_path_does_not_exit_early(main_with, argv):
    events = []
    main_with(argv, events)
    assert events == ["screen"]


LEAVE_CHILD = """
import sys
sys.path.insert(0, @ROOT@)
sys.argv = ["party.py", "--report", "%1"]
import party
from party_hud import claude_log, codex_log, collect, processes, ui
ui.get_snapshot = lambda f=None: collect.collect(@FIXTURE@)
ui.report_for = lambda a: {"text": "\\n".join(f"L{n}" for n in range(30)), "start": 1, "end": 2}
ui.tmux = lambda *a: "off" if "@party_anim" in a else ""
party.main()
print("NOT REACHED", flush=True)
""".replace("@ROOT@", repr(ROOT)).replace("@FIXTURE@", repr(FIXTURE))


def settled(t):
    # macOS sets PENDIN in the local flags when a terminal goes back to canonical mode
    return [t[0], t[1], t[2], t[3] & ~termios.PENDIN, *t[4:]]


@pytest.fixture(scope="module")
def report_through_party():
    """party.py --report %1 on a pty, q once it has drawn: (exit code, output, terminal settings before, after)."""
    m, sl = pty.openpty()
    fcntl.ioctl(sl, termios.TIOCSWINSZ, struct.pack("HHHH", 10, 60, 0, 0))
    before = termios.tcgetattr(sl)
    env = dict(os.environ, TMUX_PANE="%99")
    p = subprocess.Popen([sys.executable, "-c", LEAVE_CHILD], stdin=sl, stdout=sl, stderr=sl, env=env, close_fds=True)
    out = b""

    def pump(until):
        nonlocal out
        while time.monotonic() < until:
            if select.select([m], [], [], 0.1)[0]:
                try:
                    out += os.read(m, 65536)
                except OSError:
                    return
            elif p.poll() is not None:
                return

    t_end = time.monotonic() + 10
    while b"\x1b[J" not in out and time.monotonic() < t_end:
        pump(time.monotonic() + 0.1)
    os.write(m, b"q")
    pump(time.monotonic() + 10)
    try:
        rc = p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()
        rc = None
    drained = time.monotonic() + 10
    while time.monotonic() < drained and select.select([m], [], [], 0.2)[0]:
        out += os.read(m, 65536)
    after = termios.tcgetattr(sl)
    os.close(m)
    os.close(sl)
    return rc, out.decode(errors="ignore"), before, after


def test_report_pane_through_party_exits_0(report_through_party):
    assert report_through_party[0] == 0


def test_report_pane_through_party_last_writes_mouse_off_cursor_on_and_main_screen(report_through_party):
    text = report_through_party[1]
    assert text.endswith(ui.MOUSE_OFF + "\x1b[?25h\x1b[?1049l")
    assert "NOT REACHED" not in text


def test_report_pane_through_party_restores_the_terminal_settings(report_through_party):
    _, _, before, after = report_through_party
    assert settled(after) == settled(before)
