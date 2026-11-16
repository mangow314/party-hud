# pyright: reportOptionalSubscript=false, reportOperatorIssue=false
"""Tests index results they expect to exist and read union-typed fixture fields; a wrong value fails the test anyway."""

import os
from itertools import pairwise

import pytest
from screen import strip

from party_hud import art, collect, common, markdown, render, ui

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "sidebar.json")
agents = [a for t in collect.collect(FIXTURE)["towns"] for a in t["agents"]]
done = dict(agents[0], status="done", hp_left=410000, hp_max=1000000)


def mk(pane, status):
    return {"pane": pane, "status": status}


def mm(pane, name, status, lead=None):
    return dict(mk(pane, status), name=name, **({"lead": lead} if lead else {}))


def sq(ags):
    return {"name": "S", "agents": ags}


def sm(pane, name, status, lead=None):
    return {
        **dict(done, pane=pane, name=name, status=status, round=1, summons=[], focus=False),
        **({"lead": lead} if lead else {}),
    }


sk = ["%1", "%2", "%3"]
st = [
    sq(
        [
            mm("%1", "idle1", "idle"),
            mm("%2", "work1", "working"),
            mm("%3", "done1", "done"),
            mm("%4", "wait1", "waiting"),
            mm("%5", "sleep1", "sleep"),
            mm("%6", "c1", "waiting", "%9"),
            mm("%7", "c2", "done", "%2"),
            mm("%8", "cc", "waiting", "%6"),
        ]
    ),
    {
        "name": "T",
        "agents": [
            mm("%9", "far", "idle"),
            mm("%10", "c3", "waiting", "%9"),
            mm("%11", "c4", "waiting", "%9"),
            mm("%12", "c5", "waiting", "%2"),
        ],
    },
]
rs = render.select_roster(st)
sst = [
    {
        "name": "S",
        "agents": [
            sm("%1", "idle1", "idle"),
            sm("%2", "work1", "working"),
            sm("%3", "done1", "done"),
            sm("%4", "wait1", "waiting"),
            sm("%5", "sleep1", "sleep"),
            sm("%6", "c1", "waiting", "%9"),
            sm("%7", "c2", "done", "%2"),
            sm("%8", "cc", "waiting", "%6"),
        ],
    },
    {
        "name": "T",
        "agents": [
            sm("%9", "far", "idle"),
            sm("%10", "c3", "waiting", "%9"),
            sm("%11", "c4", "waiting", "%9"),
            sm("%12", "c5", "waiting", "%2"),
        ],
    },
]
srs = render.select_roster(sst)
srep = {
    "text": "## Layout\n\nThe list fills the pane.\n\n" + "\n".join(f"- point {i}" for i in range(80)),
    "start": 100.0,
    "end": 400.0,
    "live": False,
    "task": {
        "ask": "fix the menu size",
        "files": [],
        "cmds": 0,
        "agents": 0,
        "dir": "~/work/app",
        "branch": None,
        "cwd": "/w",
    },
}
PH = chr(0x10EEEE)


def srows_of(w, h, sel, rep=srep, art=False, ro=srs, tw=sst):
    return render.render_select(ro, tw, sel, w, h, rep, 4000.0, None, art)


def test_select_banner_is_at_most_10_rows():
    assert ui.select_banner(80, 40, 0.5)[1] == 10
    assert ui.select_banner(150, 60, 0.452)[1] == 10
    assert ui.banner_cells(143, 0.5)[1] == 6


def test_select_keys_j_and_k_move_one_row_and_stop_at_the_ends():
    assert ui.select_key("j", sk, "%1") == ("%2", None)
    assert ui.select_key("k", sk, "%3") == ("%2", None)
    assert ui.select_key("k", sk, "%1") == ("%1", None)
    assert ui.select_key("j", sk, "%3") == ("%3", None)


def test_select_keys_a_digit_opens_that_rows_member():
    assert ui.select_key("1", sk, "%3") == ("%1", "open")
    assert ui.select_key("3", sk, "%1") == ("%3", "open")
    assert ui.select_key("4", sk, "%2") == ("%2", None)
    assert ui.select_key("9", sk, "%2") == ("%2", None)
    assert ui.select_key("0", sk, "%2") == ("%2", None)


def test_select_keys_enter_and_l_open_q_and_esc_close():
    assert ui.select_key("\r", sk, "%2") == ("%2", "open")
    assert ui.select_key("\n", sk, "%2") == ("%2", "open")
    assert ui.select_key("l", sk, "%2") == ("%2", "open")
    assert ui.select_key("q", sk, "%2") == ("%2", "close")
    assert ui.select_key("\x1b", sk, "%2") == ("%2", "close")


def test_select_keys_other_keys_do_nothing_and_an_empty_roster_only_closes():
    assert all(ui.select_key(k, sk, "%2") == ("%2", None) for k in ("h", "x", "J", "PgUp", " ", "n", "g"))
    assert ui.select_key("j", [], None) == (None, None)
    assert ui.select_key("\r", [], None) == (None, None)
    assert ui.select_key("q", [], None) == (None, "close")


def test_select_roster_order():
    assert [(a["pane"], c) for _, a, c in rs] == [
        ("%2", False),
        ("%12", True),
        ("%4", False),
        ("%9", False),
        ("%6", True),
        ("%10", True),
        ("%11", True),
        ("%3", False),
        ("%1", False),
        ("%5", False),
    ]


