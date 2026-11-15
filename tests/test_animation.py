# pyright: reportOperatorIssue=false
"""render.sp_points returns None when SP is unknown; these members have SP, and a None there fails the test anyway."""

import os

import pytest
from screen import strip

from party_hud import collect, common, render, ui

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
def fe(agents):
    return next(a for a in agents if a["pane"] == "%1")


ph = ["", "BANNER1", "BANNER2", ""]
pbody = [
    "P1a",
    "P1b",
    "",
    "P2",
    "",
    common.fg("green") + "c1",
    "",
    common.fg("green") + "c2",
    "",
    "P3",
    "",
    "P4",
    "",
    "P5",
]
pf = render.report_frames(ph + pbody, 100)
pn = len(ph + pbody)


def test_report_animation_has_at_most_5_frames_ending_with_the_whole_page():
    assert pf[-1] == ph + pbody
    assert 2 <= len(pf) <= 5
    assert all(len(f) == pn for f in pf)


def test_report_animation_first_frame_has_the_head_and_first_paragraphs():
    assert all(f[:3] == ph[:3] for f in pf)
    assert pf[0][3:9] == ["", "P1a", "P1b", "", "P2", ""]
    assert pf[0][9:] == [""] * (pn - 9)
    assert [r for r in pf[0] if r] == ["BANNER1", "BANNER2", "P1a", "P1b", "P2"]


def test_report_animation_never_cuts_a_code_block():
    cb = next(i for i, r in enumerate(ph + pbody) if r.endswith("c1"))
    assert all(bool(f[cb]) == bool(f[cb + 2]) for f in pf)
    assert any(f[cb] for f in pf)
    assert not pf[0][cb]


def test_report_animation_needs_2_paragraphs():
    assert render.report_frames(ph + ["only", "one"], 100) == [ph + ["only", "one"]]
    assert render.report_frames(ph + ["a"], 100) == [ph + ["a"]]


def test_report_animation_drops_steps_that_change_nothing_visible():
    assert render.report_frames(ph + pbody, 6)[-1] == ph + pbody
    assert len(render.report_frames(ph + pbody, 6)) < len(pf)
    assert render.report_frames(ph + pbody + ["", "hint"], 100, tail=2)[0][-2:] == ["", "hint"]


def test_report_animation_keeps_the_left_column_and_the_width(done):
    fl_, fr_ = render.report_parts(
        done,
        "Studio",
        dict(rep, text="\n\n".join(f"para {n}" for n in range(9))),
        [],
        150,
        art=True,
        banner=(88, 10),
        portrait=(24, 14),
        height=40,
        fixed=True,
    )
    ff = render.report_frames(fr_, 40)
    assert len(ff) > 1
    assert any(side.strip() for side in fl_)
    assert all(
        r.startswith(side) for f in ff for r, side in zip(render.report_view(fl_, f, 40, 0)[0], fl_, strict=False)
    )
    assert all(
        (
            common.cw(r) <= common.cw(g)
            for f in ff
            for r, g in zip(render.report_view(fl_, f, 40, 0)[0], render.report_view(fl_, fr_, 40, 0)[0])
        )
    )


def test_report_animation_skips_frames_equal_in_the_visible_rows():
    vf = ["", "B", "", "p0", "", "p1", "p1b", "", "p2", "", "p3"]
    vf_ = render.report_frames(vf, 8)
    vg = ["", "B", "", "p0", "p0b", "", "p1", "", "p2"]
    assert len(vf_) == 2
    assert vf_[-1] == vf
    assert len(render.report_frames(vf, 100)) == 4
    assert render.report_frames(vg, 6) == [vg]


def test_party_anim_off_turns_the_animation_off():
    assert ui.report_anim_enabled("")
    assert ui.report_anim_enabled("on")
    assert not ui.report_anim_enabled("off\n")
    assert not ui.report_anim_enabled(" off ")


@pytest.fixture
def a0(fe):
    return dict(fe, status="working")


