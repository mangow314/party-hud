"""Sidebar integration tests on a separate tmux server (-L party-test), leaving your running tmux alone.

A real client is attached through `script` (util-linux or BSD/macOS), so "visible" means the same as for you.
The tests run in file order and share one server: each step builds on the state the previous one left.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time

import pytest

pytestmark = pytest.mark.tmux

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARTY = os.path.join(ROOT, "party.py")
PY = f"python3 {shlex.quote(PARTY)}"
FAKE_AGY = """#!/usr/bin/env python3
import time
print("ready", flush=True)
input()
print("\\nparty-test-reply-42", flush=True)
time.sleep(120)
"""


class Server:
    def __init__(self):
        self.tmp = tempfile.mkdtemp()
        env = dict(os.environ)
        env.pop("TMUX", None)
        env.pop("TMUX_PANE", None)
        # sort order follows the locale and differs on macOS; LC_ALL would override LC_COLLATE, so keep it as LC_CTYPE
        if env.get("LC_ALL"):
            env["LC_CTYPE"] = env.pop("LC_ALL")
        env.pop("LC_ALL", None)
        env.update(
            LC_COLLATE="C",
            XDG_RUNTIME_DIR=os.path.join(self.tmp, "xdg"),
            XDG_STATE_HOME=os.path.join(self.tmp, "state"),
            TMUX_TMPDIR=self.tmp,
            PYTHONDONTWRITEBYTECODE="1",
        )
        os.makedirs(env["XDG_RUNTIME_DIR"])
        self.env = env
        self.client: subprocess.Popen[bytes] | None = None
        self.fake = os.path.join(self.tmp, "fake")
        self.host = self.side0 = self.member = self.crew = self.sent = self.shell = self.rwin = self.report = ""

    def t(self, *args: str) -> str:
        p = self.run("tmux", "-L", "party-test", *args)
        if p.returncode:
            pytest.fail(f"tmux {shlex.join(args)} exited {p.returncode}: {p.stderr.strip()}")
        return p.stdout.rstrip("\n")

    def run(self, *cmd: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(cmd, env=env or self.env, capture_output=True, text=True, check=False, timeout=60)

    def lines(self, *args: str) -> list[str]:
        out = self.t(*args)
        return out.split("\n") if out else []

    def sidebars(self) -> int:
        return self.lines("list-panes", "-a", "-F", "#{@party_sidebar}").count("1")

    def running(self) -> int:
        return self.lines("list-panes", "-a", "-F", "#{@party_sidebar} #{pane_dead}").count("1 0")

    def windows(self) -> int:
        return len(self.lines("list-windows", "-a"))

    def hooks(self, pattern: str) -> int:
        return len([h for h in self.lines("show-hooks", "-g") if re.search(pattern, h)])

    def sidebar_widths(self, target: str) -> list[str]:
        rows = self.lines("list-panes", *target.split(), "-F", "#{@party_sidebar} #{pane_width}")
        return [r.split()[1] for r in rows if r.startswith("1 ")]

    def pane(self, target: str, sidebar: bool) -> str:
        rows = self.lines("list-panes", *target.split(), "-F", "#{pane_id} #{@party_sidebar}")
        return next(r.split()[0] for r in rows if r.endswith(" 1") == sidebar)

    def sidebar_alive(self, window: str) -> bool:
        return "1 0" in self.lines("list-panes", "-t", window, "-F", "#{@party_sidebar} #{pane_dead}")

    def seqno(self) -> int:
        try:
            with open(os.path.join(self.env["XDG_RUNTIME_DIR"], "party-hud", "snapshot.json")) as f:
                return json.load(f)["seq"]
        except (OSError, ValueError, KeyError):
            return 0

    def place(self, pane: str) -> str:
        return self.t("display", "-p", "-t", pane, "#{session_name}:#{window_index}.#{pane_index}")

    def as_host(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = dict(
            self.env,
            PATH=f"{self.fake}:{self.env['PATH']}",
            TMUX=self.t("display", "-p", "#{socket_path},#{pid},0"),
            TMUX_PANE=self.host,
        )
        return self.run("python3", PARTY, *args, env=env)

    def attach(self):
        attach = "stty cols 200 rows 50; tmux -L party-test attach -t a"
        env = dict(self.env, TERM="xterm-256color")
        if self.run("script", "--version").returncode == 0:
            cmd = ["script", "-qfc", attach, "/dev/null"]  # util-linux (Linux)
        else:
            cmd = ["script", "-q", "/dev/null", "sh", "-c", attach]  # BSD (macOS): script [-q] file command...
        # an open stdin pipe keeps the client alive without needing your terminal
        self.client = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env
        )
        for _ in range(40):
            if self.t("list-clients", "-F", "x"):
                return True
            time.sleep(0.25)
        return False

    def close(self):
        try:
            self.run("tmux", "-L", "party-test", "kill-server")
        finally:
            try:
                if self.client:
                    self.stop_client(self.client)
            finally:
                shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def stop_client(client: subprocess.Popen[bytes]):
        try:
            if client.stdin:
                client.stdin.close()
        finally:
            client.terminate()
            try:
                client.wait(timeout=5)
            except subprocess.TimeoutExpired:
                client.kill()
                client.wait()


@pytest.fixture(scope="module")
def srv():
    s = Server()
    try:
        s.t("-f", "/dev/null", "new-session", "-d", "-s", "a", "-x", "200", "-y", "50")
        # trailing colon = next free index in that session; plain a may resolve to a window and hit index in use
        s.t("new-window", "-t", "a:")
        s.t("new-session", "-d", "-s", "b", "-x", "200", "-y", "50")
        if not s.attach():
            pytest.fail("cannot attach a test client (needs util-linux or BSD script)")
        yield s
    finally:
        s.close()


def test_client_attached_to_session_a(srv):
    assert srv.t("list-clients", "-F", "#{session_name}") == "a"


def test_party_tmux_binds_four_keys(srv):
    srv.t("run-shell", os.path.join(ROOT, "party.tmux"))
    assert sum("party.py" in k for k in srv.lines("list-keys")) == 4


def test_party_tmux_leaves_passthrough_off_globally(srv):
    assert srv.t("show", "-gv", "allow-passthrough") == "off"


def test_toggle_on_every_window_has_a_sidebar(srv):
    srv.t("run-shell", f"{PY} --toggle")
    time.sleep(2)
    assert srv.sidebars() == srv.windows() == 3


def test_toggle_on_passthrough_on_for_sidebars_only(srv):
    rows = srv.lines("list-panes", "-a", "-F", "#{@party_sidebar}:#{allow-passthrough}")
    assert sorted(set(rows)) == ["1:on", ":off"]


def test_toggle_on_new_window_hook(srv):
    assert srv.hooks(r"new-window\[90\]") == 1


def test_toggle_on_switch_hooks(srv):
    assert srv.hooks(r"(client-session|session-window)-changed\[90\]") == 2


def test_toggle_on_tidy_and_attach_hooks(srv):
    assert srv.hooks(r"(after-kill-pane|client-attached)\[90\]") == 2


def test_memory_only_visible_sidebar_runs(srv):
    # sidebars you cannot see stop their process after 2 s; the pane stays (dead, keeps its last frame)
    time.sleep(4)
    assert srv.running() == 1


def test_memory_hidden_sidebar_panes_stay(srv):
    assert srv.sidebars() == srv.windows()


def test_switch_window_restarts_its_sidebar_within_1s(srv):
    srv.t("select-window", "-t", "a:0")
    start = time.monotonic()
    for _ in range(40):
        if srv.sidebar_alive("a:0"):
            break
        time.sleep(0.05)
    ms = int((time.monotonic() - start) * 1000)
    assert ms <= 1000, f"sidebar restarted {ms} ms after switching window"


def test_switch_window_left_window_stops_after_2s(srv):
    time.sleep(4)
    assert srv.running() == 1


def test_new_window_gets_a_sidebar(srv):
    srv.t("new-window", "-t", "a:")
    time.sleep(2)
    assert srv.sidebars() == srv.windows()


def test_sidebar_width_is_default_34(srv):
    assert set(srv.sidebar_widths("-a")) == {"34"}


def test_window_resize_returns_width_to_34(srv):
    srv.t("resize-window", "-t", "a:1", "-x", "150")
    time.sleep(4)
    assert srv.sidebar_widths("-t a:1") == ["34"]


def test_dragged_wider_stays_40(srv):
    srv.side0 = srv.pane("-t a:0", sidebar=True)
    srv.t("resize-pane", "-t", srv.side0, "-x", "40")
    # same as finishing a mouse border drag (MouseDragEnd1Border)
    srv.t("run-shell", f"{PY} --remember-width")
    time.sleep(2)
    assert srv.t("display", "-p", "-t", srv.side0, "#{pane_width}") == "40"


def test_dragged_wider_remembered_globally(srv):
    assert srv.t("show", "-gqv", "@party_sidebar_width") == "40"


def test_later_windows_get_the_remembered_width(srv):
    srv.t("new-window", "-d", "-t", "b:")
    time.sleep(2)
    assert srv.sidebar_widths("-t b:1") == ["40"]


def test_dragged_below_minimum_bounces_to_30(srv):
    srv.t("resize-pane", "-t", srv.side0, "-x", "25")
    srv.t("run-shell", f"{PY} --remember-width")
    time.sleep(2)
    assert srv.t("display", "-p", "-t", srv.side0, "#{pane_width}") == "30"


def test_dragged_below_minimum_remembers_30(srv):
    assert srv.t("show", "-gqv", "@party_sidebar_width") == "30"


def test_bell_flags_hidden_window_with_waiting_member(srv):
    srv.t("set-option", "-p", "-t", srv.pane("-t b:0", sidebar=False), "@workmux_pane_status", "💬")
    time.sleep(5)
    assert srv.t("display", "-p", "-t", "b:0", "#{window_bell_flag}") == "1"


def test_party_reports_counts_waiting_member(srv):
    assert int(srv.t("show", "-gqv", "@party_reports") or 0) >= 1


def test_killing_main_pane_closes_hidden_window(srv):
    before = srv.windows()
    srv.t("kill-pane", "-t", srv.pane("-t a:1", sidebar=False))
    time.sleep(3)
    assert srv.windows() == before - 1


def test_main_program_exit_closes_hidden_window(srv):
    # no kill-pane, so no hook runs: the collector closes it
    before = srv.windows()
    srv.t("send-keys", "-t", srv.pane("-t b:1", sidebar=False), "exit", "Enter")
    time.sleep(5)
    assert srv.windows() == before - 1


def test_performance_about_one_collection_per_2s(srv):
    srv.t("new-session", "-d", "-s", "c", "-x", "200", "-y", "50")
    for _ in range(19):
        srv.t("new-window", "-d", "-t", "c:")
    time.sleep(4)
    seq1 = srv.seqno()
    time.sleep(10)
    n = srv.seqno() - seq1
    assert 3 <= n <= 6, f"{srv.sidebars()} sidebars, {srv.running()} running, {n} collections in 10 s"


def test_memory_at_most_2_processes_with_many_sidebars(srv):
    assert srv.running() <= 2, f"{srv.sidebars()} sidebars"


def test_report_opens_one_marked_pane(srv):
    srv.host = srv.pane("-a", sidebar=False)
    srv.t("run-shell", "-t", srv.host, f"{PY} --open-report")
    time.sleep(2)
    reports = [
        r.split()[0] for r in srv.lines("list-panes", "-a", "-F", "#{pane_id} #{@party_report}") if r.endswith(" 1")
    ]
    srv.report = reports[0] if reports else ""
    assert len(reports) == 1


def test_report_pane_has_passthrough_on(srv):
    assert srv.t("display", "-p", "-t", srv.report, "#{allow-passthrough}") == "on"


def test_report_passthrough_stays_off_globally(srv):
    assert srv.t("show", "-gv", "allow-passthrough") == "off"


def test_report_main_pane_passthrough_still_off(srv):
    try:
        assert srv.t("display", "-p", "-t", srv.host, "#{allow-passthrough}") == "off"
    finally:
        if srv.report:
            srv.t("kill-pane", "-t", srv.report)


def test_summon_prints_the_new_pane_id(srv):
    os.makedirs(os.path.join(srv.fake, "real"))
    real = os.path.join(srv.fake, "real", "agy")
    with open(real, "w") as f:
        f.write(FAKE_AGY)
    # the python child is what agent_kind recognises ("python3 .../agy"); the wrapper must not exec it
    with open(os.path.join(srv.fake, "agy"), "w") as f:
        f.write(f'#!/usr/bin/env bash\npython3 "{real}"\necho done\n')
    os.chmod(real, 0o755)
    os.chmod(os.path.join(srv.fake, "agy"), 0o755)
    # tmux 3.8 gives a split-window pane the PATH of the client that sent the command, not the global one; set both
    srv.t("set-environment", "-g", "PATH", f"{srv.fake}:{srv.env['PATH']}")
    p = srv.as_host("--summon", "agy", "--timeout", "30")
    srv.member = p.stdout.rstrip("\n")
    srv.crew = f"crew-{srv.host.lstrip('%')}"
    assert p.returncode == 0, p.stderr
    assert re.fullmatch(r"%\d+", srv.member), p.stderr


def test_summon_member_sits_in_crew_session(srv):
    assert srv.t("display", "-p", "-t", srv.member, "#{session_name}") == srv.crew


def test_summon_crew_session_has_no_sidebar(srv):
    time.sleep(1)
    assert srv.lines("list-panes", "-s", "-t", srv.crew, "-F", "#{@party_sidebar}").count("1") == 0


def test_ask_prints_the_time_it_sent(srv):
    p = srv.as_host("--ask", srv.member, "hello")
    srv.sent = p.stdout.rstrip("\n")
    assert p.returncode == 0, p.stderr
    assert srv.sent, p.stderr


def test_report_text_wait_after_returns_the_reply(srv):
    p = srv.as_host("--report-text", srv.member, "--wait", "--after", srv.sent, "--timeout", "30")
    assert (p.stdout.rstrip("\n"), p.returncode) == ("party-test-reply-42", 0), p.stderr


def test_dismiss_closes_a_member_whose_report_was_read(srv):
    p = srv.as_host("--dismiss", srv.member)
    assert (p.stdout, p.returncode) == ("", 0), p.stderr


def test_dismiss_last_member_ends_crew_session(srv):
    assert srv.run("tmux", "-L", "party-test", "has-session", "-t", f"={srv.crew}").returncode != 0


# tmux display-message exits 0 for a pane that is gone; only a real server shows that
@pytest.mark.parametrize("args", [("--report-text",), ("--ask", "hello"), ("--dismiss",)], ids=lambda a: a[0])
def test_gone_member_names_the_missing_pane_and_exits_2(srv, args):
    p = srv.as_host(args[0], srv.member, *args[1:])
    assert (p.stdout + p.stderr, p.returncode) == (f"no such pane: {srv.member}\n", 2)


def test_sidebar_panes_are_titled_party_hud(srv):
    rows = srv.lines("list-panes", "-a", "-F", "#{@party_sidebar} #{pane_title}")
    assert {r for r in rows if r.startswith("1 ")} == {"1 party-hud"}


def test_restore_adds_no_sidebar_while_running(srv):
    srv.t("run-shell", f"{PY} --restore-begin")
    # now the client's window: tmux answers for its active pane when a target is missing
    srv.rwin = srv.t("new-window", "-t", "a:", "-P", "-F", "#{window_id}")
    time.sleep(1)
    assert len(srv.lines("list-panes", "-t", srv.rwin)) == 1


def test_restore_the_pane_named_becomes_a_sidebar(srv):
    # stands for the shell a restore leaves where the sidebar was
    srv.shell = srv.t("split-window", "-hbf", "-d", "-l", "34", "-t", srv.rwin, "-P", "-F", "#{pane_id}")
    places = " ".join(shlex.quote(p) for p in (srv.place(srv.shell), srv.place(srv.host), "nowhere:9.9"))
    srv.t("run-shell", f"{PY} --restore-end {places}")
    time.sleep(1)
    assert srv.t("display", "-p", "-t", srv.shell, "#{@party_sidebar} #{pane_title}") == "1 party-hud"


def test_restore_leaves_older_pane_and_missing_place_alone(srv):
    assert srv.sidebars() == srv.windows()


def test_restore_older_pane_still_runs_its_program(srv):
    assert srv.t("display", "-p", "-t", srv.host, "#{@party_sidebar}#{pane_dead}") == "0"


def test_restore_new_windows_get_a_sidebar_afterwards(srv):
    srv.t("new-window", "-d", "-t", "a:")
    time.sleep(1)
    assert srv.sidebars() == srv.windows()


def test_restore_end_without_begin_exits_2(srv):
    p = srv.as_host("--restore-end", srv.place(srv.host))
    assert (p.stdout + p.stderr, p.returncode) == ("--restore-end: run --restore-begin before the restore\n", 2)


def test_q_in_a_sidebar_closes_all_sidebars(srv):
    rows = srv.lines("list-panes", "-a", "-F", "#{pane_id} #{@party_sidebar} #{pane_dead}")
    srv.t("send-keys", "-t", next(r.split()[0] for r in rows if r.endswith(" 1 0")), "q")
    time.sleep(3)
    assert srv.sidebars() == 0


def test_toggle_off_removes_hooks(srv):
    pattern = r"(new-window|client-session-changed|session-window-changed|after-kill-pane|client-attached)\[90\]"
    assert srv.hooks(pattern) == 0


def test_toggle_off_all_sessions_still_exist(srv):
    assert len(srv.lines("list-sessions")) == 3