def test_select_roster_drops_done_crew_and_crew_of_crew():
    assert "%7" not in [a["pane"] for _, a, _ in rs]
    assert "%8" not in [a["pane"] for _, a, _ in rs]


def test_select_screen_is_exactly_height_rows_of_width_cells():
    seen_all = True
    for w, h in [
        (180, 47),
        (100, 30),
        (78, 20),
        (77, 20),
        (36, 12),
        (35, 12),
        (34, 8),
        (30, 6),
        (80, 5),
        (80, 4),
        (80, 3),
        (80, 2),
        (80, 1),
        (30, 1),
        (80, 60),
    ]:
        for art_ in (False, True):
            for rep_ in (srep, None):
                out = srows_of(w, h, "%9", rep_, art_)
                seen_all = seen_all and len(out) == h and all(common.cw(strip(r)) == w for r in out)
    assert seen_all


def test_select_preview_column_grows_with_the_pane():
    wide_r, wider_r = srows_of(100, 40, "%2"), srows_of(180, 40, "%2")

    def rule_w(out):
        return len(strip(out[next(i for i, r in enumerate(out) if "  preview" in strip(r)) + 1])[38:].rstrip())

    assert rule_w(wide_r) == 100 - 36 - 2
    assert rule_w(wider_r) == 180 - 36 - 2


def test_select_pane_too_narrow_for_the_preview_draws_only_the_list():
    assert "  preview" in "".join(strip(r) for r in srows_of(78, 40, "%2"))
    assert "  preview" not in "".join(strip(r) for r in srows_of(77, 40, "%2"))
    assert all(strip(r).startswith(" ") and common.cw(strip(r)) == 77 for r in srows_of(77, 40, "%2"))
    assert strip(srows_of(77, 40, "%2")[2])[3] in "╭╔"


def test_select_cursor_member_is_the_selected_card():
    cur = srows_of(180, 40, "%4")
    assert sum("❯" in r for r in cur) == 1
    assert sum("╔" in r for r in cur) == 1
    assert sum("╭" in r for r in cur) >= 2
    assert "❯" not in "".join(srows_of(180, 40, "%12"))


@pytest.fixture
def lines():
    return [strip(r) for r in srows_of(180, 40, "%2")]


def test_select_lead_card_is_five_rows(lines):
    top_ = next(i for i, l in enumerate(lines) if "work1" in l)
    assert lines[top_ - 1][3] in "╭╔"
    assert lines[top_ + 3][3] in "╰╚"
    assert lines[top_ + 3][3] != lines[top_ - 1][3]


def test_select_waiting_crew_is_one_row_under_its_lead(lines):
    cr = next(i for i, l in enumerate(lines) if "c5" in l and render.CREW_MARK in l)
    assert "╰" in lines[cr - 1] or "╚" in lines[cr - 1]
    assert "work1" in lines[cr - 4]
    assert lines[cr].startswith(" 2 ")
    assert render.CREW_MARK in lines[cr]


def test_select_right_column_has_no_portrait_name_class_or_hp():
    art_out = srows_of(180, 47, "%2", srep, True)
    assert "".join(art_out).count(PH) == 18 * sum(1 for r in art_out if "╭" in strip(r) or "╔" in strip(r))
    assert not any(
        w in strip(r)[40:] for r in srows_of(180, 47, "%2") for w in ("HP ", "SP ", "work1", "Thief", "Cleric")
    )


def test_select_report_that_does_not_fit_ends_in_a_more_row():
    mo = [strip(r) for r in srows_of(100, 20, "%2")]
    last = max(i for i, l in enumerate(mo) if "to read" in l)
    assert mo[last][38:].rstrip() == "… more · ⏎ to read"
    assert last == len(mo) - 2


def test_select_report_that_fits_has_no_more_row():
    short = {"text": "short report", "start": 1.0, "end": 2.0, "task": {}}
    assert not any("more ·" in l for l in map(strip, srows_of(180, 40, "%2", short)))
    assert any("no report yet" in strip(r) for r in srows_of(180, 40, "%2", None))


@pytest.fixture
def previews(monkeypatch):
    """Preview rows against the full layout for several reports and sizes: (all ok, cases, fewer layout calls each)."""
    tbl = "| name | note | n |\n|---|---|---|\n" + "\n".join(
        f"| row{i} | {'長い説明 ' * (i % 4)}text {i} | {i * 7} |" for i in range(40)
    )
    fence = "```python\n" + "\n".join(f"line_{i} = '" + "x" * (i % 40) + "'" for i in range(60)) + "\n```\n\nafter"
    nested = "\n".join(f"- item {i} " + "word " * (i % 9) + f"\n  - nested {i}\n    1. deep {i}" for i in range(30))
    quote = "\n".join(f"> quoted {i} " + "q " * (i % 12) + "\n>> inner" for i in range(30))
    cjk = "\n\n".join("你好，世界。" * (3 + i % 5) + "ABC def" for i in range(25))
    heads = "\n".join(f"## Head {i}\nparagraph {i} " + "text " * (i % 15) + "\n" for i in range(30))
    reports_ = [tbl, fence, nested, quote, cjk, heads, "intro\n\n" + tbl, "x\n\n" + fence.replace("after", tbl)]
    pv_ok, pv_n, pv_seen = True, 0, []
    mdcount = [0]
    real_rows, real_table = markdown.md_rows, markdown.md_table
    monkeypatch.setattr(
        markdown, "md_rows", lambda *a, **k: (mdcount.__setitem__(0, mdcount[0] + 1), real_rows(*a, **k))[1]
    )
    monkeypatch.setattr(
        markdown, "md_table", lambda *a, **k: (mdcount.__setitem__(0, mdcount[0] + 1), real_table(*a, **k))[1]
    )
    at_ = next(i for i, (_, a, _) in enumerate(srs) if a["pane"] == "%3")
    for text in reports_:
        rp = dict(srep, text=text)
        for w in (30, 44, 62):
            markdown.clear_markdown_cache()
            mdcount[0] = 0
            full = [strip(r).rstrip() for r in render.report_rows(rp, [], [], w, w, 4000.0, False)]
            n_full = mdcount[0]
            for h in (12, 20, 30):
                markdown.clear_markdown_cache()
                mdcount[0] = 0
                pv = [strip(r).rstrip() for r in render.select_preview(srs, sst, at_, w, h, rp, 4000.0)]
                rule = next(i for i, r in enumerate(pv) if r.startswith("─" * w))
                body = pv[rule + 1 :]
                pv_seen.append(mdcount[0] < n_full if "| name |" not in text[:20] else mdcount[0] <= n_full)
                pv_n += 1
                pv_ok = (
                    pv_ok and body[-1] == "… more · ⏎ to read" and body[:-1] == full[: len(body) - 1] and len(pv) == h
                )
    markdown.clear_markdown_cache()
    return pv_ok, pv_n, pv_seen


