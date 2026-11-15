"""Crew sub-commands: --summon, --dismiss, the crew round files, and crew grouping under leads."""

import json
import os
import subprocess
import sys
import time

import pytest
from screen import strip

import party
from party_hud import collect, render, sidebars

FS = collect.FIELD_SEP
READY = f"claude{FS}123\n"
OPENS = ("split-window", "new-window", "new-session")


class FakeTmux:
    """tmux for summon: the caller is %1, a new pane is %9; shows are the screens the new pane reports in turn."""

    def __init__(self):
        self.calls = []
        self.shows = [READY]
        self.has_crew = False
        self.crew_lead = ""
        self.lead_alive = True
        self.pane_alive = True
        self.listed = True

    def run(self, args, timeout=None):
        self.calls.append(tuple(args))
        if args[0] == "display-message" and args[-1] == FS.join(["#{pane_id}", "#{@party_lead}"]):
            return 0, args[3] + FS + self.crew_lead + "\n", ""
        # tmux exits 0 for a pane that does not exist and prints no pane id
        if args[0] == "display-message" and args[-1] == "#{pane_id}":
            return 0, (args[3] if self.lead_alive else "") + "\n", ""
        if args[0] in OPENS:
            return 0, "%9\n", ""
        if args[0] == "has-session":
            return (0 if self.has_crew else 1), "", ""
        if args[0] == "display-message" and args[-1] == FS.join(["#{window_width}", "#{window_height}"]):
            return 0, f"132{FS}41\n", ""
        if args[0] == "display-message":
            show = self.shows.pop(0) if len(self.shows) > 1 else self.shows[0]
            return 0, (args[3] + FS if self.pane_alive else "") + show, ""
        return 0, "", ""

    def opened(self):
        return next(c for c in self.calls if c[0] in OPENS)

    def blocked(self):
        return any(c[0] in (*OPENS, "set-option") for c in self.calls)


@pytest.fixture
def tm(monkeypatch):
    fake = FakeTmux()
    monkeypatch.setattr(sidebars, "tmux_run", fake.run)
    monkeypatch.setattr(collect, "tmux_run", fake.run)
    monkeypatch.setattr(
        sidebars, "tmux", lambda *a: fake.calls.append(a) or ("screen" if a[0] == "capture-pane" else "")
    )
    monkeypatch.setattr(sidebars.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        sidebars, "get_snapshot", lambda: {"towns": [{"agents": [{"pane": "%9"}] if fake.listed else []}]}
    )
    monkeypatch.setenv("TMUX_PANE", "%1")
    return fake


@pytest.fixture
def clock(monkeypatch):
    """time.monotonic that moves only when summon sleeps."""
    t = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: t[0])
    monkeypatch.setattr(sidebars.time, "sleep", lambda s: t.__setitem__(0, t[0] + s))
    return t


def test_summon_ready_prints_the_pane_id(tm, tmp_path):
    assert sidebars.summon("claude", str(tmp_path), False, 5) == (0, "%9\n", "")


def test_summon_default_creates_the_crew_session_at_the_callers_window_size(tm, tmp_path):
    sidebars.summon("claude", str(tmp_path), False, 5)
    new = ("new-session", "-d", "-s", "crew-1", "-x", "132", "-y", "41", "-P", "-F", "#{pane_id}", "-c")
    assert (*new, str(tmp_path), "claude") in tm.calls


def test_summon_sets_party_lead_on_the_new_pane(tm, tmp_path):
    sidebars.summon("claude", str(tmp_path), False, 5)
    assert ("set-option", "-p", "-t", "%9", "@party_lead", "%1") in tm.calls


def test_summon_default_with_the_crew_session_there_opens_a_window_in_it(tm, tmp_path):
    tm.has_crew = True
    sidebars.summon("claude", str(tmp_path), False, 5)
    assert ("new-window", "-d", "-t", "crew-1:", "-P", "-F", "#{pane_id}", "-c", str(tmp_path), "claude") in tm.calls
    assert not any(c[0] == "new-session" for c in tm.calls)


def test_summon_here_splits_the_callers_window(tm, tmp_path):
    sidebars.summon("claude", str(tmp_path), False, 5, here=True)
    assert tm.opened() == ("split-window", "-t", "%1", "-P", "-F", "#{pane_id}", "-c", str(tmp_path), "claude")


