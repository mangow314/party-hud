# pyright: reportOptionalSubscript=false
"""Tests index results they expect to exist; a None there fails the test, so the Optional check is off."""

import pytest

from party_hud import art, collect, sidebars, ui

NEW_PANE_USAGE = (
    "new-pane (newp) [-AbCDefhIkKLMOPvWZ] [-c start-directory] [-F format] [-t target-pane] [shell-command]"
)
SPLIT_USAGE = "split-window (splitw) [-bdefhIPvZ] [-c start-directory] [-l size] [-t target-pane] [shell-command]"


def fake_tmux(calls, usage, rows="%1 1 s1 r\n%2 0 s r\n"):
    def run(*a):
        calls.append(a)
        if a[0] == "list-commands":
            return usage
        if a[0] == "list-panes":
            return rows
        return "%9\n" if a[0] in ("new-pane", "split-window") else ""

    return run


def first_open(calls):
    return next(c for c in calls if c[0] in ("new-pane", "split-window"))


@pytest.fixture
def opened(monkeypatch):
    """open_report_pane("@1", "%7") on a tmux whose usage lists new-pane with -O: the tmux calls."""
    calls = []
    monkeypatch.setattr(sidebars, "_new_pane", None)
    monkeypatch.setattr(sidebars, "tmux", fake_tmux(calls, NEW_PANE_USAGE))
    sidebars.open_report_pane("@1", "%7")
    return calls


def test_report_pane_floats_with_new_pane_beside_the_first_non_sidebar_pane(opened):
    c = first_open(opened)
    assert c[0] == "new-pane"
    assert all(f in c for f in ("-x80%", "-y80%", "-X10%", "-Y10%"))
    assert "-O" not in c
    assert "-D" not in c
    assert c[c.index("-t") + 1] == "%2"
    assert c[-1].endswith("--report %7")


def test_report_pane_is_marked_and_allows_passthrough_in_one_call(opened):
    calls = opened
    assert (
        "set-option",
        "-p",
        "-t",
        "%9",
        "@party_report",
        "1",
        ";",
        "set-option",
        "-p",
        "-t",
        "%9",
        "allow-passthrough",
        "on",
    ) in calls
    assert not any("window-style" in c or "window-active-style" in c for c in calls)


def test_the_new_pane_answer_is_cached(opened):
    calls = opened
    calls.clear()
    sidebars.open_report_pane("@1", "")
    assert not any(c[0] == "list-commands" for c in calls)
    assert first_open(calls)[0] == "new-pane"
    assert first_open(calls)[-1].endswith("party.py --report")


@pytest.mark.parametrize("usage", [SPLIT_USAGE, ""], ids=["no O flag", "command unknown"])
def test_tmux_without_new_pane_splits_the_window_in_half(monkeypatch, usage):
    calls = []
    monkeypatch.setattr(sidebars, "_new_pane", None)
    monkeypatch.setattr(sidebars, "tmux", fake_tmux(calls, usage))
    sidebars.open_report_pane("@1", "%7")
    c = first_open(calls)
    assert c[0] == "split-window"
    assert c[1:4] == ("-h", "-l", "50%")
    assert "new-pane" not in [x[0] for x in calls]
    assert c[c.index("-t") + 1] == "%2"


def test_report_and_select_cols_at_two_cell_ratios():
    assert (
        sidebars.report_cols(0.5),
        sidebars.select_cols(0.5),
        sidebars.report_cols(0.452),
        sidebars.select_cols(0.452),
    ) == (105, 82, 113, 90)


@pytest.fixture
def sel_open(monkeypatch):
    """open_report_pane in a window win_w wide whose cells are cell pixels: the command that opened it."""
    monkeypatch.setattr(sidebars, "_new_pane", True)

    def run(win_w, select=True, cell="19,42"):
        calls = []

        def tmux(*a):
            calls.append(a)
            if a[0] == "display-message":
                return win_w + ("," + cell if cell else "")
            if a[0] == "list-panes":
                return "%1 1 s r\n"
            return "%9\n" if a[0] == "new-pane" else ""

        monkeypatch.setattr(sidebars, "tmux", tmux)
        sidebars.open_report_pane("@1", "", select)
        return first_open(calls)

    return run


