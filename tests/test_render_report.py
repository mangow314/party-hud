import os
import re

import pytest
from screen import strip

from party_hud import art, collect, common, markdown, render, ui

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "sidebar.json")
agents = [a for t in collect.collect(FIXTURE)["towns"] for a in t["agents"]]
done = dict(agents[0], status="done", hp_left=410000, hp_max=1000000)
rep = {"text": "## 結果\n完成了報告畫面\n" + "很長的一行中文" * 20, "start": 100, "end": 860}
sub = {"type": "executor", "desc": "Execute ticket 001", "text": "## 子結果\nsubagent said hi"}
busy = dict(done, summons=[{"type": "executor", "desc": "Branch 還在跑" * 8}])
task_l = {
    "ask": "q",
    "files": ["/w/a.py", "/w/b.py"],
    "cmds": 1,
    "agents": 0,
    "dir": "~/x",
    "branch": "main",
    "cwd": "/w",
}
many = {
    "ask": "q",
    "files": [f"/w/party_hud/f{n}.py" for n in range(8)] + ["/w/party_hud/" + "x" * 40 + ".py"],
    "cmds": 0,
    "agents": 3,
    "cwd": "/w",
}


def mk(pane, status):
    return {"pane": pane, "status": status}


bid_, pid_, big_ = art.banner_id("done", True, False), art.portrait_id(done), art.big_portrait_id(done)


@pytest.fixture
def frame():
    frame = render.render_report(done, "Studio", rep, [], 60)
    rf = strip(frame).splitlines()
    return frame, rf


def test_title_who_squad_and_key_hints(frame):
    frame, rf = frame
    assert "Quest complete" in rf[0]
    assert f"{done['name']}  claude · Studio" in rf[1]
    assert "q close" in rf[-1]
    assert "scroll" not in rf[-1]


def test_time_from_prompt_to_answer_and_hp_left(frame):
    _, rf = frame
    assert "took 12m 40s" in rf[2]
    assert "HP 410k/1M" in rf[2]


def test_no_row_is_wider_than_the_width(frame):
    _, rf = frame
    assert all(common.cw(l) <= 60 for l in rf)
    assert sum(common.cw(l) == 60 for l in rf) >= 1


def test_text_goes_through_render_markdown(frame):
    frame, _ = frame
    assert common.fg("gold", True) + "結果" in frame
    assert "## " not in strip(frame)


def test_a_report_taller_than_any_pane_is_printed_in_full():
    long = dict(rep, text="\n".join(f"L{n}" for n in range(50)))
    lf = strip(render.render_report(done, "Studio", long, [], 60)).splitlines()
    assert all(f"L{n}" in lf for n in range(50))


@pytest.fixture
def art_page():
    ar = render.render_report(done, "Studio", rep, [], 60, art=True).splitlines()
    pid = art.portrait_id(done)
    return ar, pid


def test_with_art_the_portrait_stands_left_of_the_first_rows(frame, art_page):
    frame, _ = frame
    ar, pid = art_page
    assert all(ar[10 + r].startswith(art.image_row(pid, r, art.PORTRAIT_CELLS[0])) for r in range(3))
    assert chr(1109742) not in frame
    assert all(common.cw(strip(l)) <= 60 for l in ar)


def test_with_art_the_banner_opens_the_page(frame, art_page):
    frame, _ = frame
    ar, pid = art_page
    bn = art.banner_id("done", True, False)
    assert ar[0] == art.image_row(bn, 0, 60)
    assert ar[9] == art.image_row(bn, 9, 60)
    assert ar[10].startswith(art.image_row(pid, 0, 6))
    assert "Quest complete" not in strip("\n".join(ar))
    assert "Quest complete" in strip(frame)
    assert [
        art.banner_id(s, r, m) - art.BANNER_ID
        for s, r, m in (
            ("done", True, False),
            ("waiting", True, False),
            ("working", True, False),
            ("done", False, False),
            ("done", True, True),
            ("waiting", False, False),
            ("waiting", True, True),
        )
    ] == [0, 1, 2, 3, 2, 1, 1]


def test_no_report_shows_the_panes_last_lines():
    last = strip(render.render_report(dict(done, status="waiting"), "Studio", None, ["$ make", "ok", "", ""], 60))
    assert "Last output" in last
    assert "$ make" in last
    assert "took" not in last


def test_nothing_at_all_says_so():
    assert "no report yet" in strip(render.render_report(done, "Studio", None, [], 60))


@pytest.fixture
def live_page():
    lv = {
        "live": True,
        "text": "",
        "start": 1000,
        "end": None,
        "tool": "Bash: rg -n 很長的指令" * 6,
        "said": "第一行\n" + "很長的一行中文" * 20 + "\nlast words",
        "prev": {"text": "## 上輪\n舊報告", "start": 1, "end": 2},
        "task": {"ask": "做事", "files": [], "cmds": 2, "agents": 0, "dir": "~/x", "branch": "main", "cwd": "/x"},
    }
    lf = strip(render.render_report(dict(done, status="working"), "Studio", lv, [], 60, now=1000 + 723)).splitlines()
    return lf