def test_select_preview_shows_the_first_rows_of_the_full_layout(previews):
    pv_ok, pv_n, _ = previews
    assert pv_ok
    assert pv_n == 72


def test_select_preview_lays_out_only_part_of_the_report(previews):
    _, _, pv_seen = previews
    assert all(pv_seen)


def test_select_preview_header_rows_are_the_preview_width_when_narrow():
    live_r = dict(srep, live=True, end=None, start=3700.0)
    widths = {}
    for w in range(18, 34):
        for pane in ("%1", "%2", "%3", "%4", "%9"):
            at_ = next(i for i, (_, a, _) in enumerate(srs) if a["pane"] == pane)
            for label, rep_ in (("done", srep), ("live", live_r), ("none", None)):
                pv = [strip(r) for r in render.select_preview(srs, sst, at_, w, 12, rep_, 4000.0, ["x"])]
                rule = next(i for i, r in enumerate(pv) if r.startswith("─"))
                widths[w, pane, label] = {common.cw(r) for r in pv[: rule + 1]}
    assert {k: v for k, v in widths.items() if v != {k[0]}} == {}


@pytest.fixture
def cxro():
    cxst = [
        {
            "name": "S",
            "agents": [
                {**sm(f"%{i}", f"m{i}", st_), **({"kind": "codex", "sp": None} if i % 2 else {})}
                for i, st_ in enumerate(["waiting", "done", "working", "idle", "waiting", "idle", "done", "sleep"], 20)
            ],
        }
    ]
    cxro = render.select_roster(cxst)
    return cxst, cxro


def test_select_fixture_has_4_and_5_row_cards(cxro):
    _, cxro = cxro
    assert {len(render.card(a, render.SELECT_CARD, False, False)) for _, a, _ in cxro} == {4, 5}


def test_select_mixed_card_heights_keep_the_screen_exact(cxro):
    cxst, cxro = cxro
    cx_ok = True
    for w, h in [(179, 47), (100, 30), (100, 20), (100, 14), (179, 12)]:
        for _, a, _ in cxro:
            out = [strip(r) for r in srows_of(w, h, a["pane"], srep, False, cxro, cxst)]
            cx_ok = (
                cx_ok
                and len(out) == h
                and all(common.cw(r) == w for r in out)
                and out[-2][38:].rstrip() == "… more · ⏎ to read"
            )
    assert cx_ok


def test_select_preview_without_report_shows_the_panes_last_lines():
    pk_rows = lambda rep, pk_: [
        strip(r) for r in render.render_select(srs, sst, "%2", 120, 30, rep, 4000.0, None, False, pk_)
    ]
    assert any("$ make test" in r for r in pk_rows(None, ["$ make test", "ok"]))
    assert not any("no report yet" in r for r in pk_rows(None, ["$ make test"]))
    assert any("no report yet" in r for r in pk_rows(None, []))
    assert not any("$ make test" in r for r in pk_rows(srep, ["$ make test"]))


@pytest.fixture
def st_of():
    live_r = {
        "live": True,
        "start": 3700.0,
        "end": None,
        "text": "",
        "tool": "Bash make",
        "said": "building",
        "prev": None,
        "task": {},
    }
    st_of = lambda status, rep, pk_=(): next(
        (
            strip(r)[38:]
            for r in render.render_select(
                srs,
                sst,
                {"done": "%3", "waiting": "%4", "idle": "%1", "working": "%2"}[status],
                120,
                30,
                rep,
                4000.0,
                None,
                False,
                pk_,
            )
            if "  preview" in strip(r)
        ),
        "",
    )
    fin = dict(srep, live=False)
    return st_of, live_r, fin


def test_select_preview_title_row_opens_with_the_state_word(st_of):
    st_of, live_r, fin = st_of
    assert st_of("done", fin).startswith("Quest complete")
    assert st_of("waiting", fin).startswith("Waiting for you")
    assert st_of("idle", fin).startswith("Report")
    assert st_of("working", live_r).startswith("Working")
    assert st_of("working", None, ["x"]).startswith("Last output")


