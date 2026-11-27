import fcntl
import json
import os
import random
import re
import sys
import threading
import time
import unicodedata

import pytest
from screen import strip

from party_hud import claude_log, codex_log, collect, common, render, sidebars

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture_text(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


@pytest.fixture(autouse=True)
def party_dir(tmp_path, monkeypatch):
    path = str(tmp_path / "party")
    monkeypatch.setattr(collect, "PARTY_DIR", path)
    monkeypatch.setattr(sidebars, "PARTY_DIR", path)
    return path


def pane(pid, cmd, **extra):
    return {
        "session_name": "New",
        "window_index": "1",
        "window_name": "w",
        "window_active": "1",
        "session_attached": "1",
        "pane_id": pid,
        "pane_active": "1",
        "pane_current_command": cmd,
        "pane_current_path": "/n",
        "@workmux_pane_status": "",
        "pane_pid": "",
        **extra,
    }


def write_fixture(tmp_path, data):
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(data))
    return str(path)


def members(snap):
    return {a["pane"]: a for t in snap["towns"] for a in t["agents"]}


@pytest.fixture
def new_squad(tmp_path):
    """A freshly started Claude, an agy and a grok with no readable context, and a codex with a known window."""
    path = write_fixture(
        tmp_path,
        {
            "panes": [pane("%20", "claude"), pane("%21", "agy"), pane("%22", "grok"), pane("%23", "codex")],
            "now": 10000,
            "sessions": {"%20": {"sid": "s20", "name": "新開", "status": "idle"}},
            "screen_changed": ["%22"],
            "codex": {"%23": [64000, 256000]},
        },
    )
    return members(collect.collect(path)), strip(render.render(collect.collect(path)["towns"], 33, "%20"))


def test_freshly_started_claude_has_full_hp_and_sp(new_squad):
    new, nl = new_squad
    assert new["%20"]["hp"] == 100
    assert new["%20"]["fresh"]
    assert re.search(r"新開.*· idle.*\n.*HP +100% +║\n.*SP +60/60m +║", nl)


def test_report_pane_is_treated_like_a_sidebar(tmp_path):
    path = write_fixture(
        tmp_path,
        {
            "panes": [pane("%30", "claude"), pane("%31", "python3", **{"@party_report": "1", "window_id": "@7"})],
            "now": 10000,
            "sessions": {"%30": {"sid": "s30", "name": "x", "status": "idle"}},
        },
    )
    rs = collect.collect(path)
    assert rs["panes"]["%31"]["sidebar"] is True
    assert rs["panes"]["%30"]["sidebar"] is False
    assert [a["pane"] for t in rs["towns"] for a in t["agents"]] == ["%30"]


def test_other_agents_with_unreadable_context_have_no_hp_or_sp(new_squad):
    new, nl = new_squad
    assert new["%21"]["hp"] is None
    assert not new["%21"]["fresh"]
    assert re.search(r"agy.*\n.*· idle.*\n.*HP +-- +│\n╰", nl)
    assert "SP --" not in nl


def test_other_agents_are_busy_while_their_screen_changes(new_squad):
    new, _ = new_squad
    assert new["%22"]["status"] == "working"
    assert new["%21"]["status"] == "idle"


@pytest.fixture
def waiting_squad(tmp_path):
    path = write_fixture(
        tmp_path,
        {
            "panes": [
                pane("%30", "claude"),
                pane("%31", "claude", **{"@workmux_pane_status": "✅"}),
                pane("%32", "claude", **{"@workmux_pane_status": "🤖"}),
            ],
            "now": 10000,
            "sessions": {
                "%30": {"sid": "s30", "name": "w", "status": "waiting"},
                "%31": {"sid": "s31", "name": "d", "status": "waiting"},
                "%32": {"sid": "s32", "name": "r", "status": "waiting"},
            },
        },
    )
    return members(collect.collect(path))


def test_claude_sessions_status_waiting_makes_a_waiting_member(waiting_squad):
    wt = waiting_squad
    assert wt["%30"]["status"] == "waiting"
    assert "!1" in strip(render.squad_summary([wt["%30"]])[0])