def test_live_report_status_row_now_block_and_previous_report(live_page):
    lf = live_page
    assert "Working · 12m 03s" in lf
    assert "Now" in lf
    assert "last words" in " ".join(lf)
    assert "Previous report" in lf
    assert "舊報告" in " ".join(lf)


def test_live_report_no_row_is_wider_than_the_width(live_page):
    lf = live_page
    assert all(common.cw(l) <= 60 for l in lf)


def test_last_output_continuation_row_keeps_the_prefix():
    pr = [strip(r) for r in render.report_rows(None, ["  │ " + "ab " * 20], [], 30)]
    assert len(pr) > 1
    assert all(r.startswith("  │ ") for r in pr)
    assert all(common.cw(r) <= 30 for r in pr)
    assert "".join(r[4:] for r in pr) == ("ab " * 20).rstrip()


def test_last_output_no_prefix_without_room_for_a_wide_character():
    pn = [strip(r) for r in render.report_rows(None, [" 你你你"], [], 2)]
    assert all(common.cw(r) <= 2 for r in pn)
    assert "".join(pn).replace(" ", "") == "你你你"


def test_last_output_continuation_prefix_with_cjk():
    pc = [strip(r) for r in render.report_rows(None, ["│ " + "你好" * 20], [], 21)]
    assert len(pc) > 1
    assert all(r.startswith("│ ") for r in pc)
    assert all(common.cw(r) <= 21 for r in pc)
    assert "".join(r[2:] for r in pc) == "你好" * 20


def test_last_output_no_prefix_over_half_the_width():
    assert [strip(r) for r in render.report_rows(None, [" " * 20 + "abc" * 10], [], 30)] == [
        " " * 20 + "abcabcabca",
        "bcabcabcabcabcabcabc",
    ]


def test_last_output_row_without_prefix_gets_none():
    assert [strip(r) for r in render.report_rows(None, ["x" * 50], [], 20)] == ["x" * 20, "x" * 20, "x" * 10]


def test_branch_task_still_running_replaces_quest_complete():
    bf = strip(render.render_report(busy, "Studio", dict(rep, subagents=[sub]), [], 60))
    assert "Quest complete" not in bf
    assert "1 subagent still running" in bf.splitlines()[0]
    assert "running" in bf.split("\n\n", 1)[1]
    assert all(common.cw(l) <= 60 for l in bf.splitlines())


def test_art_and_a_running_branch_task():
    bart = render.render_report(busy, "Studio", rep, [], 60, art=True, banner=(40, 5)).splitlines()
    assert len(bart) > 5
    assert bart[0] == art.image_row(art.banner_id("done", True, True), 0, 40)
    assert "1 subagent still running" in strip(bart[5])
    assert all(common.cw(strip(l)) <= 60 for l in bart)


@pytest.fixture
def wide():
    wide = render.render_report(
        done, "Studio", rep, [], 150, 2, 3, art=True, banner=(118, 15), portrait=(24, 14)
    ).splitlines()
    wl = [strip(l) for l in wide]
    bot = next(i for i, l in enumerate(wl) if l.startswith("┗"))
    return wide, wl, bot


def test_split_page_rows_open_with_the_side_frame(wide):
    _, wl, bot = wide
    cjk_row = next(ln for ln in wl if "結果" in ln)
    assert all(common.cw(ln) <= 150 for ln in wl)
    assert all(ln[0] in "┏┃┗" for ln in wl[: bot + 1])
    assert all(ln.startswith(" " * 30) for ln in wl[bot + 1 :])
    assert common.cw(cjk_row[: cjk_row.index("結果")]) == 32


@pytest.fixture
def body_page():
    bodyw = dict(rep, text="很長的一行中文" * 30 + "\n```\n" + "x" * 150 + "\n```", subagents=[])
    bwl = [
        strip(l)
        for l in render.render_report(
            done, "Studio", bodyw, [], 150, art=True, banner=(60, 8), portrait=(24, 14)
        ).splitlines()
    ]
    return bodyw, bwl


def test_split_page_prose_wraps_at_the_banner_width(body_page):
    _, bwl = body_page
    prose = [l.rpartition("┃")[2][2:].rstrip() for l in bwl if "中文" in l]
    assert len(prose) > 3
    assert all(common.cw(l) <= 60 for l in prose)
    assert max(common.cw(l) for l in prose) >= 58


def test_split_page_fenced_code_fills_the_right_column(body_page):
    _, bwl = body_page
    assert max(len(l.rpartition("┃")[2][2:].rstrip()) for l in bwl if "xxx" in l) == 118


def test_narrow_page_keeps_the_pane_width_for_prose(body_page):
    bodyw, _ = body_page
    nar = [strip(l) for l in render.render_report(done, "Studio", bodyw, [], 99, art=True, banner=(40, 5)).splitlines()]
    assert max(common.cw(l) for l in nar if "中文" in l) >= 90