def test_select_preview_title_row_says_unread_for_a_done_member(st_of):
    st_of, live_r, fin = st_of
    assert "preview · unread" in st_of("done", fin)
    assert all(
        t.rstrip().endswith("preview") and "unread" not in t for t in (st_of("working", live_r), st_of("idle", fin))
    )


def test_select_working_preview_names_the_state_once(st_of):
    _, live_r, _ = st_of
    wk = [strip(r) for r in render.render_select(srs, sst, "%2", 120, 30, live_r, 4000.0, None, False)]
    assert sum("Working" in r for r in wk) == 1
    assert any("RUNNING" in r and "5m 00s" in r for r in wk)


def test_select_list_taller_than_the_pane_scrolls_by_whole_cards():
    many = [("S", sm(f"%{i}", f"m{i}", "idle"), False) for i in range(12)] + [
        ("S", sm("%30", "crew-a", "waiting", "%11"), True)
    ]
    vis = True
    for k in range(13):
        for art_ in (False, True):
            for h in (20, 14, 9):
                out = [strip(r) for r in srows_of(100, h, many[k][1]["pane"], srep, art_, many, sst)]
                nm = many[k][1]["name"]
                i = next((i for i, l in enumerate(out) if nm in l), None)
                if i is None:
                    vis = False
                elif not many[k][2] and k != 12:
                    vis = vis and ("╔" in out[i - 1] or "╭" in out[i - 1]) and ("╚" in out[i + 3] or "╰" in out[i + 3])
        out = [strip(r)[:36] for r in srows_of(100, 20, many[k][1]["pane"], srep, False, many, sst)]
        vis = vis and sum("╭" in l or "╔" in l for l in out) == sum("╰" in l or "╚" in l for l in out)
    assert vis


def test_select_with_less_room_than_one_card_every_item_is_one_row():
    assert any("far" in strip(r) for r in srows_of(100, 6, "%9"))
    assert not any("╭" in r or "╔" in r for r in srows_of(100, 6, "%9"))
    assert any("╔" in r for r in srows_of(100, 9, "%9"))


def test_select_empty_roster_shows_no_party_members():
    emp = render.render_select([], [], None, 40, 12)
    assert len(emp) == 12
    assert all(common.cw(strip(r)) == 40 for r in emp)
    assert sum("no party members" in r for r in emp) == 1
    assert "PARTY SELECT" in strip(emp[0])


def test_select_title_and_hint_rows():
    assert "PARTY SELECT" in strip(render.render_select(srs, sst, "%4", 80, 20)[0])
    assert strip(render.render_select(srs, sst, "%4", 80, 20, None, None, ["ban", "ner"])[1]).strip() == "ner"
    assert "j/k" in strip(render.render_select(srs, sst, "%4", 80, 20)[-1])


def test_select_summary_counts():
    assert strip(render.select_summary(rs, st, 60)).split() == [
        "6",
        "leads",
        "6",
        "need",
        "you",
        "4",
        "crew",
        "waiting",
    ]
    assert strip(
        render.select_summary([("S", mm("%1", "a", "idle"), False)], [sq([mm("%1", "a", "idle")])], 30)
    ).split() == ["1", "lead"]


def test_select_crew_line():
    assert "c3 waiting" in strip(render.select_crew_line(st[1]["agents"][0], st, 40))
    assert "c4 waiting" in strip(render.select_crew_line(st[1]["agents"][0], st, 60))
    assert "c2 done" in strip(render.select_crew_line(st[0]["agents"][1], st, 40))
    assert render.select_crew_line(st[0]["agents"][0], st, 40) is None
    assert common.cw(strip(render.select_crew_line(st[1]["agents"][0], st, 12))) == 12


def test_select_preview_crew_line_only_for_a_lead_with_crew():
    assert not any("crew " in strip(r)[38:] for r in srows_of(180, 40, "%1"))
    assert any(strip(r)[38:].startswith("crew") for r in srows_of(180, 40, "%2"))


def test_select_images_plan_and_shared_ids(tmp_path):
    def png(name, data=b"x"):
        path = tmp_path / name
        path.write_bytes(data)
        return str(path)

    assert ui.select_image_plan([sst[1]["agents"][0]], {art.portrait_id(sst[1]["agents"][0]): (png("x"), 6, 3)}) == [
        (art.portrait_id(sst[1]["agents"][0]), 6, 3)
    ]
    assert ui.select_image_plan([sst[1]["agents"][0]], None) == []
    assert art.kitty_delete(7) not in ui.select_images_out([(7, 6, 3)], {7: (png("x"), 6, 3)}, {}, {7})
    assert art.kitty_delete(8) in ui.select_images_out([(8, 6, 3)], {8: (png("x"), 6, 3)}, {}, {7})


def cw_row(name, w, sel="%9"):
    return render.select_row(2, sm("%20", name, "waiting", "%9"), True, sel, w)


def test_select_row_waiting_crew_is_bold_with_waiting_for_you():
    cw_ok = all(
        common.cw(strip(cw_row(n, w))) == w
        for n in ("c1", "建置-worker-with-a-very-long-name", "你好世界")
        for w in range(12, 60)
    )
    wr = strip(cw_row("c1", 40))
    assert cw_ok
    assert wr.rstrip().endswith("waiting for you")
    assert render.CREW_MARK in wr
    assert "c1" in wr
    assert strip(cw_row("c1", 40, "%20")).rstrip().endswith("waiting for you")
    assert "\x1b[1;" in cw_row("c1", 40)
    assert common.fg("warn", True) in cw_row("c1", 40)
    assert common.bg("sel") in cw_row("c1", 40, "%20")
    assert "waiting for you" in strip(cw_row("a-long-crew-name-here", 40))
    assert "…" in strip(cw_row("a-long-crew-name-here", 40))