def test_summon_window_and_here_together_is_rc_2_without_tmux(tm, tmp_path):
    assert sidebars.summon("claude", str(tmp_path), True, 5, here=True)[0] == 2
    assert not tm.calls


def test_summon_window_opens_a_new_window_and_codex_skips_its_update_prompt(tm, tmp_path):
    sidebars.summon("codex", str(tmp_path), True, 5)
    cmd = "codex -c check_for_update_on_startup=false"
    assert tm.opened() == ("new-window", "-P", "-F", "#{pane_id}", "-c", str(tmp_path), cmd)


def test_summon_doubles_every_hash_in_cwd(tm, tmp_path):
    hashed = tmp_path / "a#(b)#{c}"
    hashed.mkdir()
    sidebars.summon("codex", str(hashed), True, 5)
    opened = tm.opened()
    assert opened[opened.index("-c") + 1] == str(tmp_path / "a##(b)##{c}")


def test_summon_read_only_codex_runs_with_a_read_only_sandbox(tm, tmp_path):
    sidebars.summon("codex", str(tmp_path), False, 5, True, True)
    cmd = "codex -c check_for_update_on_startup=false -s read-only"
    assert tm.opened() == ("split-window", "-t", "%1", "-P", "-F", "#{pane_id}", "-c", str(tmp_path), cmd)


def test_summon_read_only_default_crew_session_gets_the_read_only_command(tm, tmp_path):
    sidebars.summon("claude", str(tmp_path), False, 5, True)
    assert any(c[0] == "new-session" and c[-1] == "claude --permission-mode plan" for c in tm.calls)


@pytest.mark.parametrize(
    ("kind", "cmd"),
    [("claude", "claude --permission-mode plan"), ("agy", "agy --mode plan"), ("grok", "grok --permission-mode plan")],
)
def test_summon_read_only_starts_each_agent_in_its_plan_mode(tm, tmp_path, kind, cmd):
    rc, _, _ = sidebars.summon(kind, str(tmp_path), False, 5, True, True)
    assert rc == 0
    assert tm.opened()[-1] == cmd


@pytest.mark.parametrize(
    "kw", [{}, {"window": True}, {"here": True}, {"read_only": True}], ids=["default", "window", "here", "read-only"]
)
def test_summon_by_crew_whose_lead_pane_exists_is_rc_6_and_opens_nothing(tm, tmp_path, kw):
    tm.crew_lead = "%0"
    rc, out, err = sidebars.summon(
        "claude", str(tmp_path), kw.get("window", False), 5, kw.get("read_only", False), kw.get("here", False)
    )
    assert rc == 6
    assert out == ""
    assert "report to your lead" in err
    assert not tm.blocked()


def test_summon_by_crew_whose_lead_pane_is_gone_summons_as_usual(tm, tmp_path):
    tm.crew_lead, tm.lead_alive = "%0", False
    rc, _, _ = sidebars.summon("claude", str(tmp_path), False, 5)
    assert rc == 0
    assert any(c[0] == "new-session" for c in tm.calls)


def test_summon_of_an_unknown_agent_is_rc_2_without_tmux(tm, tmp_path):
    assert sidebars.summon("vim", str(tmp_path), False, 5)[0] == 2
    assert not tm.calls


def test_summon_outside_tmux_is_rc_2(tm, tmp_path, monkeypatch):
    monkeypatch.delenv("TMUX_PANE")
    assert sidebars.summon("claude", str(tmp_path), False, 5)[0] == 2
    assert not tm.calls


def test_summon_timeout_is_rc_3_with_the_pane_id_on_stderr(tm, tmp_path, clock):
    tm.shows = [f"bash{FS}1\n"]
    rc, out, err = sidebars.summon("claude", str(tmp_path), False, 3)
    assert rc == 3
    assert out == ""
    assert "%9" in err


def test_summon_is_not_ready_until_the_snapshot_lists_the_pane(tm, tmp_path, clock):
    tm.listed = False
    rc, _, err = sidebars.summon("claude", str(tmp_path), False, 3)
    assert rc == 3
    assert "%9" in err


def test_summon_of_a_pane_that_closes_before_it_is_ready_is_rc_2_at_once(tm, tmp_path, clock):
    tm.shows, tm.pane_alive = [f"{FS}\n"], False
    assert sidebars.summon("claude", str(tmp_path), False, 3) == (2, "", "no such pane: %9\n")


def agent(pane, kind="claude", window="@1"):
    return {"pane": pane, "kind": kind, "window": window, "status": "idle"}