def test_workmux_done_icon_wins_over_sessions_status_waiting(waiting_squad):
    assert waiting_squad["%31"]["status"] == "done"


def test_sessions_status_waiting_wins_over_a_stale_workmux_working_icon(waiting_squad):
    assert waiting_squad["%32"]["status"] == "waiting"


def test_codex_pane_kind_and_name_are_both_codex(new_squad):
    new, _ = new_squad
    assert new["%23"]["kind"] == "codex"
    assert new["%23"]["name"] == "codex"


def test_codex_hp_is_the_part_of_the_window_left(new_squad):
    new, _ = new_squad
    assert new["%23"]["hp"] == 75
    assert new["%23"]["hp_left"] == 192000


def test_pane_state_file_left_by_claude_is_ignored_for_codex_and_agy(tmp_path):
    stale = {"session_id": "old", "transcript": "/t/old", "ctx_left": 59, "ctx_size": 200000, "model": "Opus 5.5"}
    path = write_fixture(
        tmp_path,
        {
            "panes": [pane("%40", "codex"), pane("%41", "agy")],
            "now": 10000,
            "codex": {"%40": [64000, 256000]},
            "party": {"%40": stale, "%41": stale},
            "cache": {"/t/old": [9990, 300, 60000]},
        },
    )
    old = members(collect.collect(path))
    assert all(old[k]["sp"] is None and old[k]["model"] == "" and old[k]["status"] != "sleep" for k in ("%40", "%41"))
    assert old["%40"]["hp"] == 75
    assert old["%41"]["hp"] is None


def test_screen_diff_counts_a_change_as_busy_until_it_settles(monkeypatch):
    screens = iter(["a", "a", "b", "b"])
    monkeypatch.setattr(collect, "tmux", lambda *args: next(screens))
    first, same = collect.screen_changed(["%9"], 100), collect.screen_changed(["%9"], 110)
    moved, later = collect.screen_changed(["%9"], 120), collect.screen_changed(["%9"], 130)
    assert first == {"%9": False}
    assert same == {"%9": False}
    assert moved == {"%9": True}
    assert later == {"%9": False}


def tmux_panes(*cmds):
    return [
        dict(
            {f: "" for f in collect.TMUX_FIELDS},
            pane_id=f"%{i}",
            pane_pid=str(i),
            pane_current_command=cmd,
            session_name="s",
            session_attached="1",
            window_active="1",
            window_id="@1",
            window_panes=str(len(cmds)),
        )
        for i, cmd in enumerate(cmds, 1)
    ]


@pytest.fixture
def statuses(monkeypatch):
    """Collect panes running cmds while every pane shows screen: {kind: status}."""
    monkeypatch.setattr(claude_log, "read_claude_sessions", dict)

    def run(cmds, screen, now=None):
        monkeypatch.setattr(collect, "read_tmux", lambda: tmux_panes(*cmds))
        monkeypatch.setattr(collect, "tmux", lambda *args: screen)
        return {a["kind"]: a["status"] for t in collect.collect(now=now)["towns"] for a in t["agents"]}

    return run


@pytest.fixture
def agy_menu():
    return fixture_text("agy-permission.txt")


def test_agy_permission_menu_on_screen_is_waiting(statuses, agy_menu):
    assert statuses(("agy", "grok"), agy_menu)["agy"] == "waiting"


def test_agy_screen_without_the_permission_menu_is_not_waiting(statuses, agy_menu):
    agy_done = agy_menu[: agy_menu.index("Command\n")]
    assert statuses(("agy", "grok"), agy_done)["agy"] == "idle"


def test_grok_pane_showing_the_agy_permission_menu_is_unaffected(statuses, agy_menu):
    assert statuses(("agy", "grok"), agy_menu)["grok"] == "idle"


def test_changing_screen_with_the_menu_text_keeps_agy_waiting(statuses, agy_menu):
    for n in (100, 101):
        busy = statuses(("agy", "grok", "codex"), agy_menu + f"tick {n}", now=n)
    assert busy == {"agy": "waiting", "grok": "working", "codex": "working"}


def rollout(folder, name, *events):
    path = os.path.join(folder, name)
    with open(path, "w") as f:
        f.writelines(json.dumps({"type": "event_msg", "payload": {"type": e}}) + "\n" for e in events)
    return path