def test_select_row_too_narrow_leaves_the_text_out():
    assert "waiting for you" not in strip(cw_row("c1", 14))
    assert "c1" in strip(cw_row("c1", 14))
    assert "waiting for you" not in strip(render.select_row(2, sm("%21", "idle1", "idle"), False, "%1", 40))


def test_select_preview_reread():
    cache0 = (("%2", 1), None, [], 100.0)
    assert not ui.select_reread(cache0, sm("%2", "w", "idle"), 200.0)
    assert not ui.select_reread(cache0, sm("%2", "w", "done"), 200.0)
    assert ui.select_reread(cache0, sm("%3", "w", "idle"), 100.0)
    assert ui.select_reread(cache0, dict(sm("%2", "w", "idle"), round=2), 100.0)
    assert ui.select_reread(cache0, sm("%2", "w", "working"), 100.0 + ui.LIVE_REFRESH)
    assert not ui.select_reread(cache0, sm("%2", "w", "working"), 100.0 + ui.LIVE_REFRESH - 0.1)


def tw_(now, anchors):
    return ui.tick_wait(now, anchors) - ui.TICK_MARGIN


def sec_(a):
    return (a, 1.0)


def test_time_ticks_wait_up_to_the_next_anchor():
    assert abs(tw_(105.0, [sec_(100.3)]) - 0.3) < 1e-06
    assert abs(tw_(105.3, [sec_(100.3)]) - 1.0) < 1e-06
    assert abs(tw_(105.0, [sec_(100.3), sec_(100.8)]) - 0.3) < 1e-06
    assert abs(tw_(105.5, [sec_(100.3), sec_(100.8)]) - 0.3) < 1e-06
    assert abs(tw_(105.0, [ui.SECOND, sec_(100.3)]) - 0.3) < 1e-06
    assert ui.tick_wait(105.0, []) == float("inf")
    assert abs(tw_(130.0, [(100.0, 60.0)]) - 30.0) < 1e-06
    assert abs(tw_(130.0, [(100.0, 60.0), ui.SECOND]) - 1.0) < 1e-06


def test_time_anchor():
    assert ui.time_anchor(100.0, 3599.4 + 100.0) == (100.5, 1.0)
    assert ui.time_anchor(100.0, 3599.6 + 100.0) == (99.5, 60.0)
    assert ui.time_anchor(100.0, 100.0) == (100.5, 1.0)


def test_select_wait():
    assert abs(ui.select_wait(10.0, 10.2, 10.9, 10.4) - 0.5) < 1e-09
    assert ui.select_wait(10.0, 10.2, 10.3, 10.4) == 0.0
    assert abs(ui.select_wait(10.0, 10.2, 40.0, 10.4) - 0.8) < 1e-09
    assert abs(ui.select_wait(10.0, 10.2, float("inf"), 10.4) - 0.8) < 1e-09


def sel_sched(anchors_of, t0, frac=0.35, span=60.0):
    t, fetched, wakes, reads = t0, t0 - frac, [], []
    while t < t0 + span:
        if t - fetched >= ui.SNAP_AGE:
            fetched = t
            reads.append(t)
        wakes.append(t)
        tick_at = t + ui.tick_wait(t, anchors_of(t))
        t += ui.select_wait(fetched, t, tick_at, t)
    return wakes, reads


def sel_rates(anchors_of):
    worst, gap = 0, 0.0
    for fr in (0.0, 0.1, 0.35, 0.5, 0.75, 0.95):
        wakes, reads = sel_sched(lambda t, fr=fr: anchors_of(t, fr), 5000.0)
        worst = max(worst, (len(wakes) - 1) / 60)
        gap = max(gap, max(b - a for a, b in pairwise(reads)))
    return worst, gap


@pytest.fixture(scope="module")
def rates():
    return {
        name: sel_rates(f)
        for name, f in {
            "none": lambda t, fr: [],
            "done_cursor_hp": lambda t, fr: [ui.SECOND],
            "waiting": lambda t, fr: [ui.time_anchor(4900.0 + fr, t)],
            "working_live": lambda t, fr: [ui.SECOND, ui.time_anchor(4900.0 + fr, t)],
            "waiting_hour": lambda t, fr: [ui.time_anchor(1000.0 + fr, t)],
        }.items()
    }


def test_select_at_most_1_recompute_a_second_2_for_a_live_working_member(rates):
    assert rates["none"][0] <= 1
    assert rates["done_cursor_hp"][0] <= 1
    assert rates["waiting"][0] <= 1
    assert rates["working_live"][0] <= 2
    assert rates["waiting_hour"][0] <= 1
    assert rates["working_live"][0] > 1.5


def test_select_snapshot_read_at_least_every_2_seconds(rates):
    assert all((gap <= 2.0 for _, gap in rates.values()))


def select_changes(frac):
    start = 4900.0 + frac
    wakes, _ = sel_sched(lambda t: [ui.SECOND, ui.time_anchor(start, t)], 5000.0, span=30.0)
    shown, changes = None, []
    for t in wakes:
        v = render.fmt_took(t - start)
        if v != shown:
            changes.append(t)
        shown = v
    return start, changes