@pytest.fixture
def a1(a0):
    return dict(a0, hp=48, hp_left=96000, sp=(1320, 3600))


@pytest.fixture
def an(a0, a1):
    """Animation state after a0 at 0 s and a1 at 10 s, and what the 10 s call returned."""
    an = {}
    ui.animate(an, [a0], 0.0)
    return an, ui.animate(an, [a1], 10.0)


def test_sidebar_animation_shows_the_new_value_with_the_change(an, a0):
    _, d1 = an
    assert not d1[2]
    assert d1[0][0]["hp"] == 48
    assert d1[0][0]["hp_delta"] == 48 - a0["hp"]
    assert d1[0][0]["sp_delta"] == 22 - render.sp_points(a0)


def test_sidebar_animation_labels_stay_10_s_and_never_make_the_loop_busy(an, a1):
    an, _ = an
    lab = [ui.animate(an, [a1], t) for t in (19.9, 20.0)]
    assert not lab[0][2]
    assert lab[0][0][0]["hp_delta"] is not None
    assert not lab[1][2]
    assert lab[1][0][0] is a1


def test_sidebar_animation_a_new_change_restarts_the_10_s(a0, a1):
    a2, rs = dict(a1, hp=88, hp_left=176000), {}
    ui.animate(rs, [a0], 0.0)
    ui.animate(rs, [a1], 10.0)
    ui.animate(rs, [a2], 12.0)
    r1, r2 = ui.animate(rs, [a2], 21.9), ui.animate(rs, [a2], 22.0)
    assert r1[0][0]["hp_delta"] == 40
    assert r2[0][0] is a2


def test_sidebar_animation_a_change_under_5_points_has_no_label(a0):
    sm = dict(a0, hp=86, hp_left=172000, sp=(2460, 3600))
    sa = {}
    ui.animate(sa, [a0], 0.0)
    sd, _, sbusy = ui.animate(sa, [sm], 10.0)
    assert not sbusy
    assert sd[0] is sm


def test_sidebar_animation_a_member_seen_first_has_no_label(a0):
    nb, nl, nbusy = ui.animate({}, [a0], 5.0)
    assert nb[0] is a0
    assert not nl
    assert not nbusy
    assert "hp_delta" not in nb[0]


@pytest.fixture
def flashing(a0):
    """a0 at 0 s, then done: (frame lit at 30, 30.4, 30.5, 31, 31.5, 33.5, 33.9, 34 s, busy at 30, 33.9, 34 s, state, done)."""
    fa = {}
    ui.animate(fa, [a0], 0.0)
    d0 = dict(a0, status="done")
    lit = [bool(ui.animate(fa, [d0], t)[1]) for t in (30.0, 30.4, 30.5, 31.0, 31.5, 33.5, 33.9, 34.0)]
    fc = {}
    ui.animate(fc, [a0], 0.0)
    fb = ui.animate(fc, [d0], 30.0)[2], ui.animate(fc, [d0], 33.9)[2], ui.animate(fc, [d0], 34.0)[2]
    return lit, fb, fa, d0


def test_sidebar_animation_turning_done_pulses_the_frame_for_4_s(flashing):
    lit, fb, _, _ = flashing
    assert lit == [True, True, False, True, False, False, False, False]
    assert fb == (True, True, False)


def test_sidebar_animation_no_flash_when_first_seen_done_or_leaving_to_idle(flashing, a0):
    _, _, fa, d0 = flashing
    assert not ui.animate({}, [dict(a0, status="done")], 30.0)[1]
    assert not ui.animate(fa, [dict(d0, status="idle")], 40.0)[1]


def test_sidebar_animation_turning_waiting_flashes_too(a0):
    fw = ui.animate(
        {"%1": {"last": [88, 42], "delta": [None, None], "t0": [0, 0], "status": "done", "flash": None}},
        [dict(a0, status="waiting")],
        1.0,
    )[1]
    assert fw == {"%1"}