@pytest.fixture
def rollouts(tmp_path):
    """Rollouts whose newest turn event is task_complete, task_started, or none."""
    return (
        rollout(tmp_path, "done.jsonl", "task_started", "task_complete"),
        rollout(tmp_path, "started.jsonl", "task_complete", "task_started"),
        rollout(tmp_path, "empty.jsonl", "token_count"),
    )


@pytest.fixture
def asked(statuses, rollouts, monkeypatch):
    """Collect a codex and an agy pane while codex is at a rollout and both show screen."""

    def run(which, screen):
        path = rollouts[0] if which == "done" else rollouts[1]
        monkeypatch.setattr(codex_log, "codex_rollout", lambda *a: path)
        return statuses(("codex", "agy"), screen)

    return run


@pytest.fixture
def cx_ask():
    return fixture_text("codex-approval.txt")


def test_codex_approval_prompt_on_screen_during_a_turn_is_waiting(asked, cx_ask):
    assert asked("started", cx_ask)["codex"] == "waiting"


def test_agy_pane_showing_the_codex_approval_prompt_is_unaffected(asked, cx_ask):
    assert asked("started", cx_ask)["agy"] == "idle"


def test_codex_prompt_line_still_on_screen_after_task_complete_is_not_waiting(asked, cx_ask):
    assert asked("done", cx_ask)["codex"] == "idle"


def test_codex_screen_without_the_approval_prompt_is_not_waiting(asked, cx_ask):
    assert asked("started", cx_ask[: cx_ask.index("› 1.")])["codex"] == "idle"


@pytest.fixture
def cx_status(monkeypatch):
    """Status of a lone codex pane at rollout path, with its screen changed or not."""
    monkeypatch.setattr(collect, "read_tmux", lambda: tmux_panes("codex"))
    monkeypatch.setattr(claude_log, "read_claude_sessions", dict)

    def run(path, changed=True):
        monkeypatch.setattr(codex_log, "codex_rollout", lambda *a: path)
        monkeypatch.setattr(collect, "screen_changed", lambda ps, now: {p: changed for p in ps})
        return collect.collect()

    return run


def lone_status(snap):
    return next(a for t in snap["towns"] for a in t["agents"])["status"]


def test_codex_newest_event_task_complete_and_screen_changed_is_not_working(cx_status, rollouts):
    assert lone_status(cx_status(rollouts[0])) != "working"


def test_codex_newest_event_task_started_and_screen_changed_is_working(cx_status, rollouts):
    assert lone_status(cx_status(rollouts[1])) == "working"


def test_codex_no_rollout_or_no_turn_event_and_screen_changed_is_working(cx_status, rollouts):
    assert lone_status(cx_status(None)) == "working"
    assert lone_status(cx_status(rollouts[2])) == "working"


def test_codex_task_complete_and_screen_unchanged_is_idle(cx_status, rollouts):
    assert lone_status(cx_status(rollouts[0], False)) == "idle"


def test_codex_redraw_after_task_complete_does_not_start_a_new_round(cx_status, rollouts):
    towns_cx = [
        [{"agents": [dict(a, focus=False) for t in cx_status(rollouts[0], changed)["towns"] for a in t["agents"]]}]
        for changed in (True, False)
    ]
    st_cx = {"%1": {"status": "idle", "unseen": False, "round": 2}}
    for ts in towns_cx:
        st_cx = collect.mark_unseen(ts, st_cx)
    assert st_cx["%1"]["round"] == 2
    assert towns_cx[1][0]["agents"][0]["status"] == "idle"


def mu(raw, focus, state):
    ts = [{"agents": [{"pane": "%50", "status": raw, "focus": focus}]}]
    new_state = collect.mark_unseen(ts, state)
    return ts[0]["agents"][0]["status"], new_state


S0 = {"%50": {"status": "working", "unseen": False}}


def test_unseen_done_stays_until_seen():
    st1, s1 = mu("idle", False, S0)
    st2, s2 = mu("idle", False, s1)
    st3, s3 = mu("idle", True, s2)
    st4, _ = mu("idle", False, s3)
    assert st1 == st2 == "done"
    assert st3 == "idle"
    assert st4 == "idle"