@pytest.fixture
def side():
    return render.report_side_rows(done, "Studio", rep, 2, 3, (24, 14))


def test_side_column_rows_are_30_wide(side):
    assert all(common.cw(strip(r)) == 30 for r in side)
    assert strip(side[-1]).startswith("┗")
    assert art.image_row(art.big_portrait_id(done), 13, 24) in side[14]
    assert any("TOOK" in r for r in side)
    assert any("12m 40s" in r for r in side)


@pytest.fixture
def took(side):
    side_t = render.report_side_rows(done, "Studio", dict(rep, task=task_l), 1, 1, (24, 14), now=860 + 3725)
    took_row = next(r for r in side if "TOOK" in strip(r))
    return side_t, took_row


def test_side_column_took_label_left_value_right(took):
    _, took_row = took
    assert strip(took_row).strip("┃ ").startswith("TOOK")
    assert strip(took_row).strip("┃ ").endswith("12m 40s")
    assert common.cw(strip(took_row)) == 30


def test_headings_are_bold_text_in_their_own_colors(took):
    side_t, took_row = took
    assert took_row.count(common.fg("code", True) + "TOOK") == 1
    assert common.fg("fg", True) + "12m 40s" in took_row
    assert common.fg("gold", True) + "TOOK" not in took_row
    assert all(
        (
            common.fg(c, True) + n in "\n".join(side_t)
            for n, c in (("WAITED", "amber"), ("ASKED", "gold"), ("FILES", "green"), ("WHERE", "violet"))
        )
    )


@pytest.fixture
def side_l():
    side_l = render.report_side_rows(
        done, "Studio", dict(rep, task=task_l), 1, 1, (24, 14), now=860 + 3725, labels=True
    )
    return side_l


def test_label_images_replace_the_heading_text(side_l):
    lab_row = lambda r, n: next(x for x in side_l if art.image_row(art.label_id(n), 0, art.LABEL_COLS[n]) in x)
    assert all(
        common.cw(strip(lab_row(0, n))) == 30 and strip(lab_row(0, n)).count(chr(1109742)) == art.LABEL_COLS[n]
        for n in ("took", "waited", "asked", "files", "where")
    )
    assert "TOOK" not in strip("\n".join(side_l))
    assert strip(lab_row(0, "took")).strip("┃ ").endswith("12m 40s")
    assert not any(
        art.image_row(art.label_id(n), 0, art.LABEL_COLS[n]) in "\n".join(side_l) for n in ("work", "running")
    )


def test_working_member_has_a_running_row():
    live_s = dict(rep, live=True, end=None, task=task_l)
    run_l = render.report_side_rows(
        dict(done, status="working"), "Studio", live_s, 1, 1, (24, 14), now=100 + 723, labels=True
    )
    run_t = [
        strip(r)
        for r in render.report_side_rows(dict(done, status="working"), "Studio", live_s, 1, 1, (24, 14), now=100 + 723)
    ]
    assert any(
        art.image_row(art.label_id("running"), 0, 11) in r
        and strip(r).strip("┃ ").endswith("12m 03s")
        and (common.cw(strip(r)) == 30)
        for r in run_l
    )
    assert not any(art.image_row(art.label_id(n), 0, art.LABEL_COLS[n]) in r for r in run_l for n in ("took", "waited"))
    assert any(r.strip("┃ ").startswith("RUNNING") and r.strip("┃ ").endswith("12m 03s") for r in run_t)
    assert not any("TOOK" in r for r in run_t)


def test_waiting_member_waited_row_gets_an_orange_band(side_l):
    wait_l = render.report_side_rows(
        dict(done, status="waiting"), "Studio", rep, 1, 1, (24, 14), now=860 + 3725, labels=True
    )
    w_row = next(r for r in wait_l if art.image_row(art.label_id("waited"), 0, 10) in r)
    assert strip(w_row).startswith("┃ !")
    assert common.cw(strip(w_row)) == 30
    assert "48;2;" in w_row
    assert not any("48;2;" in r for r in wait_l if r != w_row)
    assert not strip(next(r for r in side_l if art.image_row(art.label_id("waited"), 0, 10) in r)).startswith("┃ !")


def test_side_frame_color_follows_the_status():
    frames = {
        s_: render.report_side_rows(dict(done, status=s_), "Studio", rep, 1, 1, (24, 14))[0]
        for s_ in ("done", "waiting", "working", "idle")
    }
    assert [
        common.fg(c, True) in frames[s_]
        for s_, c in (("done", "gold"), ("waiting", "warn"), ("working", "sp"), ("idle", "blue"))
    ] == [True] * 4
    assert common.fg("line") not in "".join(frames.values())