def mk_towns(*ts):
    return {n: {"name": n, "agents": list(ag)} for n, ag in ts}


def test_crew_members_join_the_leads_squad_under_the_lead():
    towns = mk_towns(("main", [agent("%1"), agent("%7")]), ("crew-1", [agent("%2", "codex"), agent("%3", "grok")]))
    collect.adopt_crews(towns, {"%1": ("", False, "@1"), "%2": ("%1", False, "@2"), "%3": ("%1", False, "@2")})
    assert list(towns) == ["main"]
    got = collect.group_under_leads(towns["main"]["agents"], {"%2": ("%1", False, "@2"), "%3": ("%1", False, "@2")})
    assert [x["pane"] for x in got] == ["%1", "%2", "%3", "%7"]


def test_crew_squad_whose_lead_is_gone_stays_as_it_is():
    towns = mk_towns(("main", [agent("%7")]), ("crew-1", [agent("%2", "codex")]))
    collect.adopt_crews(towns, {"%2": ("%1", False, "@2")})
    assert list(towns) == ["main", "crew-1"]
    assert [x["pane"] for x in towns["crew-1"]["agents"]] == ["%2"]


def test_crew_inside_a_crew_keeps_every_agent_in_one_squad_whatever_the_order():
    nest = {"%5": ("%0", False, "@5"), "%6": ("%5", False, "@6")}
    seen = []
    for order in (("crew-0", "crew-5", "main"), ("crew-5", "crew-0", "main")):
        pool = {"main": [agent("%0")], "crew-0": [agent("%5")], "crew-5": [agent("%6")]}
        towns = mk_towns(*((n, pool[n]) for n in order))
        collect.adopt_crews(towns, nest)
        seen.append({n: sorted(x["pane"] for x in t["agents"]) for n, t in towns.items()})
    assert seen[0] == seen[1]
    assert sorted(p for v in seen[0].values() for p in v) == ["%0", "%5", "%6"]


def test_party_lead_lists_the_member_under_its_lead():
    a, b, c = agent("%1"), agent("%2", "codex"), agent("%3", "claude", "@2")
    got = collect.group_under_leads(
        [a, c, b], {"%1": ("", False, "@1"), "%2": ("%1", False, "@1"), "%3": ("", False, "@2")}
    )
    assert [x["pane"] for x in got] == ["%1", "%2", "%3"]
    assert b.get("lead") == "%1"
    assert "lead" not in c


def test_xv_member_gets_the_only_claude_of_the_window_as_lead():
    a, x = agent("%1"), agent("%4", "codex")
    got = collect.group_under_leads([x, a], {"%1": ("", False, "@1"), "%4": ("", True, "@1")})
    assert [m["pane"] for m in got] == ["%1", "%4"]
    assert x.get("lead") == "%1"


def test_xv_member_with_two_claudes_in_the_window_is_an_ordinary_member():
    a, a2, x = agent("%1"), agent("%2"), agent("%4", "codex")
    got = collect.group_under_leads(
        [a, a2, x], {"%1": ("", False, "@1"), "%2": ("", False, "@1"), "%4": ("", True, "@1")}
    )
    assert [m["pane"] for m in got] == ["%1", "%2", "%4"]
    assert "lead" not in x


def test_group_under_leads_without_lead_or_xv_keeps_the_order():
    a, b, c = agent("%1"), agent("%2", "codex"), agent("%3", "claude", "@2")
    got = collect.group_under_leads(
        [c, b, a], {"%1": ("", False, "@1"), "%2": ("", False, "@1"), "%3": ("", False, "@2")}
    )
    assert [m["pane"] for m in got] == ["%3", "%2", "%1"]
    assert not any("lead" in m for m in got)


BOSS = {
    **agent("%1"),
    "name": "boss",
    "hp": 50,
    "hp_max": 100,
    "hp_left": 50,
    "sp": None,
    "fresh": False,
    "model": "",
    "summons": [],
    "cls": 0,
    "focus": False,
    "id": "i1",
}


@pytest.mark.parametrize("art", [False, True])
@pytest.mark.parametrize("lead", ["", "%1"])
def test_card_lines_are_exactly_40_columns_with_and_without_a_lead(art, lead):
    rows = render.card({**BOSS, "lead": lead}, 40, False, art)
    assert {render.cw(strip(r)) for r in rows} == {40}