def test_watched_pane_finishing_goes_straight_to_idle():
    _, s1 = mu("idle", False, S0)
    assert mu("idle", True, S0)[0] == "idle"
    assert mu("sleep", False, s1)[0] == "done"
    assert mu("working", False, s1)[0] == "working"


def test_idle_member_that_was_never_busy_is_not_marked_done():
    assert mu("idle", False, {})[0] == "idle"


def test_unseen_done_summoned_member_stays_under_its_lead():
    ts = [
        {
            "agents": [
                {"pane": "%60", "status": "idle", "focus": True},
                {"pane": "%61", "status": "idle", "focus": False, "lead": "%60"},
                {"pane": "%62", "status": "idle", "focus": False},
            ]
        }
    ]
    collect.mark_unseen(
        ts, {"%61": {"status": "working", "unseen": False}, "%62": {"status": "working", "unseen": False}}
    )
    assert [a["pane"] for a in ts[0]["agents"]] == ["%62", "%60", "%61"]
    assert ts[0]["agents"][2]["status"] == "done"


def mr(raw, state, seen=None, focus=False):
    ts = [{"agents": [{"pane": "%50", "status": raw, "focus": focus}]}]
    new_state = collect.mark_unseen(ts, state, seen)
    return ts[0]["agents"][0], new_state


def test_round_counts_each_finished_turn():
    a1, r1 = mr("idle", {"%50": {"status": "working", "unseen": False, "round": 4}})
    a2, r2 = mr("idle", r1)
    a3, r3 = mr("working", r2)
    a4, r4 = mr("sleep", r3)
    assert mr("idle", {})[0]["round"] == 0
    assert a1["round"] == 5
    assert a2["round"] == 5
    assert a3["round"] == 5
    assert a4["round"] == 6
    assert r4["%50"]["round"] == 6


def test_round_unseen_json_without_rounds_reads_as_round_0():
    assert mr("idle", {"%50": {"status": "working", "unseen": False}})[0]["status"] == "done"
    assert mr("idle", {"%50": {"status": "working", "unseen": False}})[0]["round"] == 1


def test_seen_round_read_is_not_done():
    wk = {"%50": {"status": "working", "unseen": False, "round": 2}}
    assert mr("idle", wk, {"%50": 2})[0]["status"] == "done"
    assert mr("idle", wk, {"%50": 3})[0]["status"] == "idle"
    assert mr("idle", wk, {"%50": 9})[0]["status"] == "idle"
    assert mr("idle", wk, {"%51": 9})[0]["status"] == "done"


def test_seen_reading_a_done_round_clears_done_on_next_collection():
    assert mr("idle", {"%50": {"status": "idle", "unseen": True, "round": 3}}, {"%50": 3})[0]["status"] == "idle"


def wm(state, seen=None, focus=False, raw="done", sp=None):
    """One collection of a workmux pane: raw "done" is the ✅ icon."""
    ts = [{"agents": [{"pane": "%50", "status": raw, "focus": focus, "sp": sp}]}]
    new_state = collect.mark_unseen(ts, state, seen)
    return ts[0]["agents"][0], new_state


WM_WORKING = {"%50": {"status": "working", "unseen": False, "round": 2}}


def test_workmux_done_after_working_is_a_new_round_shown_done():
    a, s = wm(WM_WORKING)
    a2, _ = wm(s)
    assert (a["round"], a["status"], s["%50"]["round"]) == (3, "done", 3)
    assert (a2["round"], a2["status"]) == (3, "done")


@pytest.mark.parametrize(("sp", "status"), [(None, "idle"), ((120.0, 300), "idle"), ((0.0, 300), "sleep")])
def test_workmux_done_whose_round_was_read_falls_back_to_idle_or_sleep(sp, status):
    _, s1 = wm(WM_WORKING)
    a2, s2 = wm(s1, {"%50": 3}, sp=sp)
    a3, _ = wm(s2, {"%50": 3}, sp=sp)
    assert a2["status"] == a3["status"] == status