def test_select_pane_is_select_cols_wide_and_centred(sel_open):
    c = sel_open("200")
    assert c[c.index("-x90") + 1] == "-y80%"
    assert "-X55" in c
    assert "-Y10%" in c


def test_select_pane_without_cell_size_is_82_columns(sel_open):
    c = sel_open("200", cell="")
    assert c[c.index("-x82") + 1] == "-y80%"
    assert "-X59" in c


def test_select_pane_with_cell_size_0_is_82_columns(sel_open):
    c = sel_open("200", cell="0,0")
    assert "-x82" in c
    assert "-X59" in c


def test_select_pane_is_no_wider_than_the_window(sel_open):
    c = sel_open("60")
    assert "-x60" in c
    assert "-X0" in c


def test_report_pane_with_unreadable_window_width_keeps_80_percent(sel_open):
    c = sel_open("", select=False)
    assert c[1:5] == ("-x80%", "-y80%", "-X10%", "-Y10%")


def test_report_pane_is_report_cols_wide_in_a_wide_window(sel_open):
    c = sel_open("400", select=False)
    assert c[1:5] == ("-x113", "-y80%", "-X143", "-Y10%")


def test_report_pane_without_cell_size_is_105_columns(sel_open):
    c = sel_open("400", select=False, cell="")
    assert c[1:5] == ("-x105", "-y80%", "-X147", "-Y10%")


def test_report_pane_with_a_cell_size_that_is_not_a_number_is_105_columns(sel_open):
    c = sel_open("400", select=False, cell="x,0")
    assert c[1:5] == ("-x105", "-y80%", "-X147", "-Y10%")


def test_report_pane_in_a_100_column_window_is_80_percent(sel_open):
    c = sel_open("100", select=False)
    assert c[1:5] == ("-x80", "-y80%", "-X10", "-Y10%")


def test_select_pane_with_unreadable_window_width_keeps_80_percent(sel_open):
    c = sel_open("n/a")
    assert "-x80%" in c
    assert "-X10%" in c


@pytest.fixture
def fit(monkeypatch):
    """fit_report_pane("%9", select) on a pane tmux describes as flag,win_w,50,cell: the calls besides display-message."""

    def run(flag, select, new=True, win_w=200, cell="19,42"):
        calls = []
        monkeypatch.setattr(sidebars, "_new_pane", new)
        monkeypatch.setattr(
            sidebars,
            "tmux",
            lambda *a: calls.append(a) or (f"{flag},{win_w},50,{cell}" if a[0] == "display-message" else ""),
        )
        sidebars.fit_report_pane("%9", select)
        return [c for c in calls if c[0] != "display-message"]

    return run


def test_fit_pane_resizes_a_floating_pane_to_the_select_screen(fit):
    assert fit("1", True) == [
        ("resize-pane", "-t", "%9", "-x", "90", "-y", "40", ";", "move-pane", "-t", "%9", "-X", "55", "-Y", "5")
    ]


def test_fit_pane_without_cell_size_uses_82_columns(fit):
    assert fit("1", True, cell=",") == [
        ("resize-pane", "-t", "%9", "-x", "82", "-y", "40", ";", "move-pane", "-t", "%9", "-X", "59", "-Y", "5")
    ]
    assert fit("1", True, cell="0,0") == fit("1", True, cell=",")


def test_fit_pane_report_page_in_a_100_column_window(fit):
    assert fit("1", False, win_w=100) == [
        ("resize-pane", "-t", "%9", "-x", "80", "-y", "40", ";", "move-pane", "-t", "%9", "-X", "10", "-Y", "5")
    ]


def test_report_and_select_span():
    assert sidebars.report_span(400, 0.5) == (105, 147)
    assert sidebars.report_span(100, 0.5) == (80, 10)
    assert sidebars.select_span(200, 0.5) == (82, 59)