def test_crew_done_card_still_says_done():
    crew_done = {**BOSS, "pane": "%2", "status": "done", "lead": "%1"}
    assert "✓ done" in strip("\n".join(render.card(crew_done, 40, False, False)))


class FakeDismiss:
    """The caller is %1; the member %9 is a known agent whose @party_lead is lead."""

    def __init__(self):
        self.calls = []
        self.lead = "%1"
        self.exists = True
        self.member = {"pane": "%9", "kind": "codex", "status": "idle", "summons": [], "round": 3}

    def run(self, args, timeout=None):
        self.calls.append(tuple(args))
        # tmux exits 0 for a pane that does not exist and prints no pane id
        if args[0] == "display-message":
            return 0, (args[3] if self.exists else "") + FS + self.lead + "\n", ""
        return 0, "", ""

    def dismiss(self, pane="%9", **kw):
        self.calls.clear()
        self.member.update({"status": "idle", "summons": [], **kw})
        return sidebars.dismiss(pane)

    def killed(self):
        return any(c[0] == "kill-pane" for c in self.calls)


@pytest.fixture
def dm(monkeypatch, tmp_path):
    fake = FakeDismiss()
    monkeypatch.setattr(collect, "PARTY_DIR", str(tmp_path))
    monkeypatch.setattr(sidebars, "tmux_run", fake.run)
    monkeypatch.setattr(collect, "tmux_run", fake.run)
    monkeypatch.setattr(sidebars, "get_snapshot", lambda: {"towns": [{"agents": [fake.member]}]})
    monkeypatch.setenv("TMUX_PANE", "%1")
    return fake


def write_seen(seen):
    with open(os.path.join(collect.PARTY_DIR, "seen.json"), "w") as f:
        json.dump(seen, f)


def test_dismiss_of_an_idle_member_you_summoned_kills_the_pane(dm):
    rc, _, _ = dm.dismiss()
    assert rc == 0
    assert ("kill-pane", "-t", "%9") in dm.calls


@pytest.mark.parametrize(
    ("lead", "kw", "msg"),
    [
        ("%2", {}, "not summoned by you"),
        ("", {}, "not summoned by you"),
        ("%1", {"status": "waiting"}, "not dismissed"),
        ("%2", {"status": "waiting"}, "not summoned by you"),
        ("%1", {"status": "waiting", "summons": [{"type": "executor"}]}, "still working"),
        ("%1", {"status": "working"}, "still working"),
        ("%1", {"summons": [{"type": "executor"}]}, "still working"),
        ("%1", {"status": "done"}, "report not read yet; run --report-text first"),
    ],
    ids=[
        "lead-is-another-pane",
        "no-lead",
        "waiting",
        "waiting-and-another-lead",
        "waiting-with-subagents",
        "working",
        "running-subagents",
        "done-report-not-read",
    ],
)
def test_dismiss_refuses_with_rc_6_and_no_kill_pane(dm, lead, kw, msg):
    dm.lead = lead
    rc, _, err = dm.dismiss(**kw)
    assert rc == 6
    assert msg in err
    assert not dm.killed()


def test_dismiss_of_a_done_member_whose_seen_round_is_older_is_rc_6(dm):
    write_seen({"%9": 2})
    rc, _, err = dm.dismiss(status="done")
    assert rc == 6
    assert "report not read yet" in err
    assert not dm.killed()


def test_dismiss_of_a_done_member_whose_round_was_read_kills_the_pane_once(dm):
    write_seen({"%9": 3})
    rc, _, _ = dm.dismiss(status="done")
    assert rc == 0
    assert dm.calls.count(("kill-pane", "-t", "%9")) == 1


def test_dismiss_of_a_pane_that_is_not_an_agent_is_rc_4(dm):
    rc, _, _ = dm.dismiss("%8")
    assert rc == 4
    assert not dm.killed()


def test_dismiss_of_a_pane_that_does_not_exist_is_rc_2(dm):
    dm.exists = False
    rc, _, err = dm.dismiss()
    assert (rc, err) == (2, "no such pane: %9\n")
    assert not dm.killed()


def test_dismiss_of_a_bad_pane_id_is_rc_2_without_tmux(dm):
    rc, _, _ = dm.dismiss("9")
    assert rc == 2
    assert not dm.calls


def test_dismiss_outside_tmux_is_rc_2_without_tmux(dm, monkeypatch):
    monkeypatch.delenv("TMUX_PANE")
    rc, _, _ = dm.dismiss()
    assert rc == 2
    assert not dm.calls