def test_workmux_done_cleared_by_looking_does_not_light_up_again():
    _, s1 = wm(WM_WORKING)
    a2, s2 = wm(s1, focus=True)
    a3, s3 = wm(s2)
    a4, _ = wm(s3, raw="idle")
    assert a2["status"] == a3["status"] == a4["status"] == "idle"
    assert a4["round"] == 3


def test_workmux_done_seen_first_with_no_state_is_shown_done():
    a, s = wm({})
    assert (a["status"], a["round"], s["%50"]["round"]) == ("done", 1, 1)


def test_workmux_done_again_after_a_read_round_is_shown_done():
    _, s1 = wm(WM_WORKING)
    _, s2 = wm(s1, {"%50": 3})
    _, s3 = wm(s2, {"%50": 3}, raw="working")
    a4, _ = wm(s3, {"%50": 3})
    assert (a4["status"], a4["round"]) == ("done", 4)


def test_workmux_done_left_over_from_a_read_round_hides_a_round_run_between_collections():
    _, s1 = wm(WM_WORKING)
    a2, _ = wm(s1, {"%50": 3})
    assert (a2["status"], a2["round"]) == ("idle", 3)


def test_seen_no_seen_json_reads_as_empty():
    assert collect.read_seen() == {}


def test_seen_mark_seen_never_lowers_a_value_and_keeps_other_members():
    sidebars.mark_seen("%50", 5)
    sidebars.mark_seen("%50", 3)
    sidebars.mark_seen("%51", 1)
    assert collect.read_seen() == {"%50": 5, "%51": 1}


def test_seen_broken_seen_json_reads_as_empty(party_dir):
    os.makedirs(party_dir)
    with open(os.path.join(party_dir, "seen.json"), "w") as f:
        f.write("{broken")
    assert collect.read_seen() == {}


@pytest.fixture
def gone():
    """State after a collection where %50, last idle at round 5 and seen, is missing."""
    gt = [{"agents": [{"pane": "%51", "status": "working", "focus": False}]}]
    return collect.mark_unseen(gt, {"%50": {"status": "idle", "unseen": False, "round": 5}}, {"%50": 5})


def test_round_pane_missing_from_a_collection_keeps_its_round(gone):
    assert gone["%50"]["round"] == 5
    assert not gone["%50"]["unseen"]


def test_round_pane_coming_back_goes_on_from_its_old_round(gone):
    g2 = mr("working", gone, {"%50": 5})[1]
    g3 = mr("idle", g2, {"%50": 5})[0]
    assert g3["round"] == 6
    assert g3["status"] == "done"


def ag(p, s, w="@1"):
    return {"pane": p, "status": s, "window": w}


def test_bell_rings_once_for_hidden_members():
    vis = {"%1": {"visible": False}, "%2": {"visible": False}, "%9": {"visible": True}}
    r0, _ = collect.bell_panes(None, [ag("%1", "waiting")], vis)
    r1, b1 = collect.bell_panes(
        {"%1": "working", "%9": "working"}, [ag("%1", "done"), ag("%2", "idle"), ag("%9", "waiting")], vis
    )
    r2, _ = collect.bell_panes(b1, [ag("%1", "done")], vis)
    assert r0 == []
    assert r1 == ["%1"]
    assert r2 == []


def test_tidy_closes_only_a_sidebar_left_alone_in_its_window():
    lp = {
        "%1": {"window": "@1", "sidebar": True},
        "%2": {"window": "@1", "sidebar": False},
        "%3": {"window": "@2", "sidebar": True},
        "%4": {"window": "@3", "sidebar": False},
    }
    assert collect.lonely_sidebars(lp) == ["%3"]


CREW_DONE = {"pane": "%2", "status": "done", "lead": "%1"}
SOLO_DONE = {"pane": "%3", "status": "done"}
CREW_WAIT = {"pane": "%4", "status": "waiting", "lead": "%1"}


def test_crew_done_rings_no_bell():
    vis2 = {"%2": {"visible": False}, "%3": {"visible": False}, "%4": {"visible": False}}
    ring_crew, _ = collect.bell_panes(
        {"%2": "working", "%3": "working", "%4": "working"}, [CREW_DONE, SOLO_DONE, CREW_WAIT], vis2
    )
    assert sorted(ring_crew) == ["%3", "%4"]