def test_select_running_time_changes_when_fmt_took_rounds_up():
    sel_ok = True
    for fr in (0.0, 0.3, 0.7):
        st, ch = select_changes(fr)
        sel_ok = sel_ok and len(ch) >= 25 and all(0.5 <= (c - st) % 1 < 0.55 for c in ch[1:])
    assert sel_ok


def hour_changes(frac):
    start = 100.0 + frac
    t, shown, changes, wakes = start + 3590.0, None, [], 0
    while t < start + 7300.0:
        wakes += 1
        v = render.fmt_took(t - start)
        if v != shown:
            changes.append(t)
        shown = v
        t += ui.tick_wait(t, [ui.time_anchor(start, t)])
    return start, changes, wakes


def test_time_ticks_from_3600_s_once_a_minute():
    hour_ok = True
    for fr in (0.0, 0.3, 0.77):
        st, ch, wk = hour_changes(fr)
        hour_ok = (
            hour_ok
            and wk <= 75
            and all(0.0 <= (c - st + 0.5) % 60 < 0.3 for c in ch if c - st > 3599)
            and len([c for c in ch if c - st > 3599]) == 62
        )
    assert hour_ok


def phase_run(spins, timed_of, t0, frac, span=30.0):
    t, fetched, rows = t0, t0 - frac, []
    while t < t0 + span:
        if t - fetched >= ui.SNAP_AGE:
            fetched = t
        tick, anchors, _ = ui.select_phase(t, spins, timed_of(t))
        rows.append((t, tick))
        t += ui.select_wait(fetched, t, t + ui.tick_wait(t, anchors), t)
    return rows


def phase_ok(rows):
    ticks = [k for _, k in rows]
    gaps = [b[0] - a[0] for a, b in pairwise(rows[1:])]
    return len(rows) <= 32 and all(b - a == 1 for a, b in pairwise(ticks)) and all(0.99 <= g <= 1.01 for g in gaps)


def one_wake_a_second():
    if getattr(ui, "select_phase", None) is None:
        return False
    good = True
    for fr in (0.0, 0.3, 0.7):
        start = 5000.0 - 200.0 + fr
        rows = phase_run(True, lambda t, start=start: ui.time_anchor(start, t), 5000.0, fr)
        took = [render.fmt_took(t - start) for t, _ in rows]
        good = good and phase_ok(rows) and all(a != b for a, b in pairwise(took))
        hour = 5000.0 - 3700.0 + fr
        rows = phase_run(True, lambda t, hour=hour: ui.time_anchor(hour, t), 5000.0, fr)
        took = [render.fmt_took(t - hour) for t, _ in rows]
        ticks = [k for _, k in rows]
        good = (
            good
            and len(rows) <= 32
            and all(k == int(t) for t, k in rows)
            and all(b - a in (0, 1) for a, b in pairwise(ticks))
            and ticks[-1] - ticks[0] >= 29
            and sum(a != b for a, b in pairwise(took)) <= 1
        )
        rows = phase_run(True, lambda t: None, 5000.0, fr)
        good = good and phase_ok(rows) and all(k == int(t) for t, k in rows)
    return good


def test_select_one_wake_a_second():
    assert one_wake_a_second()


def phase_seq(segments, t0):
    t, fetched, state, rows = t0, t0 - 0.35, None, []
    for timed_of, dur in segments:
        end = t + dur
        while True:
            if t - fetched >= ui.SNAP_AGE:
                fetched = t
            tick, anchors, state = ui.select_phase(t, True, timed_of(t), state)
            rows.append((t, tick, state))
            nxt = t + ui.select_wait(fetched, t, t + ui.tick_wait(t, anchors), t)
            if nxt >= end:
                t = end
                break
            t = nxt
    return rows


def phase_switch_ok():
    if getattr(ui, "select_phase", None) is None:
        return False
    good = True
    for shift in (0.0, 0.21, 0.55, 0.9):
        t0 = 5000.0 + shift
        a, b, hr = t0 - 200.3, t0 - 100.8, t0 + 30.0 - 3600.0 - 3.4
        segs = [
            (lambda t, a=a: ui.time_anchor(a, t), 8.0 + shift),
            (lambda t, b=b: ui.time_anchor(b, t), 8.37),
            (lambda t: None, 7.61),
            (lambda t, a=a: ui.time_anchor(a, t), 8.83),
            (lambda t, hr=hr: ui.time_anchor(hr, t), 9.2),
        ]
        rows = phase_seq(segs, t0)
        ticks = [k for _, k, _ in rows]
        good = good and all(y - x in (0, 1) for x, y in pairwise(ticks)) and ticks[-1] - ticks[0] >= 35
        good = good and all(
            0.0 <= (t - st[0]) % 1 < 0.02 or (st[0] != old[0] and t - old[3] >= 1.0)
            for (_, x, old), (t, y, st) in pairwise(rows)
            if y == x + 1
        )
        good = good and len(rows) <= 42 + 12
    return good


def test_select_one_wake_a_second_across_phase_switches():
    assert phase_switch_ok()


def phase_moving_ok():
    if getattr(ui, "select_phase", None) is None:
        return False
    good = True
    for gap in (0.03, 0.2, 0.5):
        state, steps, ticks = None, [], []
        for i in range(int(60 / gap)):
            t = 5000.0 + i * gap
            start = 4800.0 + (0.3, 0.8, 0.55)[i % 3]
            tick, _, state = ui.select_phase(t, True, ui.time_anchor(start, t), state)
            ticks.append(tick)
            if len(ticks) > 1 and tick != ticks[-2]:
                steps.append(t)
        good = good and all(y - x in (0, 1) for x, y in pairwise(ticks)) and ticks[-1] - ticks[0] >= 60 / (1 + gap) - 2
        good = good and all(b - a <= 1 + gap + 1e-6 for a, b in pairwise(steps))
    return good