def test_side_frame_is_thick_lines_in_bold():
    hv = render.report_side_rows(done, "Studio", rep, 1, 1, (24, 14))
    hb = common.fg("gold", True)
    assert hv[0] == hb + "┏" + "━" * 28 + "┓" + common.RESET
    assert hv[-1] == hb + "┗" + "━" * 28 + "┛" + common.RESET
    assert all(r.startswith(hb + "┃" + common.RESET) and r.endswith(hb + "┃" + common.RESET) for r in hv[1:-1])


def test_member_cards_keep_their_own_frames():
    assert not any(c in "".join(render.card(agents[0], 33, False)) for c in "┏━┓┃┗┛")
    assert not any(c in "".join(render.card(agents[0], 33, True)) for c in "┏━┓┃┗┛")


def test_side_column_shows_a_status_tag(side):
    tag_done = next(r for r in side if "Complete" in strip(r))
    tag_wait = next(
        r
        for r in render.report_side_rows(dict(done, status="waiting"), "Studio", rep, 1, 1, (24, 14))
        if "Waiting" in strip(r)
    )
    assert "✓ Complete" in strip(tag_done)
    assert common.fg("green") in tag_done
    assert "! Waiting" in strip(tag_wait)
    assert common.fg("warn") in tag_wait


def test_split_page_key_hints_on_the_frames_last_row(wide):
    wide, wl, bot = wide
    hint_rows = [i for i, l in enumerate(wl) if "⏎ go" in l]
    assert hint_rows == [bot - 1]
    assert wl[bot - 1].startswith("┃")
    assert "⏎ go" in wl[bot - 1][:30]


def test_banner_opens_the_right_column_on_the_portrait_top_row(wide):
    wide, wl, _ = wide
    assert wl[0].rstrip() == "┏" + "━" * 28 + "┓"
    assert wide[1].endswith(art.image_row(art.banner_id("done", True, False), 0, 118))


def test_split_page_without_time_or_hp():
    thin = dict(rep, text="一行")
    sw = [
        strip(l)
        for l in render.render_report(
            dict(done, hp=None, hp_left=None),
            "Studio",
            dict(thin, start=None),
            [],
            150,
            art=True,
            banner=(118, 15),
            portrait=(24, 14),
        ).splitlines()
    ]
    lw = [
        strip(l)
        for l in render.render_report(
            done,
            "Studio",
            dict(rep, text="\n".join(f"L{n}" for n in range(60))),
            [],
            150,
            art=True,
            banner=(118, 15),
            portrait=(24, 14),
        ).splitlines()
    ]
    assert "TOOK" not in "\n".join(sw)
    assert "HP" not in "\n".join(sw)
    assert all(l.startswith(("┏", "┃", "┗", " " * 30)) for l in sw)
    assert any("⏎ go" in l for l in sw)
    assert sum(l.startswith("┗") for l in sw) == 1
    assert sum(l.startswith("┗") for l in lw) == 1
    assert lw[-1].startswith("┗")
    assert "L59" in lw[-3]


def test_side_column_shows_prompt_counts_directory_branch_and_wait():
    task = {
        "ask": "請幫我把報告頁左欄改成任務資訊\n" + "很長的提問" * 20,
        "files": ["/w/a.py", "/w/b.py", "/w/c.py", "/w/d.py", "/w/e.py"],
        "cmds": 12,
        "agents": 2,
        "dir": "~/projects/party-hud",
        "branch": "sdlc/game-feel",
        "cwd": "/w",
    }
    ti = [
        strip(r)
        for r in render.report_side_rows(
            dict(done, sp=(1800.0, 3600), fresh=False), "Studio", dict(rep, task=task), 1, 1, (24, 14), now=860 + 3725
        )
    ]
    ti_text = "\n".join(ti)
    assert not any(k in ti_text for k in ("HP", "SP", "410k", "60m"))
    assert "ASKED" in ti_text
    assert "請幫我把報告頁" in ti_text
    assert sum("很長的提問" in r for r in ti) == 1
    assert sum("…" in r for r in ti) == 1
    assert "12 cmds · 2 agents" in ti_text
    assert "FILES" in ti_text
    assert "a.py" in ti_text
    assert "e.py" in ti_text
    assert "~/projects/party-hud" in ti_text
    assert "\ue725 sdlc/game-feel" in ti_text
    assert "⎇" not in ti_text
    assert any(r.strip("┃ ").startswith("WAITED") and r.strip("┃ ").endswith("1h 02m") for r in ti)
    assert all(common.cw(r) == 30 for r in ti)