def test_fit_pane_report_page_in_a_400_column_window(fit):
    assert fit("1", False, win_w=400) == [
        ("resize-pane", "-t", "%9", "-x", "113", "-y", "40", ";", "move-pane", "-t", "%9", "-X", "143", "-Y", "5")
    ]
    assert fit("1", False, win_w=400, cell=",") == [
        ("resize-pane", "-t", "%9", "-x", "105", "-y", "40", ";", "move-pane", "-t", "%9", "-X", "147", "-Y", "5")
    ]


@pytest.mark.parametrize("r_", [0.4, 0.452, 0.5, 0.55, 0.6])
def test_select_banner_fills_its_column(r_):
    sb = ui.select_banner(sidebars.select_cols(r_) - 1, 50, r_)
    assert sb[1:3] == (10, 4)
    assert abs(sb[0] - (sidebars.select_cols(r_) - 1)) <= 1


@pytest.mark.parametrize("r_", [0.4, 0.452, 0.5])
def test_report_banner_fills_its_column(r_):
    right = sidebars.report_cols(r_) - 1 - ui.SPLIT_SIDE_COLS - ui.SPLIT_GAP
    bc = ui.banner_cells(sidebars.report_cols(r_) - 1, r_)
    assert abs(bc[0] - right) <= 1
    assert bc[1:] == (6, 6)


def test_the_widest_report_pane_still_draws_the_split_page():
    assert all(sidebars.report_cols(r_) - 3 >= art.SPLIT_MIN_WIDTH for r_ in (0.4, 0.452, 0.5, 0.55, 0.6, 0.65))


def shape_ok(cols_in, rows_max, r_, b):
    cols, rows, k = b
    a = cols_in * r_ / rows
    return (
        rows == max(1, min(rows_max, round(min(len(art.DIAC), cols_in) * r_ / 4)))
        and cols <= cols_in
        and cols - rows * k / r_ <= 1 + 1e-9
        and abs(a - k) <= min(abs(a - j) for j in art.BANNER_RATIOS) + 1e-9
    )


def test_report_banner_shape_follows_the_split_width():
    fit_scan = [
        (w - ui.SPLIT_SIDE_COLS - ui.SPLIT_GAP, r_, b)
        for r_ in (0.4, 0.452, 0.5, 0.55, 0.6)
        for w in [*range(100, 260, 7), sidebars.report_cols(r_) - 1]
        for b in [ui.banner_cells(w, r_)]
    ]
    assert all((shape_ok(min(len(art.DIAC), w), ui.REPORT_BANNER_MAX_ROWS, r_, b) for w, r_, b in fit_scan))


