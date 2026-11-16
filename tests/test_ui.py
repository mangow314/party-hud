# pyright: reportOptionalSubscript=false
"""Tests index results they expect to exist; a None there fails the test, so the Optional check is off."""

import os
import re

import pytest
from screen import strip

from party_hud import art, collect, common, render, sidebars, ui

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "sidebar.json")
MDT = "# T\n\n- a **b** `c`\n\n| h | i |\n|---|---|\n| 1 | 2 |\n\n```\ncode line that is long\n```\nlast line of text"
rep = {"live": False, "start": 1, "end": 2, "text": MDT, "subagents": [{"desc": "d", "type": "t", "text": MDT + " 2"}]}


@pytest.fixture
def towns():
    return collect.collect(FIXTURE)["towns"]


@pytest.fixture
def agents(towns):
    return [a for t in towns for a in t["agents"]]


@pytest.fixture
def done(agents):
    return dict(agents[0], status="done", hp_left=410000, hp_max=1000000)


@pytest.fixture
def windowed(towns):
    """The fixture towns with every member in its own window, then %1 and %2 sharing one, as the cursor tests leave them."""
    for t in towns:
        for a in t["agents"]:
            a["window"] = "@" + a["pane"][1:]
    towns[0]["agents"][1]["window"] = towns[0]["agents"][0]["window"]
    return towns


def mk(pane, status):
    return {"pane": pane, "status": status}


def mm(pane, name, status, lead=None):
    return dict(mk(pane, status), name=name, **({"lead": lead} if lead else {}))


mt = [
    {
        "name": "Studio",
        "agents": [mm("%1", "a", "idle"), mm("%2", "b", "working"), mm("%3", "c", "waiting"), mm("%4", "d", "done")],
    },
    {"name": "Empty", "agents": []},
    {
        "name": "Lab",
        "agents": [
            mm("%5", "lead", "working"),
            mm("%6", "w1", "idle", "%5"),
            mm("%7", "w2", "waiting", "%5"),
            mm("%8", "e", "waiting"),
        ],
    },
]


def test_r_in_the_sidebar_opens_the_report_pane(towns):
    assert ui.handle_key("r", {"focus": "party", "sel": "%1", "squad": None, "peek": False}, towns) == "report"
    assert ui.handle_key("r", {"focus": "party", "sel": None, "squad": None, "peek": False}, towns) is None


@pytest.fixture
def menu(monkeypatch):
    """open_select with ui.tmux and sidebars.tmux recorded: run(towns, new_pane) -> tmux calls."""

    def run(menu_towns, new_pane=None):
        calls = []
        monkeypatch.setattr(ui, "tmux", lambda *a: calls.append(a))
        monkeypatch.setattr(
            sidebars, "tmux", lambda *a: calls.append(a) or ("%9\n" if a[0] in ("new-pane", "split-window") else "")
        )
        monkeypatch.setattr(ui, "get_snapshot", lambda f=None: {"towns": menu_towns})
        monkeypatch.setattr(sidebars, "_new_pane", new_pane)
        ui.open_select()
        return calls

    return run


def test_menu_with_no_members_only_shows_the_message(menu):
    calls = menu([{"name": "A", "agents": []}])
    assert calls == [("display-message", "no party members")]


def test_menu_with_members_opens_a_pane_that_runs_select(menu):
    calls = menu(mt, False)
    opened_cmd = next(c for c in calls if c[0] == "split-window")
    assert opened_cmd[-1].endswith("party.py --select")
    assert not any("display-menu" in " ".join(c) for c in calls)


def test_menu_floating_pane_is_titled_party(menu):
    calls = menu(mt, True)
    float_cmd = next(c for c in calls if c[0] == "new-pane")
    assert float_cmd[float_cmd.index("-T") + 1] == " Party "
    assert float_cmd[-1].endswith("party.py --select")


def test_r_opens_the_report_beside_the_sidebars_own_window(monkeypatch):
    opened = []
    monkeypatch.setattr(ui, "open_report_pane", lambda *a: opened.append(a))
    monkeypatch.setenv("TMUX_PANE", "%5")
    ui.open_report("%7")
    assert opened == [("%5", "%7")]


