# pyright: reportArgumentType=false
"""report_text's timeout is inferred as int from its default 600; --timeout passes a float, as these tests do."""

import json
import os
import subprocess
import time

import pytest

import party
from party_hud import claude_log, collect, common

FS = collect.FIELD_SEP
GONE_OUT = ("\n", "%3\n")  # what tmux display-message -p -t prints, with exit 0, for a pane that does not exist
A = 1000.0


def agent(s, summons=(), **kw):
    return {"pane": "%5", "kind": "claude", "status": s, "summons": list(summons), **kw}


def snap(s, summons=(), **kw):
    return {"towns": [{"agents": [agent(s, summons, **kw)]}]}


class Fake:
    """collect.report_text with tmux and the snapshot replaced; records tmux calls and snapshot reads."""

    def __init__(self, monkeypatch):
        self.mp = monkeypatch
        self.calls, self.snaps = [], []

    def tmux(self, pane_rc=0, pane_out="%5\n", screen=None):
        def tmux_run(args, timeout=None):
            self.calls.append((tuple(args), timeout))
            if args[0] == "display-message":
                return pane_rc, pane_out, "can't find pane\n" if pane_rc else ""
            if args[0] == "capture-pane" and screen is not None:
                return 0, screen, ""
            return None, "", ""

        self.mp.setattr(collect, "tmux_run", tmux_run)

    def rounds(self, seq):
        seq = list(seq)

        def get_snapshot():
            self.snaps.append(1)
            return seq.pop(0) if len(seq) > 1 else seq[0]

        self.mp.setattr(collect, "get_snapshot", get_snapshot)

    def run(self, rounds, *a, pane_rc=0, pane_out="%5\n", **kw):
        self.calls.clear()
        self.snaps.clear()
        self.rounds(rounds)
        self.tmux(pane_rc, pane_out)
        self.mp.setattr(collect, "report_for", lambda a: {"text": "all done"})
        return collect.report_text(*a, **kw)

    def run_after(self, t, end, kind="claude"):
        self.calls.clear()
        self.mp.setattr(collect, "get_snapshot", lambda: {"t": t, "towns": [{"agents": [agent("idle", kind=kind)]}]})
        self.tmux()
        self.mp.setattr(collect, "report_for", lambda a: {"text": "answer", "end": end} if end is not False else None)
        return collect.report_text("%5", True, 0.3, A)

    def run_waiting(self, t, end, kind="codex"):
        self.calls.clear()
        self.mp.setattr(collect, "get_snapshot", lambda: {"t": t, "towns": [{"agents": [agent("waiting", kind=kind)]}]})
        self.tmux(screen="".join(f"line {i}\n\n" for i in range(30)))
        self.mp.setattr(collect, "report_for", lambda a: {"text": "old answer", "end": end})
        return collect.report_text("%5", True, 0.3, A)

    def waits(self):
        return [c for c in self.calls if c[0][0] == "wait-for"]


@pytest.fixture
def fk(monkeypatch):
    return Fake(monkeypatch)


SCREEN_TAIL = "".join(f"line {i}\n" for i in range(10, 30))


def test_exit_0_prints_the_report(fk):
    assert fk.run([snap("waiting")], "%5") == (0, "all done\n", "")


def test_without_wait_no_waiting_even_while_working(fk):
    assert fk.run([snap("working")], "%5")[0] == 0
    assert not fk.waits()


def test_without_wait_a_working_member_gives_the_previous_rounds_answer(fk, tmp_path):
    prevlog = str(tmp_path / "prev.jsonl")
    with open(prevlog, "w") as pf:
        pf.writelines(
            json.dumps({"type": r_[0], "timestamp": "2026-11-07T10:00:00Z", "message": {"content": r_[1]}}) + "\n"
            for r_ in [
                ("user", "q1"),
                ("assistant", [{"type": "text", "text": "answer one"}]),
                ("user", "q2"),
                ("assistant", [{"type": "tool_use", "id": "x", "name": "Bash", "input": {"command": "ls"}}]),
            ]
        )
    fk.rounds([snap("working", transcript=prevlog)])
    fk.tmux()
    assert collect.report_text("%5") == (0, "answer one\n", "")


def test_a_name_that_is_not_a_pane_id_gives_2_without_tmux(fk):
    assert fk.run([snap("waiting")], "5")[0] == 2
    assert not fk.calls


def test_tmux_failing_on_the_pane_gives_2_with_its_error(fk):
    rc, out, err = fk.run([snap("waiting")], "%5", pane_rc=1)
    assert rc == 2
    assert out == ""
    assert "can't find pane" in err


@pytest.mark.parametrize("other", GONE_OUT)
def test_pane_that_does_not_exist_gives_2(fk, other):
    rc, out, err = fk.run([snap("waiting")], "%5", pane_out=other)
    assert (rc, out, err) == (2, "", "no such pane: %5\n")