def test_sidebar_animation_drops_a_member_that_disappeared(a0):
    gone = {}
    ui.animate(gone, [a0, dict(a0, pane="%9")], 0.0)
    ui.animate(gone, [a0], 1.0)
    assert set(gone) == {"%1"}


def test_flash_changes_only_the_frame_color(towns):
    on = render.render(towns, 33, "%2", flash={"%1", "%2"})
    off = render.render(towns, 33, "%2")
    assert on != off
    assert strip(on) == strip(off)
    assert render.render(towns, 33, "%2", flash=()) == off
    assert [common.cw(l) for l in strip(on).split("\n")] == [common.cw(l) for l in strip(off).split("\n")]


def test_flash_lights_selected_and_unselected_cards(fe):
    fl_sel = render.card(dict(fe, status="done"), 33, True, False, True)
    fl_not = render.card(dict(fe, status="done"), 33, False, False, True)
    assert fl_sel != render.card(dict(fe, status="done"), 33, True)
    assert fl_not != render.card(dict(fe, status="done"), 33, False)


@pytest.mark.parametrize("sq_art", [False, True])
def test_flash_pulses_the_squad_name_row(towns, sq_art):
    sq_on = render.render(towns, 33, "%2", flash={"%1"}, art=sq_art, focus="squad", squad=1)
    sq_off = render.render(towns, 33, "%2", art=sq_art, focus="squad", squad=1)
    sq_diff = [i for i, (x, y) in enumerate(zip(sq_on.split("\n"), sq_off.split("\n"))) if x != y]
    assert sq_diff
    assert strip(sq_on) == strip(sq_off)
    assert [common.cw(l) for l in strip(sq_on).split("\n")] == [common.cw(l) for l in strip(sq_off).split("\n")]
    assert render.render(towns, 33, "%2", flash={"%99"}, art=sq_art, focus="squad", squad=1) == sq_off


def lw(rows):
    return [common.cw(strip(r)) for r in rows]


@pytest.fixture
def tl(fe):
    return [
        dict(fe, hp_delta=40, sp_delta=-12),
        dict(fe, hp_delta=-12),
        dict(fe, summons=[1, 2], hp_delta=40, sp_delta=-12),
    ]


def test_change_labels_on_the_hp_and_sp_rows_keep_the_width(fe, tl):
    assert all("+40%" in strip(render.stat_rows(a, 29)[0]) for a in tl[:1] + tl[2:])
    assert "-12" in strip(render.stat_rows(tl[0], 29)[1])
    assert "-12%" not in strip(render.stat_rows(tl[0], 29)[1])
    assert all(lw(render.stat_rows(a, wd)) == lw(render.stat_rows(fe, wd)) for a in tl for wd in range(10, 40))


def test_change_labels_keep_the_card_width(fe, tl):
    assert all(lw(render.card(a, 33, False)) == lw(render.card(fe, 33, False)) for a in tl)
    assert all(lw(render.card(a, 33, False, True)) == lw(render.card(fe, 33, False, True)) for a in tl)


def test_change_labels_increase_green_decrease_red(fe):
    assert common.fg("green") in render.stat_rows(dict(fe, hp_delta=40), 29)[0]
    assert common.fg("red") in render.stat_rows(dict(fe, hp_delta=-40), 29)[0]
    assert common.fg("red") not in render.stat_rows(dict(fe, hp_delta=40, hp=88), 29)[0]


def test_change_labels_left_out_without_room(fe):
    assert strip(render.stat_rows(dict(fe, hp_delta=40), 12)[0]) == strip(render.stat_rows(fe, 12)[0])


def test_change_labels_take_the_model_badges_place_on_an_art_card(fe):
    op = dict(fe, model="Opus 5.5", hp=66, hp_left=131353, hp_max=200000)
    assert "+58%" in strip(render.card(dict(op, hp_delta=58), 33, False, True)[2])
    assert "Opus" not in strip(render.card(dict(op, hp_delta=58), 33, False, True)[2])
    assert "Opus" in strip(render.card(op, 33, False, True)[2])