def test_live_page_reread_follows_the_new_status(monkeypatch):
    monkeypatch.setattr(ui, "report_for", lambda a: {"status_seen": a["status"]})
    q = [("S", {"pane": "%1", "status": "working"})]
    monkeypatch.setattr(ui, "get_snapshot", lambda f=None: {"towns": [{"agents": [{"pane": "%1", "status": "done"}]}]})
    seen = ui.refresh_live(q, 0)
    monkeypatch.setattr(ui, "get_snapshot", lambda f=None: {"towns": [{"agents": []}]})
    gone_ = ui.refresh_live(q, 0)
    assert seen == {"status_seen": "done"}
    assert q[0][1]["status"] == "done"
    assert gone_ is None


def test_menu_enlarges_the_pane_for_the_report_and_shrinks_it_for_select(monkeypatch):
    fit_calls = []
    monkeypatch.setattr(ui, "fit_report_pane", lambda p, s: fit_calls.append(("fit", p, s)))
    monkeypatch.setattr(
        ui,
        "run_select",
        lambda p=None, f=None, images=None: fit_calls.append(("select", p)) or ("%1" if p is None else None),
    )
    monkeypatch.setattr(
        ui, "run_report", lambda p, f=None, back=False, images=None: fit_calls.append(("report", p)) or "%1"
    )
    monkeypatch.setenv("TMUX_PANE", "%5")
    ui.run_menu()
    assert fit_calls == [
        ("select", None),
        ("fit", "%5", False),
        ("report", "%1"),
        ("fit", "%5", True),
        ("select", "%1"),
    ]


@pytest.fixture
def followed(towns):
    """follow_here to Server @4, then to a Studio window without members: the cursor after each."""
    for t in towns:
        for a in t["agents"]:
            a["window"] = "@" + a["pane"][1:]
    fh = {"focus": "party", "sel": "%1", "squad": None, "peek": False}
    ui.follow_here(fh, towns, {"session": "Server", "window": "@4"})
    first = dict(fh)
    ui.follow_here(fh, towns, {"session": "Studio", "window": "@9"})
    return first, fh


def test_switching_window_moves_the_cursor_to_the_member_there(followed):
    fh, _ = followed
    assert fh["sel"] == "%4"
    assert fh["focus"] == "party"


def test_switching_to_a_window_without_members_rests_on_the_squad(followed):
    _, fh = followed
    assert fh["focus"] == "squad"
    assert fh["squad"] == 0


def test_cursor_already_on_a_member_of_that_window_stays(windowed):
    towns = windowed
    fh = {"focus": "party", "sel": "%2", "squad": None, "peek": False}
    ui.follow_here(fh, towns, {"session": "Studio", "window": towns[0]["agents"][0]["window"]})
    assert fh["sel"] == "%2"


def test_next_waiting_jumps_to_waiting_then_cycles_done():
    nw = [{"pane": p, "status": s} for p, s in (("%1", "idle"), ("%2", "done"), ("%3", "waiting"), ("%4", "done"))]
    assert ui.next_waiting(nw, "%1") == "%3"
    assert ui.next_waiting(nw, "%3") == "%3"
    assert ui.next_waiting([dict(a, status="idle") if a["status"] == "waiting" else a for a in nw], "%2") == "%4"


LEAD_IDLE = {"pane": "%1", "status": "idle"}
CREW_DONE = {"pane": "%2", "status": "done", "lead": "%1"}
SOLO_DONE = {"pane": "%3", "status": "done"}
CREW_WAIT = {"pane": "%4", "status": "waiting", "lead": "%1"}


def test_crew_done_is_skipped_by_the_report_queue():
    with_solo = [{"name": "A", "agents": [LEAD_IDLE, CREW_DONE, SOLO_DONE]}]
    with_wait = [{"name": "A", "agents": [LEAD_IDLE, CREW_DONE, CREW_WAIT]}]
    assert [m["pane"] for _, m in ui.report_queue(with_solo)] == ["%3", "%1", "%2"]
    assert next(m["pane"] for _, m in ui.report_queue(with_wait)) == "%4"
    assert ui.report_queue(with_solo, "%2")[0][1]["pane"] == "%2"


def test_crew_done_is_skipped_by_prefix_a():
    assert ui.next_waiting([LEAD_IDLE, CREW_DONE, SOLO_DONE], "%1") == "%3"
    assert ui.next_waiting([LEAD_IDLE, CREW_DONE], "%1") is None
    assert ui.next_waiting([LEAD_IDLE, CREW_DONE, CREW_WAIT], "%1") == "%4"


pi = ui.parse_input


def test_left_mouse_press_clicks():
    assert pi("\x1b[<0;5;7M\x1b[<0;5;7m") == [("click", 6)]


def test_mouse_move_hovers():
    assert pi("\x1b[<35;5;3M") == [("hover", 2)]