def test_pane_that_is_no_known_agent_gives_4(fk):
    rc, out, err = fk.run([{"towns": []}], "%5")
    assert rc == 4
    assert out == ""
    assert "%5" in err


def test_wait_pane_disappearing_while_waiting_gives_2_not_4(monkeypatch):
    gone = [0]

    def gone_after_wait(args, timeout=None):
        if args[0] == "display-message":
            gone[0] += 1
            return (0, "%5\n", "") if gone[0] == 1 else (0, GONE_OUT[0], "")
        return None, "", ""

    snaps2 = [snap("working"), {"towns": []}]
    monkeypatch.setattr(collect, "get_snapshot", lambda: snaps2.pop(0))
    monkeypatch.setattr(collect, "tmux_run", gone_after_wait)
    monkeypatch.setattr(collect, "report_for", lambda a: {"text": "all done"})
    rc, out, err = collect.report_text("%5", True, 30)
    assert (rc, out, err) == (2, "", "no such pane: %5\n")


def test_round_handed_out_is_that_of_the_member_data_the_report_came_from(fk):
    rd = {}
    seq_r = [
        {"towns": [{"agents": [dict(agent("idle"), round=3)]}]},
        {"towns": [{"agents": [dict(agent("idle"), round=4)]}]},
    ]
    fk.run(seq_r, "%5", read=rd)
    assert rd == {"round": 3}


def test_non_finite_timeout_gives_2(fk):
    assert fk.run([snap("waiting")], "%5", True, float("nan"))[0] == 2
    assert not fk.calls


def test_wait_reads_the_snapshot_again_after_each_2_s_wait_for(fk):
    rc, out, _ = fk.run([snap("working"), snap("working"), snap("done")], "%5", True, 30)
    assert rc == 0
    assert out == "all done\n"
    assert len(fk.snaps) == 3
    assert [c[0] for c in fk.waits()] == [("wait-for", "party-5")] * 2
    assert [c[1] for c in fk.waits()] == [2.0, 2.0]


def test_wait_timeout_expires_with_3_and_caps_the_last_wait_for(fk):
    t0 = time.monotonic()
    rc, out, _ = fk.run([snap("working")], "%5", True, 0.3)
    assert rc == 3
    assert out == ""
    assert time.monotonic() - t0 < 1
    assert 0 < fk.waits()[-1][1] <= 0.3
    assert len(fk.snaps) >= 2


def test_wait_keeps_waiting_while_subagents_run_idle_with_summons(fk):
    rc, _, _ = fk.run([snap("idle", [{}]), snap("idle", [{}]), snap("idle")], "%5", True, 30)
    assert rc == 0
    assert len(fk.snaps) == 3
    assert len(fk.waits()) == 2


@pytest.fixture
def finished_subagent(tmp_path, monkeypatch):
    """A main transcript whose report ends at 100 and a finished subagent log; returns (transcript, subagent log)."""
    tx = str(tmp_path / "main.jsonl")
    sub = tmp_path / "main" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-x.meta.json").write_text('{"finished": true}')
    (sub / "agent-x.jsonl").write_text("")
    monkeypatch.setattr(
        claude_log, "claude_report", lambda t, sidechain=False: {"text": "mid", "start": None, "end": 100}
    )
    return tx, str(sub / "agent-x.jsonl")


def test_wait_keeps_waiting_while_a_finished_subagent_log_is_newer_than_the_main_report(fk, finished_subagent):
    tx, log = finished_subagent
    os.utime(log, (200, 200))
    fk.run([snap("idle", transcript=tx), snap("idle", transcript=tx)], "%5", True, 0.3)
    assert len(fk.waits()) > 0


def test_wait_returns_when_the_finished_subagent_is_older_than_the_main_report(fk, finished_subagent):
    tx, log = finished_subagent
    os.utime(log, (50, 50))
    assert fk.run([snap("idle", transcript=tx)], "%5", True, 30)[0] == 0
    assert not fk.waits()


def test_after_waits_while_the_snapshot_is_older_than_epoch_plus_2_s(fk):
    rc, _, _ = fk.run_after(A + 1, A + 5)
    assert rc == 3
    assert fk.waits()


def test_after_waits_while_the_report_ends_before_epoch(fk):
    rc, _, _ = fk.run_after(A + 3, A - 5)
    assert rc == 3
    assert fk.waits()


def test_after_waits_while_there_is_no_report_yet(fk):
    rc, _, _ = fk.run_after(A + 3, False)
    assert rc == 3
    assert fk.waits()


def test_after_returns_once_the_report_ends_after_epoch_and_the_snapshot_is_fresh(fk):
    assert fk.run_after(A + 3, A + 2) == (0, "answer\n", "")
    assert not fk.waits()


