import os
import re
import subprocess
import sys

import pytest
from screen import has_line, strip, width, widths_ok

from party_hud import collect, common, render

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sidebar.json")
SGR = r"\033\[[0-9;:]*m"


@pytest.fixture(scope="module")
def cli():
    """party.py --fixture at width 33, the drawable width of the default 34-column sidebar: (ansi, text)."""
    out = subprocess.run(
        [sys.executable, os.path.join(ROOT, "party.py"), "--fixture", FIXTURE, "--width", "33"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out, strip(out)


@pytest.fixture(scope="module")
def sel():
    """The fixture rendered with %4 (squad Server) selected: (ansi, text)."""
    out = render.render(collect.collect(FIXTURE)["towns"], 33, "%4") + "\n"
    return out, strip(out)


@pytest.fixture
def snap():
    return collect.collect(FIXTURE)


@pytest.fixture
def towns(snap):
    return snap["towns"]


@pytest.fixture
def agents(towns):
    return [a for t in towns for a in t["agents"]]


def test_every_box_line_is_33_columns_wide(cli):
    assert widths_ok(cli[1])


def test_layout_squads_then_the_cards_of_the_viewed_squad(cli):
    assert re.search("╭─ Squads 2 .*[╭╔][─═] claude [─═].*[╭╔][─═] claude [─═]", cli[1], re.DOTALL)


def test_cards_dont_list_other_squads_members(cli):
    assert "z zzz" not in cli[1]


def test_viewed_squad_has_the_gold_bar(cli):
    assert has_line("^│▌ .* Studio", cli[1])


def test_studio_summary_and_location_pin(cli):
    assert has_line("Studio \U000f034e +!1 ⠋1 +│", cli[1])


def test_server_with_only_an_asleep_member_sums_up_as_zzz_1(cli):
    assert has_line("Server +zzz 1 │", cli[1])


def test_waiting_member_sorts_before_busy(cli):
    assert re.search("審查員.*! wait.*Frontend.*⠋ busy", cli[1], re.DOTALL)


def test_text_card_has_class_icon_name_class_and_status_on_one_line(cli):
    assert has_line("Frontend (Warrior|Merchant|Thief|Cleric|Scholar|Hunter|Apothecary|Dancer) +⠋ busy ║", cli[1])


def test_selected_card_has_a_gold_double_frame_and_the_arrow(cli):
    assert re.search("38;2;226;178;74m╔═[^╝]*❯[^╝]*Frontend", cli[0], re.DOTALL)


def test_squad_with_someone_waiting_has_an_orange_name(cli):
    assert has_line("1;38;2;240;160;80mStudio", cli[0])


def test_unselected_card_has_a_dim_thin_frame_and_dimmed_name(cli):
    assert re.search("38;2;240;160;80m╭─[^╯]*38;2;138;143;168m審查員", cli[0], re.DOTALL)


def test_hp_value_area(cli):
    assert has_line("║ .HP  176k/200k ", cli[1])


def test_sp_is_on_the_line_right_after_hp(cli):
    lines = cli[1].splitlines()
    i = next(i for i, ln in enumerate(lines) if re.search("HP  *176k/200k", ln))
    assert re.search("SP  *42/60m ", lines[i + 1])


def test_hp_row_right_side_is_the_model_base_name(cli):
    assert has_line("HP +176k/200k +. Opus ║", cli[1])


def test_sp_row_right_side_is_the_number_of_subagents(cli):
    assert has_line("SP +42/60m +.1 ║", cli[1])


def test_no_subagent_detail_lines_in_the_card(cli):
    assert "executor" not in cli[1]


def test_name_from_the_session_name_and_hp_estimated_from_the_transcript(cli):
    assert re.search("審查員.*! wait.*HP +140k/200k", cli[1], re.DOTALL)


def test_hp_88_percent_is_teal(cli):
    assert has_line(r"4m.\[58;2;126;214;168m", cli[0])


def test_select_4_gives_server_the_gold_bar(sel):
    assert has_line("^│▌ .* Server", sel[1])
    assert not has_line("^│▌ .* Studio", sel[1])


def test_select_4_shows_only_servers_card(sel):
    assert sum(bool(re.search("^[╭╔][─═] claude [─═]", ln)) for ln in sel[1].splitlines()) == 1


def test_select_4_lists_no_studio_members(sel):
    assert "審查員" not in sel[1]


def test_idle_with_expired_cache_is_asleep_with_hp_from_the_transcript(sel):
    assert re.search("一個很.*z zzz.*HP +50k/200k +║.*SP +0/60m +║", sel[1], re.DOTALL)


def test_hp_25_percent_is_yellow(sel):
    assert re.search("58;2;226;178;74m.*1;38;2;226;178;74m5", sel[0], re.DOTALL)


def test_viewed_squad_gold_name_and_unviewed_waiting_squad_orange_mark(sel):
    assert re.search("38;2;240;160;80m!.*Studio.*38;2;226;178;74mServer", sel[0], re.DOTALL)


def test_select_4_every_box_line_is_33_wide(sel):
    assert widths_ok(sel[1])


def test_empty_squad_selected_every_box_line_is_33_wide(towns):
    e = [*towns, dict(towns[1], name="Empty", agents=[])]
    assert widths_ok(strip(render.render(e, 33, "%1", focus="squad", squad=2) + "\n"))


def test_sidebar_pane_is_not_a_squad_member(snap, agents):
    assert snap["panes"]["%9"]["window_panes"] == 0
    assert "%9" not in [a["pane"] for a in agents]


def test_peek_replaces_the_status_box(towns):
    peek = strip(render.render(towns, 33, "%1", ["line1", "", "最後一行", "", ""], "sidebar"))
    assert "Peek · Frontend" in peek
    assert "最後一行" in peek
    assert "│ HP" not in peek


def test_sidebar_key_hints_are_in_english(towns):
    hint = strip(render.render(towns, 34, "%1", None, "sidebar")).splitlines()[-1]
    assert "? keys" in hint
    assert "q hide" in hint
    assert not re.search(r"[一-鿿]", hint)


def test_selected_squad_row_gets_the_warm_gold_background(towns):
    rows = render.render(towns, 33, "%1", focus="squad", squad=1).splitlines()
    assert any(common.bg("view") in ln and "Server" in ln for ln in rows)


@pytest.fixture
def tall(towns):
    return strip(render.render(towns, 33, "%1", [f"L{i}" for i in range(100)], "sidebar", 40)).splitlines()


def test_peek_fills_the_remaining_height(tall):
    assert len(tall) == 40
    assert any("L99" in ln for ln in tall)
    assert sum(ln.startswith("│L") for ln in tall) > 12


def test_peek_keeps_the_key_hints_on_the_last_line(tall):
    assert len(tall) == 40
    assert "q hide" in tall[-1]


def test_key_hints_are_pinned_to_the_last_line(towns):
    low = strip(render.render(towns, 33, "%1", None, "sidebar", 40)).splitlines()
    assert len(low) == 40
    assert "q hide" in low[-1]


def test_squad_without_agents_says_empty_with_one_info_card(towns):
    empty = [*towns, dict(towns[1], name="Empty", agents=[])]
    eq = strip(render.render(empty, 33, "%1", focus="squad", squad=2))
    assert re.search(r"Empty +\(empty\) │", eq)
    assert "no agents ⏎ open session" in eq
    assert "╭─ claude" not in eq


@pytest.fixture
def e3(towns):
    return [*towns, *(dict(towns[1], name=f"E{k}", agents=[]) for k in range(4)), towns[0]]


@pytest.mark.parametrize("art_on", [False, True])
def test_consecutive_empty_squads_collapse_into_one_row(e3, art_on):
    ec = strip(render.render(e3, 33, "%1", art=art_on)).splitlines()
    ecur = strip(render.render(e3, 33, "%1", focus="squad", squad=3, art=art_on)).splitlines()
    assert sum("+4 empty" in ln for ln in ec) == 1
    assert not any("E0" in ln or "(empty)" in ln for ln in ec)
    assert all(width(ln) == 33 for ln in ec if ln[:1] in "╭│╰")
    assert sum("+1 empty" in ln for ln in ecur) == 0
    assert sum("+" in ln and "empty" in ln for ln in ecur) == 1
    assert "+2 empty" in "".join(ecur)
    assert "".join(ecur).count("(empty)") == 2
    assert "E0" in "".join(ecur)


@pytest.mark.parametrize("art_on", [False, True])
def test_the_viewed_squad_is_not_folded(e3, art_on):
    ev = strip(render.render(e3[2:5] + e3[:1], 33, "%zz", art=art_on))
    assert "+2 empty" in ev
    assert "+3 empty" not in ev
    assert "E0" in ev
    assert "no agents" in ev


@pytest.mark.parametrize("art_on", [False, True])
def test_a_single_empty_squad_is_never_folded(e3, art_on):
    e1 = strip(render.render(e3[:3] + e3[-1:], 33, "%1", art=art_on)).splitlines()
    assert "E0" in "".join(e1)
    assert "(empty)" in "".join(e1)
    assert "+1 empty" not in "".join(e1)


def test_no_sp_data_drops_the_sp_row(agents):
    no_sp = [re.sub(SGR, "", ln) for ln in render.card({**agents[0], "sp": None, "fresh": False}, 33, True)]
    assert len(no_sp) == 4
    assert not any("SP" in ln for ln in no_sp)
    assert any("HP" in ln for ln in no_sp)
    assert all(width(ln) == 33 for ln in no_sp)


def test_art_card_without_sp_is_as_tall_as_the_portrait(agents):
    no_sp = [re.sub(SGR, "", ln) for ln in render.card({**agents[0], "sp": None, "fresh": False}, 33, False, True)]
    assert len(no_sp) == render.PORTRAIT_CELLS[1] + 2
    assert not any("SP" in ln for ln in no_sp)
    assert all(width(ln) == 33 for ln in no_sp)


def test_clicking_a_row_of_a_status_box_selects_that_member(towns):
    rm3 = []
    st3 = strip(render.render(towns, 33, "%1", row_map=rm3)).splitlines()
    assert all(rm3[i] == ("agent", "%2") for i, ln in enumerate(st3) if "Thief" in ln or "140k" in ln)


def test_sp_is_cache_minutes_left():
    assert render.sp_points({"sp": (10.0, 300)}) == 1
    assert render.sp_points({"sp": (3600.0, 3600)}) == 60
    assert render.sp_points({"sp": None}) is None


@pytest.fixture
def art_page(towns):
    """The fixture rendered with art at width 33: (stripped rows, row map)."""
    arm = []
    return strip(render.render(towns, 33, "%1", row_map=arm, art=True)).splitlines(), arm


def test_art_every_box_line_is_33_wide(art_page):
    assert all(width(ln) == 33 for ln in art_page[0] if ln[:1] in "╭│╰")


def test_art_two_rows_per_squad(art_page):
    aw = "\n".join(art_page[0])
    assert re.search("Studio +!1 ⠋1 │\n│▌\U0010eeee.{8}\U0010eeee.{2} 2 members · 1 waiting +\U000f034e │", aw)
    assert re.search(r"Server +zzz 1 │\n│ \U0010eeee.{8}\U0010eeee.{2} 1 member · 1 asleep +│", aw)


def test_squad_summary_counts_idle_members_between_done_and_asleep():
    assert strip(render.squad_summary([{"status": s} for s in ("sleep", "idle", "idle", "done")])[0]) == "✓1 ·2 zzz 1"


def test_viewed_squad_rows_are_warm_gold_and_own_squad_gets_the_pin(towns):
    hr = render.render(towns, 33, "%4", art=True, here="Studio").splitlines()
    tinted = [strip(ln) for ln in hr if common.bg("view") in ln]
    assert len(tinted) == 2
    assert "Server" in tinted[0]
    assert "member" in tinted[1]
    assert all(t.startswith("│▌") for t in tinted)
    assert any("Studio" in strip(ln) for ln in hr)
    assert sum(render.PIN_ICON in strip(ln) for ln in hr) == 1
    assert render.PIN_ICON in strip(hr[hr.index(next(ln for ln in hr if "Studio" in strip(ln))) + 1])


def test_art_both_squad_rows_map_to_that_squad(art_page):
    arm = art_page[1]
    assert sum(1 for t in arm if t == ("squad", 0)) == 2
    assert sum(1 for t in arm if t == ("squad", 1)) == 2


def test_art_card_is_a_3_row_portrait(art_page, agents):
    aw = art_page[0]
    fr = next(i for i, ln in enumerate(aw) if "Frontend" in ln)
    icon = common.class_icon(next(a for a in agents if a["pane"] == "%1"))
    assert aw[fr].startswith("║❯")
    assert re.search(f"{icon} Frontend +⠋ busy ║", aw[fr])
    assert re.search(f"\U0010eeee.{{2}} {render.HP_ICON}HP  176k/200k +{render.MODEL_ICON} Opus ║", aw[fr + 1])
    assert re.search(f"SP +42/60m +{common.SUMMON_ICON}1 ║", aw[fr + 2])
    assert aw[fr + 3].startswith("╚")
    assert aw[fr - 1].startswith("╔═ claude")


def test_model_badge():
    assert render.model_badge({"model": "Opus 5.5"}, 7) == render.MODEL_ICON + " Opus"
    assert render.model_badge({"model": "Sonnet 5.5"}, 7) == "Sonnet"
    assert render.model_badge({}, 7) == ""


NAR = {"hp": 100, "hp_left": 1_000_000, "hp_max": 1_000_000, "model": "Opus 5.5", "sp": None}
NAR2 = dict(NAR, hp_left=890_000, hp_max=1_200_000)


def hp_row(a, cols):
    return re.sub(SGR, "", render.stat_rows(a, cols)[0])


def test_narrow_sidebar_keeps_the_hp_value_whole_and_the_badge_yields():
    n31, n30 = hp_row(NAR, 20), hp_row(NAR, 19)
    assert n31.endswith(f"HP     1M/1M {render.MODEL_ICON} Opus")
    assert n30.endswith(f"HP    1M/1M {render.MODEL_ICON} Opus")
    assert common.cw(n30) == 19
    assert hp_row(NAR2, 19).endswith("HP 890k/1.2M  Opus")


def test_narrow_sidebar_drops_the_badge_before_cutting_the_value():
    n17, n13 = hp_row(NAR2, 17), hp_row(NAR2, 11)
    assert n17.rstrip().endswith("HP 890k/1.2M")
    assert "Op" not in n17
    assert common.cw(n17) == 17
    assert n13.endswith("890k")
    assert "/" not in n13
    assert common.cw(n13) == 11


def test_narrow_art_card_truncates_the_name_and_keeps_the_hp_value():
    long_a = dict(NAR2, name="party-hud-long-name", cls=0, kind="claude", status="working", sp=(600.0, 3600))
    nc = [re.sub(SGR, "", ln) for ln in render.card(long_a, 28, True, True)]
    assert all(width(ln) == 28 for ln in nc)
    assert "890k/1.2M" in nc[2]
    assert "…" in nc[1]
    assert "party-hud-long-name" not in nc[1]


def test_ui_text_is_all_english(towns, agents):
    done = dict(agents[0], status="done", hp_left=410000, hp_max=1000000)
    text = (
        render.render(towns, 33, "%1", hints="sidebar")
        + render.render(towns, 33, "%1", art=True)
        + render.render(towns, 33, "%1", ["x"], "sidebar")
    )
    en_lv = {
        "live": True,
        "text": "",
        "start": 1000,
        "end": None,
        "tool": "Bash: ls",
        "said": "thinking",
        "prev": {"text": "## Earlier\nold report", "start": 1, "end": 2},
        "task": {"ask": "do it", "files": [], "cmds": 2, "agents": 0, "dir": "~/x", "branch": "main", "cwd": "/x"},
    }
    en_rep = {"text": "## Result\nall done", "start": 100, "end": 860}
    en_sub = {"type": "executor", "desc": "Execute ticket 001", "text": "## Result\nsub said hi"}
    en_busy = dict(done, summons=[{"type": "executor", "desc": "Branch"}, {"type": "executor", "desc": "Branch 2"}])
    one_summon = [{"type": "executor", "desc": "Branch"}]
    en_pages = [
        render.render_report(dict(done, status="working"), "Studio", en_lv, [], 60, now=1723),
        render.render_report(dict(done, status="working", summons=one_summon), "Studio", en_lv, [], 60, now=1723),
        render.render_report(en_busy, "Studio", dict(en_rep, subagents=[en_sub]), [], 60),
        render.render_report(en_busy, "Studio", en_rep, [], 60, art=True, banner=(40, 5)),
        render.render_report(
            dict(done, status="working", summons=one_summon),
            "Studio",
            en_lv,
            [],
            150,
            art=True,
            banner=(118, 15),
            portrait=(24, 14),
            now=1723,
        ),
        render.render_report(en_busy, "Studio", en_rep, [], 150, art=True, banner=(118, 15), portrait=(24, 14)),
    ]
    text += "".join(en_pages)
    names = [t["name"] for t in towns] + [a["name"] for a in agents]
    for nm in names + [s["desc"] for a in agents for s in a.get("summons", [])]:
        text = text.replace(nm, "")
    assert not re.search(r"[一-鿿＀-￯]", text)


LOW = {"hp": 8, "hp_left": 16000, "hp_max": 200000, "sp": None, "fresh": False}


def test_hp_at_10_percent_or_less_blinks_red(monkeypatch):
    red, dim = "\x1b[1;38;2;208;96;90m", "\x1b[1;38;2;138;143;168m"
    monkeypatch.setattr(render, "_tick", 0)
    on = render.stat_rows(LOW, 22)[0]
    monkeypatch.setattr(render, "_tick", 1)
    off = render.stat_rows(LOW, 22)[0]
    monkeypatch.setattr(render, "_tick", 0)
    mid = render.stat_rows(dict(LOW, hp=30, hp_left=60000), 22)[0]
    assert red in on
    assert red not in off
    assert dim in off
    assert "\x1b[1;38;2;226;178;74m" in mid
    assert red not in mid


def test_hp_and_sp_rows_are_exact_width():
    for a in (LOW, {"hp": None, "sp": None}, {"hp": 100, "sp": None, "fresh": True}):
        assert all(len(strip(r)) == 22 for r in render.stat_rows(a, 22))


def test_value_row_label_left_value_right_underline_in_bar_color():
    mr = render.meter_row("HP", "hp", "124k", "fg", "/200k", 50, "hp", 22)
    assert strip(mr) == "HP" + " " * 11 + "124k/200k"
    assert mr.count(render.ul("hp")) == 11
    assert mr.count(render.ul("line")) == 11


def test_unknown_value_underline_is_all_dim():
    assert render.meter_row("SP", "sp", "--", "fg", "", None, "dim", 22).count(render.ul("line")) == 22


def test_squad_with_unseen_done_member_says_n_done(towns):
    dt = [dict(towns[1], agents=[dict(towns[1]["agents"][0], status="done")])]
    dw = strip(render.render(dt, 33, None, art=True))
    assert render.squad_alert(dt[0]["agents"]) == "done"
    assert re.search(r"1 member · 1 done", dw)


def test_crew_done_leaves_the_squad_dark():
    lead_idle = {"pane": "%1", "status": "idle"}
    crew_done = {"pane": "%2", "status": "done", "lead": "%1"}
    solo_done = {"pane": "%3", "status": "done"}
    crew_wait = {"pane": "%4", "status": "waiting", "lead": "%1"}
    assert render.squad_alert([lead_idle, crew_done]) is None
    assert render.squad_alert([lead_idle, crew_done, crew_wait]) == "waiting"
    assert render.squad_alert([lead_idle, crew_done, solo_done]) == "done"


def test_sidebar_too_narrow_falls_back_to_text(towns):
    assert "\U0010eeee" not in render.render(towns, 29, "%1", art=True)


@pytest.fixture
def mouse(towns):
    rm = []
    return strip(render.render(towns, 33, "%1", row_map=rm)).splitlines(), rm


def test_mouse_row_map_is_no_longer_than_the_screen(mouse):
    lines, rm = mouse
    assert len(rm) <= len(lines)


def test_mouse_rows_map_to_member_or_squad(mouse):
    lines, rm = mouse
    assert all(rm[i] == ("agent", "%2") for i, ln in enumerate(lines) if "審查員" in ln)
    assert all(rm[i] == ("agent", "%1") for i, ln in enumerate(lines) if "Frontend" in ln)
    assert all(rm[i] == ("squad", 1) for i, ln in enumerate(lines) if "Server" in ln)


@pytest.fixture
def many_members(towns, agents):
    """40 members in one squad at 33x24 with %130 selected: (rows, row map)."""
    many = [dict(towns[0], agents=[dict(agents[0], pane=f"%{i}", summons=[]) for i in range(100, 140)])]
    rm2 = []
    return strip(render.render(many, 33, "%130", None, "sidebar", 24, rm2)).splitlines(), rm2


def test_too_many_members_fit_the_height_and_keep_the_selected_one(many_members):
    short, rm2 = many_members
    assert len(short) <= 24
    assert len(rm2) <= len(short)
    assert ("agent", "%130") in rm2


def test_cards_that_dont_fit_show_more_above_and_below(many_members):
    short, rm2 = many_members
    up = next((ln for ln in short if "▲" in ln), "")
    down = next((ln for ln in short if "▼" in ln), "")
    shown = len({p for p in rm2 if p and p[0] == "agent"})
    assert re.fullmatch(r" *▲ \d+ more *", up)
    assert re.fullmatch(r" *▼ \d+ more *", down)
    assert int(up.split()[1]) + int(down.split()[1]) + shown == 40


def test_everything_fits_no_more_hints(mouse):
    assert not any("more" in ln for ln in mouse[0])


@pytest.fixture
def crowd(towns, agents):
    """12 squads of 2 members, %200 + 2k and %201 + 2k in squad k."""
    return [
        dict(
            towns[0],
            name=f"Sq{k}",
            agents=[dict(agents[0], pane=f"%{200 + 2 * k + j}", summons=[], focus=False) for j in range(2)],
        )
        for k in range(12)
    ]


@pytest.mark.parametrize("use_art", [True, False])
@pytest.mark.parametrize(("k", "pane"), [(0, "%200"), (11, "%222")])
def test_12_squads_at_33x24_keep_the_selected_card_and_the_hint_row(crowd, use_art, k, pane):
    cm = []
    cl = strip(render.render(crowd, 33, pane, None, "sidebar", 24, cm, art=use_art)).splitlines()
    assert len(cl) == 24
    assert cl[-1].lstrip().startswith("⏎")
    assert sum(ln.startswith("╔") for ln in cl) == 1
    assert any(ln.startswith("║❯") for ln in cl)
    assert any(ln.startswith("╚") for ln in cl)
    assert ("agent", pane) in cm
    assert ("squad", k) in cm


def squads_page(crowd, pane):
    cm = []
    cl = strip(render.render(crowd, 33, pane, None, "sidebar", 24, cm, art=True)).splitlines()
    return cl, cm


def test_squads_dont_fit_last_squad_viewed_shows_more_above(crowd):
    cl, cm = squads_page(crowd, "%222")
    box_end = next(i for i, ln in enumerate(cl) if ln.startswith("╰"))
    shown = {p[1] for p in cm if p and p[0] == "squad"}
    assert re.fullmatch(r"│ *▲ \d+ more *│", cl[1])
    assert int(cl[1].strip("│ ").split()[1]) == 12 - len(shown)
    assert 11 in shown
    assert 0 not in shown
    assert not any("▼" in ln for ln in cl[:box_end])


def test_squads_dont_fit_the_more_row_maps_to_none(crowd):
    box_end = next(i for i, ln in enumerate(squads_page(crowd, "%222")[0]) if ln.startswith("╰"))
    cl, cm = squads_page(crowd, "%200")
    assert cm[0] is None
    assert cm[1] == ("squad", 0)
    assert cm[box_end - 1] is None
    assert cm[box_end] is None
    assert "▼" in cl[box_end - 1]
    assert all(cm[i] == ("squad", (i - 1) // 2) for i in range(1, box_end - 1))
    assert int(cl[box_end - 1].strip("│ ").split()[1]) == 12 - len({p[1] for p in cm if p and p[0] == "squad"})


def test_squads_all_fit_no_more_rows(crowd):
    cl, cm = squads_page(crowd[:3], "%200")
    assert not any("more" in ln for ln in cl)
    assert cl[0].startswith("╭─ Squads 3")
    assert cl[7].startswith("╰")
    assert cm[:8] == [None, *[("squad", k // 2) for k in range(6)], None]


def test_squad_focus_gold_bar_and_no_selected_card(towns):
    sq = strip(render.render(towns, 33, "%1", focus="squad", squad=1)).splitlines()
    assert any(ln.startswith("│▌") and "Server" in ln for ln in sq)
    assert not any(ln.startswith("╔") for ln in sq)


def test_squad_list_taller_than_the_pane_cuts_the_row_map(towns):
    many = [dict(towns[0], name=f"s{i}") for i in range(12)]
    rm = []
    tall = render.render(many, 33, "%1", height=24, hints="sidebar", row_map=rm, art=True)
    assert len(tall.split("\n")) == 24
    assert len(rm) == 23