def test_select_banner_shape_follows_the_width_and_is_centred():
    sel_scan = [
        (w, r_, b)
        for r_ in (0.4, 0.452, 0.5, 0.55, 0.6)
        for w in [*range(60, 200, 7), sidebars.select_cols(r_) - 1]
        for b in [ui.select_banner(w, 50, r_)]
        if b
    ]
    assert sel_scan
    assert all((shape_ok(w, ui.SELECT_BANNER_MAX_ROWS, r_, b[:3]) for w, r_, b in sel_scan))
    assert all((b[3] == (w - b[0]) // 2 and b[0] <= w for w, r_, b in sel_scan))


def test_banners_one_or_two_columns_short_keep_their_size():
    assert ui.select_banner(87, 50, 19 / 42)[:3] == (87, 10, 4)
    assert ui.banner_cells(136, 19 / 42) == (104, 6, 8)


def test_fit_pane_leaves_a_pane_that_is_not_floating_alone(fit):
    assert fit("0", True) == []
    assert fit("1", True, new=False) == []


def test_tidy_counts_a_report_pane_as_a_sidebar(monkeypatch):
    killed = []
    monkeypatch.setattr(
        sidebars,
        "tmux",
        lambda *a: (
            "%1 @1 s1 r\n%2 @1 s r1\n%3 @2 s1 r\n%4 @2 s r\n" if a[0] == "list-panes" else killed.append(a[2]) or ""
        ),
    )
    sidebars.tidy()
    assert sorted(killed) == ["%1", "%2"]


def test_sidebar_dragged_below_30_is_remembered_as_30(monkeypatch):
    calls = []

    def tmux(*a):
        calls.append(a)
        if a[0] == "show-option":
            return "34"
        return "%9 1 22\n%8 1 34\n" if a[0] == "list-panes" else ""

    monkeypatch.setattr(sidebars, "tmux", tmux)
    sidebars.remember_width()
    assert ("set-option", "-g", "@party_sidebar_width", "30") in calls
    assert ("resize-pane", "-t", "%9", "-x", "30") in calls
    assert ("resize-pane", "-t", "%8", "-x", "30") in calls


def test_window_switch_resets_that_windows_sidebar_width(monkeypatch):
    calls = []

    def tmux(*a):
        calls.append(a)
        return {"display-message": "@5\n", "show-option": "46", "list-panes": "%7 1 36\n%8 0 175\n"}.get(a[0], "")

    monkeypatch.setattr(sidebars, "tmux", tmux)
    sidebars.nudge()
    assert ("resize-pane", "-t", "%7", "-x", "46") in calls
    assert not any(c[:3] == ("resize-pane", "-t", "%8") for c in calls)


def restore_tmux(calls, restoring, sidebar_on=""):
    sep = collect.FIELD_SEP
    places = {
        "a:1.1": sep.join(["a:1.1", "%1", ""]),
        "a:2.1": sep.join(["a:2.1", "%5", ""]),
        "a:3.1": sep.join(["a:3.1", "%6", "1"]),
        "@1": "a\t" + restoring,
        "@2": "a\t" + restoring,
    }

    def fake(*a):
        calls.append(a)
        if a[0] == "show-option":
            return restoring if a[2] == "@party_restoring" else sidebar_on
        if a[0] == "display-message":
            return (
                places.get(a[3], sep.join(["a:2.0", "%7", ""])) + "\n"
            )  # a missing place: tmux answers for the active pane
        return {
            "list-windows": "@1\n@2\n",
            "list-panes": "%1\n%2\n" if "-a" in a else "1\n",
            "split-window": "%9\n",
        }.get(a[0], "")

    return fake


def test_restore_begin_remembers_the_panes_that_exist_now(monkeypatch):
    calls = []
    monkeypatch.setattr(sidebars, "tmux", restore_tmux(calls, ""))
    sidebars.restore_begin()
    assert calls[-1] == ("set-option", "-g", "@party_restoring", "%1 %2")


@pytest.fixture
def restored(monkeypatch):
    """restore_end over five places while @party_restoring holds %1 %2: (rc, tmux calls)."""
    calls = []
    monkeypatch.setattr(sidebars, "tmux", restore_tmux(calls, "%1 %2"))
    rc = sidebars.restore_end(["a:1.1", "a:2.1", "a:3.1", "gone:1.1", ""])[0]
    return rc, calls


def test_restore_end_turns_only_a_pane_made_during_the_restore_into_a_sidebar(restored):
    rc, calls = restored
    respawned = [c[3] for c in calls if c[0] == "respawn-pane"]
    assert rc == 0
    assert respawned == ["%5"]
    assert calls[calls.index(("respawn-pane", "-k", "-t", "%5", sidebars.EXE + " --sidebar")) - 1][-6:] == (
        ";",
        "select-pane",
        "-t",
        "%5",
        "-T",
        "party-hud",
    )


def test_restore_end_releases_ensure_then_installs_the_hooks(restored):
    _, calls = restored
    unset = calls.index(("set-option", "-gu", "@party_restoring"))
    assert unset > calls.index(("respawn-pane", "-k", "-t", "%5", sidebars.EXE + " --sidebar"))
    assert any(c[:4] == ("set-option", "-g", "@party_sidebar_on", "1") for c in calls[unset:])


def test_ensure_during_a_restore_adds_no_sidebar(restored):
    _, calls = restored
    calls.clear()
    sidebars.ensure("@1")
    assert not any(c[0] == "split-window" for c in calls)


def test_restore_end_without_restore_begin_exits_2(monkeypatch):
    calls = []
    monkeypatch.setattr(sidebars, "tmux", restore_tmux(calls, ""))
    assert sidebars.restore_end(["a:2.1"])[0] == 2
    assert [c[0] for c in calls] == ["show-option"]