def test_after_agy_and_grok_reports_carry_no_time_only_the_snapshot_age_counts(fk):
    assert fk.run_after(A + 3, None, "agy") == (0, "answer\n", "")
    assert not fk.waits()


def test_after_agy_with_a_stale_snapshot_waits(fk):
    assert fk.run_after(A + 1, None, "agy")[0] == 3


def test_after_waiting_member_with_no_newer_report_gives_7_and_the_screen_tail(fk):
    rc, out, err = fk.run_waiting(A + 3, A - 5)
    assert rc == 7
    assert out == SCREEN_TAIL
    assert "%5 is waiting for input" in err
    assert not fk.waits()
    assert (("capture-pane", "-p", "-t", "%5"), None) in fk.calls


def test_after_waiting_member_in_a_stale_snapshot_is_not_reported_as_waiting_yet(fk):
    assert fk.run_waiting(A + 1, A - 5)[0] == 3
    assert fk.waits()


def test_after_waiting_member_with_a_newer_report_gives_0(fk):
    assert fk.run_waiting(A + 3, A + 2) == (0, "old answer\n", "")
    assert not fk.waits()


def test_after_waiting_agy_in_a_fresh_snapshot_gives_7_with_the_screen_tail(fk):
    rc, out, err = fk.run_waiting(A + 3, False, "agy")
    assert rc == 7
    assert out == SCREEN_TAIL
    assert "waiting for input" in err
    assert not fk.waits()


def test_wait_member_at_the_usage_limit_gives_8_and_the_limit_message_even_while_working(fk):
    limited = snap("working", limit={"text": "limit reached", "end": A + 1})
    assert fk.run([limited], "%5", True, 0.3) == (8, "limit reached\n", "%5 hit a usage limit\n")
    assert fk.run([limited], "%5", True, 0.3, after=A) == (8, "limit reached\n", "%5 hit a usage limit\n")
    assert not fk.waits()


def test_after_ignores_a_usage_limit_hit_before_epoch(fk):
    old = {"t": A + 3, **snap("waiting", limit={"text": "limit reached", "end": A - 5})}
    fk.mp.setattr(collect, "report_for", lambda a: {"text": "answer", "end": A + 2})
    fk.rounds([old])
    fk.tmux()
    assert collect.report_text("%5", True, 0.3, A) == (0, "answer\n", "")


def test_without_wait_a_usage_limit_does_not_give_8(fk):
    assert fk.run([snap("waiting", limit={"text": "limit reached", "end": A + 1})], "%5")[0] == 0


def test_after_without_wait_gives_2(fk):
    assert fk.run([snap("waiting")], "%5", False, 30, after=A)[0] == 2


def fake_ask(monkeypatch, pane):
    """party.ask against a waiting pane with tmux and subprocess.run recorded."""
    calls = []

    def tmux_run(args, timeout=None):
        calls.append(("tmux", tuple(args)))
        return (0, f"{pane}{FS}/w{FS}1700000000\n", "") if args[0] == "display-message" else (0, "", "")

    monkeypatch.setattr(party, "get_snapshot", lambda: {"towns": [{"agents": [{**agent("waiting"), "pane": pane}]}]})
    monkeypatch.setattr(party, "tmux_run", tmux_run)
    monkeypatch.setattr(collect, "tmux_run", tmux_run)
    monkeypatch.setattr(
        party.subprocess,
        "run",
        lambda cmd, **kw: calls.append((tuple(cmd), kw.get("input"))) or subprocess.CompletedProcess(cmd, 0, "", ""),
    )
    return calls


@pytest.fixture
def ask_calls(monkeypatch):
    return fake_ask(monkeypatch, "%5")


def sent_steps(pane, text):
    buf = f"party-ask-{pane[1:]}"
    return [
        (("tmux", "load-buffer", "-b", buf, "-"), text),
        ("tmux", ("paste-buffer", "-p", "-d", "-b", buf, "-t", pane)),
        ("tmux", ("send-keys", "-t", pane, "Enter")),
    ]


def test_ask_one_line_is_pasted_then_entered_and_stdout_is_the_send_time(ask_calls):
    t0 = time.time()
    rc, out, err = party.ask("%5", "hello")
    assert rc == 0
    assert t0 <= float(out) <= time.time()
    assert err == ""
    assert ask_calls[1:] == sent_steps("%5", "hello")


def test_ask_text_starting_with_dash_goes_in_on_stdin(ask_calls):
    party.ask("%5", "-Rxyz")
    assert ask_calls[1] == (("tmux", "load-buffer", "-b", "party-ask-5", "-"), "-Rxyz")


def test_ask_several_lines_are_pasted_then_entered(ask_calls):
    rc, _, _ = party.ask("%5", "a\nb")
    assert rc == 0
    assert ask_calls[1:] == sent_steps("%5", "a\nb")