def test_side_column_omits_what_it_could_not_get():
    ti = [
        strip(r)
        for r in render.report_side_rows(
            dict(done, hp=None, hp_left=None),
            "Studio",
            dict(rep, task={"ask": None, "files": [], "cmds": 3, "agents": 0, "dir": None, "branch": None}),
            1,
            1,
            (24, 14),
        )
    ]
    bare = [
        strip(r)
        for r in render.report_side_rows(
            done,
            "Studio",
            dict(rep, task={"ask": None, "files": [], "cmds": 0, "agents": 0, "dir": None, "branch": None}),
            1,
            1,
            (24, 14),
        )
    ]
    assert any("3 cmds" in r for r in ti)
    assert not any("FILES" in r or "agents" in r for r in ti)
    assert not any(k in "\n".join(bare) for k in ("ASKED", "WORK", "WHERE", "WAITED"))
    assert all(common.cw(r) == 30 for r in ti + bare)
    assert len(bare) == len([strip(r) for r in render.report_side_rows(done, "Studio", rep, 1, 1, (24, 14))])


def test_home_directory_is_written_tilde(monkeypatch):
    monkeypatch.setenv("HOME", "/home/me")
    assert [collect.home_path(p) for p in ("/home/me", "/home/me/projects/party-hud/", "/home/mex/a", "/srv/x")] == [
        "~",
        "~/projects/party-hud",
        "/home/mex/a",
        "/srv/x",
    ]


def test_where_path_breaks_at_a_slash():
    two = render.where_rows("~/projects/party-hud/subs", 24)
    assert render.where_rows("~/projects/party-hud", 24) == ["~/projects/party-hud"]
    assert two == ["~/projects/party-hud", "/subs"]


def test_where_path_too_long_is_cut_from_the_left():
    cut = render.where_rows("~/work/clients/acme/services/billing/api/internal/handlers", 24)
    assert len(cut) == 2
    assert cut[0].startswith("…/")
    assert cut[1].endswith("/handlers")
    assert "~" not in cut[0]
    assert all(common.cw(r) <= 24 for r in cut)


def test_where_rows_are_30_wide_without_control_characters():
    wr = [
        strip(r)
        for r in render.report_side_rows(
            done,
            "Studio",
            dict(
                rep,
                task={
                    "ask": None,
                    "files": [],
                    "cmds": 0,
                    "agents": 0,
                    "dir": "~/work/clients/acme/services/billing/api/internal/handlers\x1b[31m",
                    "branch": "x" * 40,
                    "cwd": "/w",
                },
            ),
            1,
            1,
            (24, 14),
        )
    ]
    assert all(common.cw(r) == 30 for r in wr)
    assert not any(re.search("[\\x00-\\x1f\\x7f]", r) for r in wr)


def test_side_column_lists_files_relative_to_cwd():
    fl = [strip(r).strip("┃ ") for r in render.report_side_rows(done, "Studio", dict(rep, task=many), 1, 1, (24, 14))]
    fa = [
        strip(r)
        for r in render.report_side_rows(
            done,
            "Studio",
            dict(
                rep, task=dict(many, files=["/w/party_hud/ui.py", "/other/" + "d/" * 20 + "ui.py"], agents=0, cmds=14)
            ),
            1,
            1,
            (24, 14),
        )
    ]
    assert fl.count("+4 more") == 1
    assert "• party_hud/f0.py" in fl
    assert "• party_hud/f4.py" in fl
    assert "party_hud/f5.py" not in "".join(fl)
    assert "3 agents" in fl
    assert not any("/w/" in r for r in fl)
    assert any(r.startswith("• …/") and r.endswith("ui.py") for r in (x.strip("┃ ") for x in fa))
    assert any("14 cmds" in r for r in fa)
    assert all(common.cw(r) == 30 for r in fa)


def test_every_listed_file_has_a_green_bullet():
    fb = [
        r
        for r in render.report_side_rows(done, "Studio", dict(rep, task=many), 1, 1, (24, 14))
        if "party_hud/f" in strip(r)
    ]
    assert len(fb) == 5
    assert all(r.count(common.fg("green", True) + "•") == 1 for r in fb)
    assert not any(
        "•" in strip(r)
        for r in render.report_side_rows(done, "Studio", dict(rep, task=many), 1, 1, (24, 14))
        if "more" in strip(r) or "agents" in strip(r)
    )


def test_control_characters_in_a_file_path_never_reach_the_side_column():
    ctl = [
        strip(r)
        for r in render.report_side_rows(
            done, "Studio", dict(rep, task=dict(many, files=["/w/a\x1b[31m\nb\tc\x07.py"], agents=0)), 1, 1, (24, 14)
        )
    ]
    assert any("a[31mbc.py" in r for r in ctl)
    assert not any(re.search("[\\x00-\\x1f\\x7f]", r) for r in ctl)
    assert all(common.cw(r) == 30 for r in ctl)


def test_split_frame_closes_on_the_last_row():
    short = [
        strip(l)
        for l in render.render_report(
            done, "Studio", dict(rep, text="一行"), [], 150, art=True, banner=(88, 10), portrait=(24, 14), height=60
        ).splitlines()
    ]
    long_ = [
        strip(l)
        for l in render.render_report(
            done,
            "Studio",
            dict(rep, text="\n".join(f"L{n}" for n in range(60))),
            [],
            150,
            art=True,
            banner=(88, 10),
            portrait=(24, 14),
            height=20,
        ).splitlines()
    ]
    assert len(short) == 59
    assert short[-1].startswith("┗")
    assert any("⏎ go" in l for l in short)
    assert sum(l.startswith("┗") for l in short) == 1
    assert long_[-1].startswith("┗")
    assert len(long_) > 20
    assert all(common.cw(l) <= 150 for l in short + long_)