def test_wheel_is_k_and_j():
    assert pi("\x1b[<64;1;1M\x1b[<65;1;1M") == [("key", "k"), ("key", "j")]


def test_arrow_keys_are_k_and_j():
    assert pi("\x1b[A\x1b[B") == [("key", "k"), ("key", "j")]


def test_lone_esc_and_plain_keys():
    assert pi("\x1b") == [("key", "\x1b")]
    assert pi("jv") == [("key", "j"), ("key", "v")]


def test_pgup_and_pgdn_are_their_own_keys():
    assert pi("\x1b[5~\x1b[6~j") == [("key", "PgUp"), ("key", "PgDn"), ("key", "j")]


def test_sidebar_ignores_pgup(windowed):
    towns = windowed
    assert ui.handle_key("PgUp", {"focus": "party", "sel": "%1", "squad": None, "peek": False}, towns) is None


def test_report_scroll_keys():
    assert [ui.report_scroll(k, 5, 20, 10) for k in ["k", "j", "PgUp", "PgDn", "g", "G", "b", " ", "x"]] == [
        4,
        6,
        0,
        14,
        0,
        20,
        5,
        5,
        5,
    ]


def test_report_side_rows_keep_the_hints_and_rows_total(done):
    assert len(render.report_side_rows(done, "Studio", rep, 2, 3, (24, 14), rows_total=30)) == 30
    assert "n/N" in strip(render.report_side_rows(done, "Studio", rep, 2, 3, (24, 14), rows_total=30)[-2])


def test_report_offset_stays_inside_its_limits():
    assert ui.report_scroll("j", 20, 20, 10) == 20
    assert ui.report_scroll("k", 0, 20, 10) == 0
    assert ui.report_scroll("PgDn", 15, 20, 10) == 20
    assert all(ui.report_scroll(k, 0, 0, 10) == 0 for k in ["j", "k", "PgUp", "PgDn", "g", "G"])


def test_report_n_and_shift_n_step_and_wrap():
    assert [
        ui.report_step("N", 0, 3),
        ui.report_step("N", 1, 3),
        ui.report_step("n", 2, 3),
        ui.report_step("N", 0, 1),
        ui.report_step("x", 1, 3),
    ] == [2, 0, 0, 0, 1]


def test_report_left_column_hint_row_shows_n_and_keys(done):
    rh = [
        re.sub(r"\x1b\[[0-9;]*m", "", r)
        for r in render.report_side_rows(done, "Studio", rep, 2, 3, (24, 14), rows_total=30)
    ]
    assert any("n/N" in r and "? keys" in r for r in rh)


@pytest.fixture
def lrep():
    lt = {
        "ask": "請幫我把這個很長的需求完整地實作並且測試一下然後回報給我 " * 3,
        "files": [f"/w/party_hud/f{n}.py" for n in range(8)],
        "cmds": 14,
        "agents": 2,
        "dir": "/w/party_hud/some/dir",
        "branch": "feature/x",
        "cwd": "/w",
    }
    lrep = dict(rep, text="\n".join(f"L{n}" for n in range(60)), task=lt)
    return lrep


@pytest.fixture
def lparts(done, lrep):
    lparts = {
        h: render.report_parts(
            done,
            "Studio",
            lrep,
            [],
            100,
            2,
            3,
            art=True,
            banner=(68, 8),
            portrait=(24, 14),
            height=h,
            now=860 + 3725,
            fixed=True,
        )
        for h in (24, 40)
    }
    return lparts


def test_report_split_page_left_column_taller_than_the_pane(lparts):
    for h in (24, 40):
        left, right = lparts[h]
        assert len(left) == h
        assert "? keys" in strip(left[-2])
        assert strip(left[-1]).startswith("┗")
        assert all(common.cw(strip(r)) == render.SPLIT_SIDE_COLS for r in left)
        assert len(render.report_view(left, right, h, 0)[0]) == h
        assert "? keys" in strip(render.report_view(left, right, h, 0)[0][h - 2])


def test_report_left_column_cut_shows_a_dim_ellipsis_row(done, lrep, lparts):
    assert all(strip(lparts[h][0][-3]).strip("┃ ") == "…" for h in (24, 40))
    assert not any(
        strip(r).strip("┃ ") == "…"
        for r in render.report_parts(
            done,
            "Studio",
            lrep,
            [],
            100,
            2,
            3,
            art=True,
            banner=(68, 8),
            portrait=(24, 14),
            height=60,
            now=860 + 3725,
            fixed=True,
        )[0]
    )