def test_select_one_wake_a_second_with_a_moving_cursor():
    assert phase_moving_ok()


sel_ros, sel_towns = [("Studio", done, False)], [{"name": "Studio", "agents": [done]}]
other_ = dict(done, cls=(done["cls"] + 1) % 4)


@pytest.fixture
def sel_art(tmp_path):
    """Small portrait files for done and other_, and the image plan for those two cards."""

    def png(name, data=b"x"):
        path = tmp_path / name
        path.write_bytes(data)
        return str(path)

    sel_art = {art.portrait_id(done): (png("G"), 6, 3), art.portrait_id(other_): (png("H"), 6, 3)}
    return sel_art, ui.select_image_plan([done, other_], sel_art)


def test_select_images_plan_holds_each_cards_small_portrait(sel_art):
    _, plan_a = sel_art
    assert plan_a == [(art.portrait_id(done), 6, 3), (art.portrait_id(other_), 6, 3)]
    assert ui.select_image_plan([done], None) == []


def test_select_images_due_skips_ids_sent_at_the_same_cells(sel_art):
    _, plan_a = sel_art
    assert ui.select_images_due(plan_a, {i: (c, r) for i, c, r in plan_a}) == []
    assert ui.select_images_due(plan_a, {plan_a[0][0]: (7, 3)})[0] == plan_a[0]
    assert ui.select_images_due(plan_a, {}) == plan_a


def test_select_screen_builds_each_card_once_a_frame(monkeypatch):
    real_card, ncard, once_ok = render.card, [0], True

    def counted_card(*a, **k):
        ncard[0] += 1
        return real_card(*a, **k)

    monkeypatch.setattr(render, "card", counted_card)
    for w_, h_, art_ in [
        (120, 40, False),
        (120, 40, True),
        (80, 12, False),
        (80, 10, False),
        (60, 40, False),
        (120, 8, False),
        (36, 40, False),
    ]:
        for cur_ in ("%1", "%4", "%6", "%9", "%12"):
            lw_, _ = render.select_widths(w_ - 1)
            ncard[0] = 0
            view_ = render.select_view(srs, cur_, lw_, render.select_layout(h_, 1)[3], art_)
            shown_ = ui.select_cards(srs, view_)
            rows_ = render.render_select(srs, sst, cur_, w_ - 1, h_, srep, 4000.0, None, art_, (), view_)
            frame_calls = ncard[0]
            built = sum(c is not None for c in view_[4])
            again = render.render_select(srs, sst, cur_, w_ - 1, h_, srep, 4000.0, None, art_)
            text_ = "".join(strip(r) for r in rows_)
            once_ok = (
                once_ok
                and frame_calls == built
                and built == (0 if view_[0] else sum(not c for _, _, c in srs))
                and rows_ == again
                and all(a_["name"] in text_ for a_ in shown_)
                and len(shown_) <= built
            )
            ncard[0] = 0
            render.render_select(srs, sst, cur_, w_ - 1, h_, srep, 4000.0, None, art_)
            once_ok = once_ok and ncard[0] == built
    assert once_ok


def test_select_images_out_repaints_nothing_and_deletes_only_unshared_new_ids(sel_art):
    sel_art, plan_a = sel_art
    same_ = {i: (c, r) for i, c, r in plan_a}
    out_new = ui.select_images_out(plan_a, sel_art, {}, set())
    assert ui.select_images_out(plan_a, sel_art, same_, set()) == ""
    assert out_new.index(f"a=d,d=I,i={plan_a[0][0]}") < out_new.index(f"a=T,U=1,f=100,i={plan_a[0][0]},c=6,r=3")
    assert "a=d" not in ui.select_images_out(plan_a, sel_art, {**same_, plan_a[0][0]: (7, 3)}, set())
    assert "a=d" not in ui.select_images_out(plan_a, sel_art, {}, {i for i, _, _ in plan_a})


def test_select_title_plan_holds_the_banner_id_of_its_shape(sel_art):
    sel_art, _ = sel_art
    sel_banner = (60, 7, 4)
    assert ui.select_title_plan(sel_art, sel_banner, True) == [(art.select_banner_id(4), 60, 7)]
    assert ui.select_title_plan(None, sel_banner, True) == []
    assert ui.select_title_plan(sel_art, sel_banner, False) == []
    assert ui.select_title_plan(sel_art, (88, 10, 6), True)[0][0] == art.select_banner_id(6)


def test_select_screen_with_art_opens_with_the_banner_rows():
    sel_title = [art.image_row(art.select_banner_id(4), r, 60) for r in range(7)]
    sel_rows = render.render_select(sel_ros, sel_towns, done["pane"], 80, 24, None, None, sel_title)
    assert sel_rows[:7] == [t + " " * 20 for t in sel_title]
    assert len(sel_rows) == 24
    assert render.select_layout(24, 7)[3] == render.select_layout(24, 1)[3] - 6
    assert not any(
        art.image_row(art.select_banner_id(4), 0, 60) in r
        for r in render.render_select(sel_ros, sel_towns, done["pane"], 80, 8, None, None, sel_title)
    )