def test_split_page_running_subagents_line_under_the_banner():
    busy_w = render.render_report(
        busy, "Studio", rep, [], 150, art=True, banner=(118, 15), portrait=(24, 14)
    ).splitlines()
    assert "1 subagent still running" in strip(busy_w[16])
    assert strip(busy_w[17]).endswith("┃  ")


def test_below_100_columns_or_without_art_the_old_layout_stays():
    wide99 = render.render_report(done, "Studio", rep, [], 99, art=True).splitlines()
    assert (
        wide99
        == render.render_report(done, "Studio", rep, [], 99, art=True, banner=(80, 10), portrait=(24, 3)).splitlines()
    )
    assert not any(strip(l).startswith("┏") for l in wide99)
    assert not any(strip(l).startswith("┏") for l in render.render_report(done, "Studio", rep, [], 150).splitlines())


def test_finished_subagent_listed_below_the_main_report():
    sf = strip(render.render_report(done, "Studio", dict(rep, subagents=[sub]), [], 60))
    assert "Quest complete" in sf.splitlines()[0]
    assert sf.index("Execute ticket 001") > sf.index("完成了報告畫面")
    assert "subagent said hi" in sf
    assert "## " not in sf
    assert "running" not in sf


def test_report_pane_with_no_party_members_says_so():
    nr = strip(render.render_no_report(40, 10)).splitlines()
    assert len(nr) == 10
    assert "No party members." in nr[1]
    assert all(common.cw(l) == 40 for l in nr[:3])
    assert "q close" in nr[-1]


MDT = "# T\n\n- a **b** `c`\n\n| h | i |\n|---|---|\n| 1 | 2 |\n\n```\ncode line that is long\n```\nlast line of text"
MDCASES = {
    "done": {"live": False, "start": 1, "end": 2, "text": MDT},
    "live": {"live": True, "start": 1, "tool": "Bash", "said": "hi", "prev": {"text": MDT}},
    "subagents": {
        "live": False,
        "start": 1,
        "end": 2,
        "text": MDT,
        "subagents": [{"desc": "d", "type": "t", "text": MDT + " 2"}],
    },
}


@pytest.mark.parametrize("name", list(MDCASES))
def test_markdown_cache_gives_the_same_rows_reused_and_recomputed(name):
    rep = MDCASES[name]
    markdown.clear_markdown_cache()
    cold1 = render.report_rows(rep, [], [], 30, 40, 10.0)
    warm = render.report_rows(rep, [], [], 30, 40, 10.0)
    markdown.clear_markdown_cache()
    assert cold1 == warm == render.report_rows(rep, [], [], 30, 40, 10.0)


def test_report_banner_split_fills_the_right_column():
    assert ui.banner_cells(170, 0.452) == (106, 6, 8)
    assert ui.banner_cells(150, 0.452) == (106, 6, 8)
    assert ui.banner_cells(120, 0.2) == (80, 4, 4)
    assert ui.banner_cells(105, 0.452) == (66, 6, 5)


def test_report_banner_flatter_than_8_to_1_narrows_the_cols():
    assert ui.banner_cells(400, 0.5) == (96, 6, 8)


def test_report_banner_narrow_stays_4_to_1():
    assert ui.banner_cells(99, 0.452) == (53, 6, 4)
    assert ui.banner_cells(60, 0.452) == (53, 6, 4)
    assert ui.banner_cells(40, 0.452) == (40, 5, 4)
    assert ui.banner_cells(400, 0.5)[2] == 8


def test_banner_row_carries_the_image_id_of_its_ratio():
    assert (
        art.image_row(art.banner_id("done", True, False, 8), 0, 106)
        in render.render_report(
            done, "Studio", rep, [], 150, art=True, banner=(106, 6, 8), portrait=(14, 7)
        ).splitlines()[1]
    )


@pytest.fixture
def images(tmp_path):
    """Fake art files and the split (sp) and narrow (nr) image strings for done."""

    def png(name, data=b"x"):
        path = tmp_path / name
        path.write_bytes(data)
        return str(path)

    fake_art = {
        art.banner_id("done", True, False): (png("B", b"B"),),
        art.portrait_id(done): (png("P", b"P"), 6, 3),
        art.big_portrait_id(done): (png("G", b"G"),),
    }
    sp = ui.report_images(done, True, fake_art, 150, (118, 15), (20, 11))
    nr = ui.report_images(done, True, fake_art, 90, (80, 10), (20, 11))
    return fake_art, png, sp, nr