def test_report_left_column_that_fits_is_the_same_with_and_without_fit(done):
    fit_args = (
        done,
        "Studio",
        dict(rep, task={"ask": "q", "files": [], "cmds": 0, "agents": 0, "dir": None, "branch": None}),
        1,
        1,
        (24, 14),
    )
    assert render.report_side_rows(
        *fit_args, rows_total=30, now=860 + 3725, labels=True, fit=True
    ) == render.report_side_rows(*fit_args, rows_total=30, now=860 + 3725, labels=True)


@pytest.mark.parametrize("h", [8, 12, 17, 24])
def test_report_left_column_keeps_or_drops_the_portrait_whole(done, lrep, h):
    pref = art.image_row(art.big_portrait_id(done), 0, 1).split(chr(0x10EEEE))[0]
    lp = render.report_parts(
        done,
        "Studio",
        lrep,
        [],
        100,
        2,
        3,
        art=True,
        banner=(68, 8),
        portrait=(24, 14),
        height=h,
        now=860 + 3725,
        fixed=True,
    )[0]
    nport = sum(pref in r for r in lp)
    assert nport in (0, 14)
    assert len(lp) == h
    assert "? keys" in strip(lp[-2])


NEED = {
    "report": "n N j k ↑ ↓ wheel PgUp PgDn g G ⏎ q Esc ?",
    "sidebar": "j k J K 1-9 n v r ⏎ q Esc P ?",
    "select": "j k 1-9 [ ] ⏎ l q Esc ?",
    "saved": "j k ↑ ↓ wheel PgUp PgDn g G h q Esc ?",
}


def test_key_help_lists_every_key_of_its_mode():
    assert all(
        set(NEED[m].split()) <= {t for k, _ in render.HELP[m] for t in k.replace(" / ", " ").split()} for m in NEED
    )


def test_key_help_is_exactly_height_rows_of_width_cells():
    assert all(
        len(rows) == h and all(common.cw(r) == w for r in rows)
        for m in NEED
        for w in (28, 33, 80)
        for h in (3, 12, 30)
        for rows in [[strip(r) for r in render.help_screen(m, w, h)]]
    )


HB = [strip(r) for r in render.help_screen("report", 80, 30)]
HK = max(common.cw(k) for k, _ in render.HELP["report"]) + 1
HW = 5 + HK + max(common.cw(t) for _, t in render.HELP["report"])
HN = len(render.HELP["report"]) + 2