@pytest.fixture
def banners():
    sb_wide, sb_short, sb_narrow, sb_huge = (
        ui.select_banner(150, 40, 0.5),
        ui.select_banner(150, 16, 0.5),
        ui.select_banner(60, 40, 0.5),
        ui.select_banner(300, 60, 0.5),
    )
    return sb_wide, sb_short, sb_narrow, sb_huge


def test_select_banner_is_as_wide_as_the_screen_and_centred(banners):
    sb_wide, sb_short, sb_narrow, sb_huge = banners
    assert sb_wide
    assert sb_wide[0] <= 150
    assert sb_wide[1] <= 10
    assert abs(sb_wide[3] - (150 - sb_wide[0] - sb_wide[3])) <= 1
    assert sb_short is None
    assert sb_narrow
    assert sb_narrow[0] <= 60
    assert sb_huge
    assert sb_huge[0] <= len(art.DIAC)
    assert abs(sb_huge[3] - (300 - sb_huge[0] - sb_huge[3])) <= 1


def test_select_banner_only_when_the_roster_keeps_8_rows():
    sb_scan = [
        (w, h, r)
        for w in range(40, 301, 20)
        for h in range(8, 61)
        for r in (0.4, 0.5, 0.6)
        if ui.select_banner(w, h, r)
    ]
    assert ui.select_banner(100, 12, 0.5) is None
    assert sb_scan
    assert all(
        (
            render.select_layout(h, ui.select_banner(w, h, r)[1])[2]
            and render.select_layout(h, ui.select_banner(w, h, r)[1])[3] >= 8
            for w, h, r in sb_scan
        )
    )


def test_select_banner_plan_and_screen_size(sel_art, banners):
    sel_art, _ = sel_art
    sb_wide, sb_short, _, sb_huge = banners
    sb_title = [
        " " * sb_huge[3] + art.image_row(art.select_banner_id(sb_huge[2]), r, sb_huge[0]) for r in range(sb_huge[1])
    ]
    sb_rows = render.render_select(sel_ros, sel_towns, done["pane"], 300, 60, None, None, sb_title)
    assert ui.select_title_plan(sel_art, sb_short, True) == []
    assert ui.select_title_plan(sel_art, sb_wide, True)[0][0] == art.select_banner_id(sb_wide[2])
    assert len(sb_rows) == 60
    assert all(render.cw(strip(r)) == 300 for r in sb_rows)


def test_report_banner_sizes_are_unchanged_by_the_select_banner():
    assert ui.banner_cells(120, 0.5) == (84, 6, 7)
    assert ui.banner_cells(80, 0.5) == (48, 6, 4)


def test_select_screen_without_art_has_no_placeholders():
    assert PH not in "".join(srows_of(180, 47, "%2"))
    assert PH in "".join(srows_of(180, 47, "%2", srep, True))


def test_select_screen_every_height_gives_that_many_rows():
    assert all(
        len(o_) == hh and all(common.cw(strip(r)) == 80 for r in o_) and (("j/k" in strip(o_[-1])) == (hh >= 2))
        for hh in range(1, 41)
        for o_ in [srows_of(80, hh, "%9")]
    )


def hround(n, task, replied=True):
    return {
        "task": task,
        "agent": "codex",
        "asked_at": 1000.0,
        "replied_at": 1095.0 if replied else None,
        "asked": "20261101T000000Z",
        "rc": 0 if replied else None,
        "dir": f"/s/round-{n:03d}",
    }


hist = ([hround(1, "修好登入頁面的錯誤訊息顯示"), hround(2, "review", False)], [("清理工作樹的長名稱任務", "/r/wt/x")])


def hpreview(pane, w, history=hist, at=None):
    i = next(i for i, (_, a, _) in enumerate(srs) if a["pane"] == pane)
    return render.select_preview(srs, sst, i, w, 30, srep, 4000.0, [], history, at)


def test_select_preview_history_rows_are_exactly_the_preview_width_with_cjk_tasks():
    for w in range(18, 61):
        rows = render.select_history(hist, w, "/s/round-001")
        assert {common.cw(strip(r)) for r in rows[1:]} == {w}, w
        assert strip(rows[3]).startswith("wt left: ")


def test_select_preview_history_shows_task_agent_took_or_no_reply():
    rows = [strip(r) for r in hpreview("%1", 60)]
    at = rows.index("past rounds".ljust(60))
    assert rows[at + 1].startswith("修好登入頁面的錯誤訊息顯示 · codex · 1m 35s")
    assert rows[at + 2].startswith("review · codex · no reply")
    assert rows[at + 3].startswith("wt left: 清理工作樹的長名稱任務")


def test_select_preview_highlights_only_the_picked_round():
    rows = hpreview("%1", 60, at="/s/round-002")
    at = next(i for i, r in enumerate(rows) if strip(r).startswith("past rounds"))
    assert [r.startswith(render.bg("sel")) for r in rows[at + 1 : at + 3]] == [False, True]


def test_select_preview_has_no_history_for_crew_or_a_lead_without_rounds():
    assert not any("past rounds" in strip(r) for r in hpreview("%10", 60))
    assert hpreview("%1", 60, ([], [])) == hpreview("%1", 60, None)


def test_select_preview_scrolls_so_the_picked_round_is_on_screen():
    five = ([hround(n, f"task{n}") for n in range(1, 6)], [])
    i = next(i for i, (_, a, _) in enumerate(srs) if a["pane"] == "%2")
    rows = [strip(r) for r in render.select_preview(srs, sst, i, 60, 4, srep, 4000.0, [], five, "/s/round-005")]
    assert len(rows) == 4
    assert rows[-1].startswith("task5 · codex")