def test_ask_each_target_pane_gets_its_own_tmux_buffer(monkeypatch):
    ask_calls = fake_ask(monkeypatch, "%12")
    party.ask("%12", "hi")
    assert ask_calls[1] == (("tmux", "load-buffer", "-b", "party-ask-12", "-"), "hi")
    assert ask_calls[2] == ("tmux", ("paste-buffer", "-p", "-d", "-b", "party-ask-12", "-t", "%12"))


def test_ask_a_name_that_is_not_a_pane_id_gives_2():
    assert party.ask("5", "x")[0] == 2


def test_ask_pane_that_is_no_known_agent_gives_4(monkeypatch):
    monkeypatch.setattr(party, "get_snapshot", lambda: {"towns": []})
    monkeypatch.setattr(party, "tmux_run", lambda args, timeout=None: (0, f"%5{FS}/w{FS}1700000000\n", ""))
    monkeypatch.setattr(collect, "tmux_run", lambda args, timeout=None: (0, f"%5{FS}/w{FS}1700000000\n", ""))
    assert party.ask("%5", "x")[0] == 4


@pytest.fixture
def gone_calls(monkeypatch):
    """tmux_run that answers every call with what display-message prints for a missing pane."""
    calls = []

    def use(other):
        def tmux_run(args, timeout=None):
            calls.append(tuple(args))
            return 0, other, ""

        monkeypatch.setattr(party, "tmux_run", tmux_run)
        monkeypatch.setattr(collect, "tmux_run", tmux_run)

    return calls, use


@pytest.mark.parametrize("other", GONE_OUT)
def test_ask_pane_that_does_not_exist_gives_2(gone_calls, other):
    _, use = gone_calls
    use(other)
    assert party.ask("%5", "x") == (2, "", "no such pane: %5\n")


def test_ask_sends_nothing_to_a_pane_that_does_not_exist(gone_calls):
    calls, use = gone_calls
    for other in GONE_OUT:
        use(other)
        party.ask("%5", "x")
    assert all(c[0] == "display-message" for c in calls)


def test_tmux_run_timeout_ends_the_tmux_child_and_returns_rc_none(tmp_path, monkeypatch):
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "tmux").write_text(f'#!/bin/sh\necho $$ >"{fake}/pid"\nexec sleep 30\n')
    (fake / "tmux").chmod(0o755)
    monkeypatch.setenv("PATH", str(fake) + os.pathsep + os.environ["PATH"])
    t0 = time.monotonic()
    rc = common.tmux_run(["wait-for", "x"], timeout=0.3)
    pid = int((fake / "pid").read_text())
    try:
        os.kill(pid, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    assert rc == (None, "", "")
    assert time.monotonic() - t0 < 5
    assert not alive


@pytest.fixture
def collector(tmp_path, monkeypatch):
    """Run the real get_snapshot on a collection of agents; returns the tmux calls it made."""
    sent = []
    monkeypatch.setattr(collect, "PARTY_DIR", str(tmp_path / "party"))
    monkeypatch.setattr(collect, "tmux", lambda *a: sent.append(a) or "")

    def run(*agents):
        sp = os.path.join(collect.PARTY_DIR, "snapshot.json")
        if os.path.exists(sp):
            os.remove(sp)
        monkeypatch.setattr(
            collect,
            "collect",
            lambda *a: {
                "t": time.time(),
                "towns": [{"agents": list(agents)}],
                "panes": {a["pane"]: {"window": "@1", "sidebar": False, "visible": True} for a in agents},
            },
        )
        sent.clear()
        collect.get_snapshot()
        return list(sent)

    return run


def test_collector_signals_wait_for_only_when_a_status_changed(collector):
    def sig(status):
        return [a for a in collector({"pane": "%5", "status": status, "focus": True}) if a[0] == "wait-for"]

    r1, r2, r3 = sig("working"), sig("waiting"), sig("waiting")
    assert r1 == []
    assert r2 == [("wait-for", "-S", "party-5")]
    assert r3 == []


def test_collector_party_reports_ignores_a_done_crew_and_is_set_only_on_change(collector):
    def reports(*agents):
        return [a[3] for a in collector(*agents) if a[:3] == ("set-option", "-g", "@party_reports")]

    lead_p = {"pane": "%1", "status": "idle", "focus": True}
    crew_w = {"pane": "%2", "status": "working", "lead": "%1"}
    crew_d = {**crew_w, "status": "done"}
    s1, s2 = reports(lead_p, crew_w), reports(lead_p, crew_d)
    s3, s4 = reports(dict(crew_d, lead="")), reports(dict(crew_d, lead=""))
    s5, s6 = reports(lead_p, crew_d), reports(lead_p, crew_d)
    assert [s1, s2, s3, s4, s5, s6] == [["0"], [], ["1"], [], ["0"], []]