@pytest.fixture
def crew(monkeypatch, tmp_path):
    """The crew root under a fresh XDG_STATE_HOME; %5 is a codex member in /work/dir at round 4."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(sidebars, "PARTY_DIR", str(tmp_path / "run"))
    monkeypatch.setattr(collect, "PARTY_DIR", str(tmp_path / "run"))
    monkeypatch.setattr(
        party, "get_snapshot", lambda: {"towns": [{"agents": [{"pane": "%5", "kind": "codex", "round": 4}]}]}
    )
    monkeypatch.setattr(party, "tmux_run", lambda args, timeout=None: (0, "%5" + FS + "/work/dir\n", ""))
    monkeypatch.setattr(collect, "tmux_run", lambda args, timeout=None: (0, "%5" + FS + "/work/dir\n", ""))
    monkeypatch.setattr(party.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", ""))
    return tmp_path / "state" / "party-hud" / "crew"


def read(root, *p):
    return (root.joinpath(*p)).read_text(encoding="utf-8")


def meta(root, *p):
    return json.loads(read(root, *p, "meta.json"))


def test_first_ask_on_a_pane_not_summoned_creates_a_session_dir(crew):
    rc, _, _ = party.ask("%5", "first?")
    sess = os.listdir(crew)
    assert rc == 0
    assert len(sess) == 1
    assert sess[0].endswith("Z-5")


def test_ask_writes_the_question_and_meta_of_round_001(crew):
    party.ask("%5", "first?")
    (sess,) = os.listdir(crew)
    m = meta(crew, sess, "round-001")
    assert read(crew, sess, "round-001", "question.md") == "first?"
    assert (m["pane"], m["agent"], m["cwd"]) == ("%5", "codex", "/work/dir")
    assert "asked_at" in m


def test_report_text_save_succeeds(crew):
    party.ask("%5", "first?")
    assert sidebars.crew_replied("%5", "answer\n", 0) == ""


def test_report_text_writes_the_reply_into_the_latest_round(crew):
    party.ask("%5", "first?")
    sidebars.crew_replied("%5", "answer\n", 0)
    (sess,) = os.listdir(crew)
    m = meta(crew, sess, "round-001")
    assert read(crew, sess, "round-001", "reply.md") == "answer\n"
    assert (m["rc"], m["agent"]) == (0, "codex")
    assert "replied_at" in m


def test_report_text_rc_7_is_saved_to_the_reply_and_meta(crew):
    party.ask("%5", "first?")
    sidebars.crew_replied("%5", "answer\n", 0)
    assert sidebars.crew_replied("%5", "screen\n", 7) == ""
    (sess,) = os.listdir(crew)
    assert meta(crew, sess, "round-001")["rc"] == 7
    assert read(crew, sess, "round-001", "reply.md") == "screen\n"


@pytest.fixture
def run_main(crew, monkeypatch, capsys):
    """party.py --report-text %5 with report_text returning result (and setting the read round to rnd)
    and crew_replied returning save_err: ((exit code, stdout, stderr), what crew_replied got)."""

    def run(result, save_err, rnd=None):
        saved = []
        monkeypatch.setattr(
            party, "report_text", lambda *a: result if rnd is None else a[-1].update(round=rnd) or result
        )
        monkeypatch.setattr(party, "crew_replied", lambda pane, out, rc: saved.append((pane, out, rc)) or save_err)
        monkeypatch.setattr(sys, "argv", ["party.py", "--report-text", "%5"])
        code = None
        try:
            party.main()
        except SystemExit as e:
            code = e.code
        got = capsys.readouterr()
        return (code, got.out, got.err), saved

    return run


def seen_path():
    return os.path.join(sidebars.PARTY_DIR, "seen.json")


def test_report_text_rc_7_prints_the_screen_and_saves_it_with_rc_7(run_main):
    got, saved = run_main((7, "screen\n", "%5 is waiting for input\n"), "")
    assert got == (7, "screen\n", "%5 is waiting for input\n")
    assert saved == [("%5", "screen\n", 7)]


def test_report_text_rc_7_with_a_failed_save_stays_7_and_reports_the_error(run_main):
    got, _ = run_main((7, "screen\n", "%5 is waiting for input\n"), "save failed\n")
    assert got == (7, "screen\n", "%5 is waiting for input\nsave failed\n")


def test_report_text_rc_0_with_a_failed_save_is_rc_5(run_main):
    got, _ = run_main((0, "answer\n", ""), "save failed\n")
    assert got == (5, "answer\n", "save failed\n")


def test_report_text_rc_3_rc_7_and_an_empty_report_record_no_round(run_main):
    run_main((3, "", "timed out waiting for %5\n"), "")
    run_main((7, "screen\n", "%5 is waiting for input\n"), "")
    run_main((0, "", "no report for %5\n"), "")
    assert not os.path.exists(seen_path())


def test_report_text_of_a_report_without_a_round_records_nothing(run_main):
    run_main((0, "answer\n", ""), "")
    assert not os.path.exists(seen_path())


def test_report_text_records_the_round_of_the_report_it_read_not_the_snapshots(run_main):
    run_main((0, "answer\n", ""), "", 3)
    with open(seen_path()) as f:
        assert json.load(f) == {"%5": 3}


def test_report_text_rc_5_from_a_failed_crew_save_still_records_the_round(run_main):
    got, _ = run_main((0, "answer\n", ""), "save failed\n", 3)
    assert got == (5, "answer\n", "save failed\n")
    with open(seen_path()) as f:
        assert json.load(f) == {"%5": 3}


class Broken:
    def write(self, s):
        raise OSError("broken pipe")

    def flush(self):
        pass


def test_report_text_whose_stdout_write_fails_records_no_round(crew, monkeypatch):
    monkeypatch.setattr(party, "report_text", lambda *a: a[-1].update(round=3) or (0, "answer\n", ""))
    monkeypatch.setattr(party, "crew_replied", lambda pane, out, rc: "")
    monkeypatch.setattr(sys, "argv", ["party.py", "--report-text", "%5"])
    monkeypatch.setattr(sys, "stdout", Broken())
    with pytest.raises(OSError, match="broken pipe"):
        party.main()
    assert not os.path.exists(seen_path())


def test_second_ask_makes_round_002_in_the_same_session(crew):
    party.ask("%5", "first?")
    sess = os.listdir(crew)
    party.ask("%5", "second?")
    assert read(crew, sess[0], "round-002", "question.md") == "second?"
    assert os.listdir(crew) == sess


def test_reply_with_no_round_yet_makes_a_round_holding_only_the_reply(crew):
    sidebars.crew_replied("%7", "lone\n", 0)
    (lone,) = [d for d in os.listdir(crew) if d.endswith("Z-7")]
    assert read(crew, lone, "round-001", "reply.md") == "lone\n"
    assert not (crew / lone / "round-001" / "question.md").exists()


@pytest.fixture
def summoned(crew):
    """%5 asked twice in a session from 2026-11-01, a 15-day-old session of %9 and a newer one of %8, then --summon %5."""
    party.ask("%5", "first?")
    party.ask("%5", "second?")
    (first,) = os.listdir(crew)
    os.rename(crew / first, crew / "20261101T000000Z-5")
    old, new = crew / "20200101T000000Z-9", crew / "20261101T000000Z-8"
    old.mkdir()
    new.mkdir()
    past = time.time() - 15 * 86400
    os.utime(old, (past, past))
    return sidebars.crew_summoned("%5"), old, new


def test_summon_deletes_session_dirs_older_than_14_days_and_keeps_newer_ones(crew, summoned):
    err, old, new = summoned
    assert err == ""
    assert not old.exists()
    assert new.is_dir()
    assert (crew / "20261101T000000Z-5").is_dir()


def test_summon_always_makes_a_new_session_dir_even_when_the_pane_has_one(crew, summoned):
    assert len([d for d in os.listdir(crew) if d.endswith("Z-5") and d != "20261101T000000Z-5"]) == 1


def test_ask_after_summon_writes_round_001_of_the_new_session(crew, summoned):
    party.ask("%5", "after summon")
    (fresh,) = [d for d in os.listdir(crew) if d.endswith("Z-5") and d != "20261101T000000Z-5"]
    assert read(crew, fresh, "round-001", "question.md") == "after summon"
    assert not (crew / "20261101T000000Z-5" / "round-003").exists()


def test_ask_whose_save_fails_is_rc_5_and_still_prints_the_send_time(crew, monkeypatch, tmp_path):
    blocked = tmp_path / "blocked"
    blocked.touch()
    monkeypatch.setenv("XDG_STATE_HOME", str(blocked))
    rc, out, err = party.ask("%5", "third?")
    assert rc == 5
    assert out
    assert "could not save" in err