def test_key_help_box_is_centred():
    assert HB[(30 - 1 - HN) // 2].startswith(" " * ((80 - HW) // 2) + "╭")
    assert not any("╭" in r for r in HB[: (30 - 1 - HN) // 2])
    assert HB[(30 - 1 - HN) // 2].rstrip().endswith("╮")
    assert common.cw(HB[(30 - 1 - HN) // 2].rstrip()) == (80 - HW) // 2 + HW


PH = art.image_row(art.BANNER_ID, 0, 60)
FAINT = "\x1b[2m"
OT, OL = (30 - 1 - HN) // 2, (80 - HW) // 2


@pytest.fixture
def overlay():
    pg = [PH + "  \x1b[1;31mred\x1b[0m text", "\x1b[32m" + "你好" * 40 + "\x1b[0m", "short"] + [
        "\x1b[34mrow\x1b[0m " + "x" * 70
    ] * 27
    ov = render.help_overlay(pg, "report", 80, 30)
    return pg, ov, [strip(r) for r in ov]


def test_key_help_overlay_keeps_the_page_text_on_both_sides(overlay):
    pg, ov, ovt = overlay
    box_rows = [strip(r) for r in render.help_box("report", 80, 30)[0]]
    assert len(ov) == 30
    assert all(common.cw(r) == 80 for r in ovt[OT : OT + HN])
    assert [r[OL : OL + HW] for r in ovt[OT : OT + HN]] == box_rows
    assert ovt[OT].startswith("row ")
    assert ovt[OT][OL - 1] == "x"
    assert ovt[OT][OL + HW :] == strip(pg[OT])[OL + HW : 80].ljust(80 - OL - HW)
    assert "x" in ovt[OT][OL + HW :]


def test_key_help_overlay_page_rows_outside_the_box_are_faint(overlay):
    pg, ov, _ = overlay
    assert ov[1] == render.dim_row(pg[1])
    assert ov[1].startswith(FAINT)
    assert ov[1].endswith("\x1b[0m")
    assert all(r.startswith(FAINT) and FAINT in r[len(FAINT) :] for r in (ov[OT - 1], ov[OT + HN]))


def test_key_help_overlay_cuts_a_wide_character_into_a_space():
    assert strip(render.cols_of("a你b", 2, 4)) == " b"
    assert strip(render.cols_of("a你b", 0, 2)) == "a "
    assert strip(render.cols_of("ab", 0, 5)) == "ab   "


def test_key_help_overlay_keeps_the_width_under_wide_characters():
    assert all(
        common.cw(strip(r)) == w
        for w in (79, 80)
        for r in render.help_overlay(["你" * 40] * 30, "report", w, 30)[OT : OT + HN]
    )


def test_key_help_overlay_keeps_placeholder_cells_around_the_box():
    left_part, right_part = render.cols_of(PH, 0, OL), render.cols_of(PH, OL + HW, 80)
    assert left_part.count("\U0010eeee") == OL
    assert right_part.count("\U0010eeee") == 60 - OL - HW
    assert "\x1b[38;2;" in right_part
    assert strip(left_part) + strip(render.cols_of(PH, OL, OL + HW)) + strip(right_part) == strip(
        render.cols_of(PH, 0, 80)
    )


def test_key_help_lists_j_as_next_and_k_as_prev():
    keys = dict(render.HELP["sidebar"])
    assert keys["j k"] == "next / prev card"
    assert keys["J K"] == "next / prev squad"


def test_key_hints_keep_the_help_key_at_the_narrowest_widths(windowed):
    towns = windowed
    assert all(("? keys" in strip(render.hint_line(m, w)) for m, w in (("sidebar", 28), ("report", 24))))
    assert "q close" in strip(render.hint_line("report", 60))
    assert "? keys" in strip(render.render(towns, 28, "%1", None, "sidebar")).splitlines()[-1]


def test_key_help_toggle():
    assert [
        ui.help_toggle(k, s)
        for k, s in [("?", False), ("j", False), ("?", True), ("\x1b", True), ("q", True), ("n", True), ("\r", True)]
    ] == [(True, True), (False, False), (False, True), (False, True), (False, True), (True, True), (True, True)]


RL, RR = [f"S{n:02}".ljust(30) for n in range(12)], [f"R{n:02}" for n in range(40)]


@pytest.fixture
def views():
    return render.report_view(RL, RR, 10, 0), render.report_view(RL, RR, 10, 7)


def test_report_view_keeps_the_left_column_and_shifts_the_right(views):
    (v0, _), (v7, o7) = views
    assert o7 == 7
    assert [r[:30] for r in v7] == [r[:30] for r in v0] == RL[:10]
    assert [r[32:] for r in v7] == RR[7:17]
    assert [r[32:] for r in v0] == RR[:10]


def test_report_view_clamps_the_offset():
    assert render.report_view(RL, RR, 10, 99) == (render.report_view(RL, RR, 10, 30)[0], 30)
    assert render.report_view(RL, RR, 10, -3)[1] == 0
    assert render.report_view(RL, RR[:6], 10, 4)[1] == 0


def test_report_view_rows_are_left_gap_right_wide(views):
    _, (v7, _) = views
    assert all(common.cw(r) == 30 + 2 + 3 for r in v7)
    assert len(v7) == 10
    assert len(render.report_view(RL, RR[:4], 20, 0)[0]) == 12


def test_report_view_narrow_page_scrolls_whole():
    np_ = [f"P{n}" for n in range(30)]
    nv, no = render.report_view([], np_, 8, 5)
    assert nv == np_[5:13]
    assert no == 5


def test_report_page_fixed_left_column_closes_on_the_last_row(done):
    fl, fr = render.report_parts(
        done,
        "Studio",
        dict(rep, text="\n".join(f"L{n}" for n in range(60))),
        [],
        150,
        art=True,
        banner=(88, 10),
        portrait=(24, 14),
        height=40,
        fixed=True,
    )
    assert len(fl) == 40
    assert strip(fl[-1]).startswith("┗")
    assert len(fr) > 40


def test_class_icon_is_fixed_by_session_id(windowed, agents, tmp_path):
    towns = windowed
    fe = next(a for a in agents if a["pane"] == "%1")
    assert common.class_icon(fe) in render.render(towns, 33)
    assert collect.collect(FIXTURE)["towns"][0]["agents"][1]["cls"] == fe["cls"]
    with open(FIXTURE) as f:
        moved = tmp_path / "moved.json"
        moved.write_text(f.read().replace('"%4"', '"%40"'))
    server = collect.collect(FIXTURE)["towns"][1]["agents"][0]
    server_moved = collect.collect(str(moved))["towns"][1]["agents"][0]
    assert (server_moved["pane"], server_moved["id"]) == ("%40", server["id"])
    assert server_moved["cls"] == server["cls"]


@pytest.fixture
def hk(windowed):
    """handle_key on the windowed fixture: (cursor after, action). After sorting: Studio = [%2 waiting, %1 busy], Server = [%4]."""

    def run(k, sel="%1", focus="party", squad=None, ts=None):
        st = {"focus": focus, "sel": sel, "squad": squad, "peek": False}
        return st, ui.handle_key(k, st, ts or windowed)

    return run


@pytest.fixture
def empty(windowed):
    return [*windowed, dict(windowed[1], name="Empty", agents=[])]


def test_j_and_k_step_one_member_within_the_squad(hk):
    assert hk("k")[0]["sel"] == "%2"
    assert hk("j", "%2")[0]["sel"] == "%1"


def test_j_and_k_stop_at_the_squads_ends(hk):
    assert hk("j")[0]["sel"] == "%1"
    assert hk("k", "%2")[0]["sel"] == "%2"
    assert hk("j", "%4")[0]["sel"] == "%4"


def test_shift_j_and_k_jump_squads(hk):
    assert hk("J")[0]["sel"] == "%4"
    assert hk("K", "%4")[0]["sel"] == "%2"


def test_digits_select_the_nth_card(hk):
    assert hk("2")[0]["sel"] == "%1"
    assert hk("1")[0]["sel"] == "%2"
    assert hk("3")[0]["sel"] == "%1"


def test_n_jumps_to_the_next_waiting_or_done(hk):
    assert hk("n")[0]["sel"] == "%2"
    assert hk("n", "%2")[0]["sel"] == "%2"


def test_v_toggles_peek(hk):
    assert hk("v")[0]["peek"] is True


def test_enter_goes_to_the_member_or_the_session(hk):
    assert hk("\r")[1] == "jump"
    assert hk("\r", focus="squad", squad=1)[1] == "jump_squad"


def test_shift_j_onto_a_squad_without_members_rests_on_it(hk, empty):
    st, _ = hk("J", "%4", ts=empty)
    assert st["focus"] == "squad"
    assert st["squad"] == 2


def test_on_an_empty_squad_j_and_k_do_nothing(hk, empty):
    assert all(hk(k, "%4", focus="squad", squad=2, ts=empty)[0]["focus"] == "squad" for k in "jk")


@pytest.fixture
def pointed(windowed):
    """point_at the current squad, then another squad, then a card: the cursor after each."""
    pt = {"focus": "party", "sel": "%1", "squad": None, "peek": False}
    steps = []
    for target in (("squad", 0), ("squad", 1), ("agent", "%2")):
        ui.point_at(target, pt, windowed)
        steps.append(dict(pt))
    return steps


def test_mouse_over_the_current_squads_row_keeps_the_member(pointed):
    pt = pointed[0]
    assert pt["sel"] == "%1"


def test_mouse_over_another_squad_selects_its_first_member(pointed):
    pt = pointed[1]
    assert pt["focus"] == "party"
    assert pt["sel"] == "%4"


def test_mouse_over_a_card_selects_that_member(pointed):
    pt = pointed[2]
    assert pt["focus"] == "party"
    assert pt["sel"] == "%2"


def test_next_waiting_for_prefix_a(windowed):
    agents = [a for t in windowed for a in t["agents"]]
    assert ui.next_waiting(agents, "%1") == "%2"
    assert ui.next_waiting(agents, "%2") == "%2"
    assert ui.next_waiting([a for a in agents if a["status"] != "waiting"], "%1") is None


def test_shared_cursor_is_written_and_read_without_peek(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "CURSOR", str(tmp_path / "fixture.cursor"))
    a = {"focus": "squad", "sel": "%4", "squad": 1, "peek": True}
    b = {"focus": "party", "sel": "%1", "squad": None, "peek": False}
    common.save_cursor(a)
    common.load_cursor(b)
    assert b == {"focus": "squad", "sel": "%4", "squad": 1, "peek": False}


def test_sidebar_q_hides_esc_and_p_go_back(hk):
    assert hk("q")[1] == "hide"
    assert hk("\x1b")[1] == "back"
    assert hk("P")[1] == "back"