def test_report_images_split_deletes_then_sends(images):
    _, _, sp, nr = images
    assert (
        sp.index(f"a=d,d=I,i={bid_}")
        < sp.index(f"a=T,U=1,f=100,i={bid_},c=118,r=15")
        < sp.index(f"a=d,d=I,i={big_}")
        < sp.index(f"a=T,U=1,f=100,i={big_},c=20,r=11")
    )
    assert big_ != pid_
    assert f"i={pid_}," not in sp
    assert f"a=d,d=I,i={pid_}," not in nr
    assert f"a=d,d=I,i={big_}," not in nr
    assert f"a=T,U=1,f=100,i={pid_},c=6,r=3" in nr
    assert f"i={big_}," not in nr


@pytest.fixture
def labelled(images):
    fake_art, png, _, _ = images
    fake_art.update({art.label_id("took"): (png("L", b"L"),), art.label_id("where"): (png("M", b"M"),)})
    lb = ui.report_images(done, True, fake_art, 150, (118, 15), (20, 11), None, ["took", "where"])
    lb_n = ui.report_images(done, True, fake_art, 90, (80, 10), (20, 11), None, ["took"])
    tid, wid = art.label_id("took"), art.label_id("where")
    return fake_art, lb, lb_n, tid, wid


def test_report_images_split_also_sends_the_labels(labelled):
    fake_art, lb, lb_n, tid, wid = labelled
    assert f"i={tid},c=8,r=1,q=2,m=0;TA==" in lb
    assert f"i={wid},c=9,r=1" in lb
    assert f"i={art.label_id('files')}," not in lb
    assert f"i={tid}," not in lb_n
    assert (
        ui.report_images(
            done,
            True,
            fake_art,
            150,
            (118, 15),
            (20, 11),
            {bid_: (118, 15), big_: (20, 11), tid: (8, 1), wid: (9, 1)},
            ["took", "where"],
        )
        == ""
    )
    assert f"i={wid},c=9,r=1" in ui.report_images(
        done,
        True,
        fake_art,
        150,
        (118, 15),
        (20, 11),
        {bid_: (118, 15), big_: (20, 11), tid: (8, 1)},
        ["took", "where"],
    )


def test_report_images_redraw_sends_only_what_changed(images):
    fake_art, _, _, _ = images
    rd_same = ui.report_images(done, True, fake_art, 150, (118, 15), (20, 11), {bid_: (118, 15), big_: (20, 11)})
    rd_big = ui.report_images(done, True, fake_art, 150, (118, 15), (24, 12), {bid_: (118, 15), big_: (20, 11)})
    rd_new = ui.report_images(done, True, fake_art, 90, (80, 10), (20, 11), {bid_: (118, 15), big_: (20, 11)})
    assert rd_same == ""
    assert "a=d" not in rd_big
    assert f"i={big_},c=24,r=12" in rd_big
    assert f"i={bid_}," not in rd_big
    assert "a=d" not in rd_new
    assert f"i={bid_},c=80,r=10" in rd_new
    assert f"i={pid_},c=6,r=3" in rd_new


@pytest.fixture
def new_page(images):
    fake_art, _, _, _ = images
    pg_same = ui.report_images(
        done, True, fake_art, 150, (118, 15), (20, 11), None, (), {bid_: (118, 15), big_: (20, 11)}
    )
    pg_big = ui.report_images(
        done, True, fake_art, 150, (118, 15), (24, 12), None, (), {bid_: (118, 15), big_: (20, 11)}
    )
    pg_new = ui.report_images(done, True, fake_art, 150, (118, 15), (20, 11), None, (), {bid_: (118, 15)})
    return pg_same, pg_big, pg_new


def test_report_images_new_page_skips_ids_sent_at_the_same_cells(new_page):
    pg_same, _, _ = new_page
    assert pg_same == ""


def test_report_images_new_page_resends_at_other_cells_without_delete(new_page):
    _, pg_big, _ = new_page
    assert "a=d" not in pg_big
    assert f"i={big_},c=24,r=12" in pg_big
    assert f"i={bid_}," not in pg_big


def test_report_images_new_page_deletes_an_id_never_sent(new_page):
    _, _, pg_new = new_page
    assert pg_new.index(f"a=d,d=I,i={big_}") < pg_new.index(f"a=T,U=1,f=100,i={big_},c=20,r=11")
    assert f"i={bid_}," not in pg_new


def test_report_first_frame_deletes_only_ids_never_sent(images):
    fake_art, _, _, _ = images
    fd_sp = ui.report_first_deletes(done, True, fake_art, 150, (118, 15), (20, 11), {bid_: (118, 15)})
    fd_nr = ui.report_first_deletes(done, True, fake_art, 90, (80, 10), (20, 11), {})
    assert fd_sp == art.kitty_delete(big_)
    assert "a=T" not in fd_sp
    assert f"a=d,d=I,i={bid_}," in fd_nr
    assert f"i={pid_}," not in fd_nr