def test_crew_done_is_not_counted_in_party_reports():
    assert collect.unread_count({"%2": "done", "%3": "done", "%4": "waiting"}, {"%2", "%4"}) == 2
    assert collect.unread_count({"%2": "done"}, set()) == 1


def test_no_snapshot_and_lock_taken_waits_for_the_collector(party_dir, monkeypatch):
    os.makedirs(party_dir)
    lock = os.open(os.path.join(party_dir, "snapshot.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX)
    collected, got = [], []
    monkeypatch.setattr(
        collect, "collect", lambda *a: collected.append(1) or {"t": time.time(), "towns": [], "panes": {}}
    )
    th = threading.Thread(target=lambda: got.append(collect.get_snapshot()))
    th.start()
    time.sleep(0.3)
    waited = not got
    with open(os.path.join(party_dir, "snapshot.json"), "w") as f:
        json.dump({"v": collect.SNAP_VERSION, "t": time.time(), "towns": [], "panes": {}, "mark": 1}, f)
    fcntl.flock(lock, fcntl.LOCK_UN)
    os.close(lock)
    th.join(5)
    assert waited
    assert got
    assert got[0].get("mark") == 1
    assert not collected


def test_list_panes_output_skips_a_line_with_the_wrong_field_count():
    good = collect.FIELD_SEP.join(["a", "1", "w\\037x"] + ["0"] * (len(collect.TMUX_FIELDS) - 3))
    rows = collect.parse_panes(good + "\n" + "a\\0371\\037bash\n")
    assert len(rows) == 1
    assert rows[0]["session_name"] == "a"
    assert rows[0]["window_name"] == "w\\037x"


def test_printable_drops_every_unicode_cc_character():
    def old_printable(s):
        return "".join(ch for ch in s if unicodedata.category(ch) != "Cc")

    every = [chr(i) for i in range(sys.maxunicode + 1)]
    rnd = random.Random(7)
    pool = [chr(c) for c in (*range(0xA1), 0xD7FF, 0xE000, 0x300, 0x301, 0x4E00, 0x9FFF, 0xFF21, 0x1F600, 0x10FFFF)]
    mixed = ["".join(rnd.choice(pool) for _ in range(rnd.randint(0, 40))) for _ in range(2000)]
    mixed += ["\ud800", "a\udbffb\udc00\x00", "é\x07中\x9f\x7f"]
    assert all(common.printable(c) == old_printable(c) for c in every)
    assert all(common.printable(s) == old_printable(s) for s in mixed)


LIMIT = {"text": "limit reached", "end": 990}


def test_codex_turn_that_ended_on_the_usage_limit_is_waiting_with_reason_limited(cx_status, tmp_path):
    error = {"message": "limit reached", "codex_error_info": "usage_limit_exceeded"}
    path = tmp_path / "limited.jsonl"
    event = {
        "type": "event_msg",
        "timestamp": "1970-01-01T00:16:30Z",
        "payload": {"type": "task_complete", "error": error},
    }
    path.write_text(json.dumps(event) + "\n")
    a = next(a for t in cx_status(str(path))["towns"] for a in t["agents"])
    assert (a["status"], a["reason"], a["limit"]) == ("waiting", "limited", LIMIT)


def test_claude_at_the_usage_limit_is_waiting_with_reason_limited(tmp_path):
    data = {
        "now": 1000,
        "panes": [pane("%20", "claude"), pane("%21", "claude")],
        "sessions": {"%20": {"sid": "a", "status": "idle"}, "%21": {"sid": "b", "status": "idle"}},
        "transcripts": {"a": "/a", "b": "/b"},
        "cache": {"/a": [990, 300, 0, LIMIT], "/b": [990, 300, 1000, None]},
    }
    new = members(collect.collect(write_fixture(tmp_path, data)))
    assert (new["%20"]["status"], new["%20"]["reason"], new["%20"]["limit"]) == ("waiting", "limited", LIMIT)
    assert new["%21"]["status"] == "idle"
    assert "reason" not in new["%21"]