def test_report_images_send_the_right_portrait_bytes(images):
    _, _, sp, nr = images
    assert f"i={big_},c=20,r=11,q=2,m=0;Rw==" in sp
    assert "UA==" not in sp
    assert "UA==" in nr
    assert "Rw==" not in nr


def test_split_portrait_is_centered_and_shares_the_banner_top_row():
    pc_, pr_ = ui.portrait_cells(0.452)
    raw_wide = render.render_report(
        done, "Studio", rep, [], 150, art=True, banner=(96, 6), portrait=(pc_, pr_)
    ).splitlines()
    assert pc_ == art.SPLIT_BIG_PORTRAIT_COLS == 14
    assert pr_ == 7
    assert strip(raw_wide[1]).startswith("┃" + " " * 7 + chr(1109742))
    assert art.image_row(art.big_portrait_id(done), 0, 14) in raw_wide[1]
    assert art.image_row(art.banner_id("done", True, False), 0, 96) in raw_wide[1]


qt = [
    {"name": "A", "agents": [mk("%1", "done"), mk("%2", "working"), mk("%3", "waiting")]},
    {"name": "B", "agents": [mk("%4", "done")]},
]
qi = [
    {
        "name": "A",
        "agents": [
            dict(mk("%1", "idle"), window="@1"),
            dict(mk("%2", "idle"), window="@2"),
            dict(mk("%3", "working"), window="@2"),
        ],
    }
]


def test_report_queue_waiting_then_done_then_the_rest():
    assert [a["pane"] for _, a in ui.report_queue(qt)] == ["%3", "%1", "%4", "%2"]


def test_report_queue_pane_asked_for_comes_first():
    assert [a["pane"] for _, a in ui.report_queue(qt, "%2")] == ["%2", "%3", "%1", "%4"]
    assert ui.report_queue(qt, "%2")[0][0] == "A"


def test_report_resize_redraws_are_at_least_resize_interval_apart():
    assert abs(ui.report_resize_wait(5.0, 5.0) - ui.RESIZE_INTERVAL) < 1e-09
    assert ui.RESIZE_INTERVAL > 0
    assert abs(ui.report_resize_wait(5.0, 5.02) - (ui.RESIZE_INTERVAL - 0.02)) < 1e-09
    assert ui.report_resize_wait(5.0, 5.0 + ui.RESIZE_INTERVAL) == 0
    assert ui.report_resize_wait(5.0, 9.0) == 0


def test_report_peek_reuses_the_captured_peek():
    pk, grabs = {}, []
    assert ui.report_peek(pk, "%1", None, None, lambda p: grabs.append(p) or ["x"]) == ["x"]
    assert ui.report_peek(pk, "%1", None, None, lambda p: grabs.append(p) or ["y"]) == ["x"]
    assert grabs == ["%1"]
    assert ui.report_peek(pk, "%2", {}, None, grabs.append) == []
    assert grabs == ["%1"]


def test_report_queue_working_with_running_subagents_after_waiting_and_done():
    qs = [
        {
            "name": "A",
            "agents": [
                dict(mk("%1", "working"), summons=[{}]),
                mk("%2", "working"),
                mk("%3", "done"),
                dict(mk("%4", "working"), summons=[]),
            ],
        },
        {"name": "B", "agents": [mk("%5", "waiting"), dict(mk("%6", "working"), summons=[{}])]},
    ]
    assert [a["pane"] for _, a in ui.report_queue(qs)][:4] == ["%5", "%3", "%1", "%6"]


def test_report_queue_idle_and_working_are_still_queued():
    assert [a["pane"] for _, a in ui.report_queue(qi)] == ["%1", "%2", "%3"]


def test_report_queue_waiting_first_then_the_current_window():
    qw = [
        {
            "name": "A",
            "agents": [
                dict(mk("%1", "idle"), window="@1"),
                dict(mk("%2", "waiting"), window="@2"),
                dict(mk("%3", "idle"), window="@1"),
            ],
        }
    ]
    assert [a["pane"] for _, a in ui.report_queue(qw, None, "@1")] == ["%2", "%1", "%3"]


def test_report_queue_current_window_before_other_idle_or_working():
    assert [a["pane"] for _, a in ui.report_queue(qi, None, "@2")] == ["%2", "%3", "%1"]


def test_report_queue_callers_window_orders_the_queue():
    qm = [
        {"name": "A", "agents": [dict(mk("%1", "idle"), window="@1")]},
        {"name": "B", "agents": [dict(mk("%2", "idle"), window="@2")]},
    ]
    assert [a["pane"] for _, a in ui.report_queue(qm, None, "@2")] == ["%2", "%1"]


def test_report_queue_pane_asked_for_stays_first_with_a_current_window():
    assert [a["pane"] for _, a in ui.report_queue(qi, "%3", "@2")] == ["%3", "%2", "%1"]


def test_report_queue_no_members():
    assert ui.report_queue([]) == []
    assert ui.report_queue([{"name": "A", "agents": []}], "%1", "@1") == []
