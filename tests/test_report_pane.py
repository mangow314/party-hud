"""The report pane and the select screen run in a child process on a pty: keys in, terminal output read back."""

import fcntl
import itertools
import json
import os
import pty
import re
import select as _sel
import signal
import struct
import subprocess
import sys
import termios as _tm
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from screen import strip

from party_hud import collect, render, ui

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sidebar.json")
REAL_PNG = os.path.join(ROOT, "art", "label-took.png")

child = """
import sys
sys.path.insert(0, %r)
from party_hud import claude_log, codex_log, collect, processes, ui
ui.get_snapshot = lambda f=None: collect.collect(%r)
ui.report_for = lambda a: {"text": "\\n".join(f"L{n}" for n in range(%d)), "start": 1, "end": 2}
ui.tmux = lambda *a: print("TMUX", a, flush=True) or ("off" if "@party_anim" in a else "")
ui.run_report("%%1")
print("EXITED", flush=True)
"""


def report_session(
    keys,
    rows=10,
    lines=60,
    draws=None,
    src=child,
    resizes=(),
    gap=0.0,
    hold=0.0,
    runtime=None,
    marker=b"\x1b[J",
    crashes=False,
):
    """Run src on a pty rows x 60, send keys (each after draws[i] markers, one per screen), and return everything it wrote.
    runtime: the child's XDG_RUNTIME_DIR (where seen.json goes); None keeps the test process's.
    crashes: the child is expected to fail; otherwise it must print EXITED and exit 0."""
    m, sl = pty.openpty()
    fcntl.ioctl(sl, _tm.TIOCSWINSZ, struct.pack("HHHH", rows, 60, 0, 0))
    env = dict(os.environ, TMUX_PANE="%99", **({"XDG_RUNTIME_DIR": str(runtime)} if runtime else {}))
    p = subprocess.Popen(
        [sys.executable, "-c", src % (ROOT, FIXTURE, lines)], stdin=sl, stdout=sl, stderr=sl, env=env, close_fds=True
    )
    os.close(sl)
    out = b""

    def read_until(marker, n):
        nonlocal out
        for _ in range(100):
            if out.count(marker) >= n:
                return
            if _sel.select([m], [], [], 0.1)[0]:
                try:
                    out += os.read(m, 65536)
                except OSError:
                    return

    if resizes:
        read_until(b"\x1b[J", 1)
        for r in resizes:
            fcntl.ioctl(m, _tm.TIOCSWINSZ, struct.pack("HHHH", r, 60, 0, 0))
            p.send_signal(signal.SIGWINCH)
            time.sleep(gap)
        time.sleep(0.5)
        drained = time.monotonic() + 10
        while time.monotonic() < drained and _sel.select([m], [], [], 0.2)[0]:
            out += os.read(m, 65536)
    for key, n in zip(keys, draws or range(1, len(keys) + 1)):
        if not resizes:
            read_until(marker, n)
        # a pty holds little unread output (far less on macOS than on Linux); unread, the child blocks in its write
        held = time.monotonic() + hold
        while time.monotonic() < held:
            if _sel.select([m], [], [], max(0.0, held - time.monotonic()))[0]:
                try:
                    out += os.read(m, 65536)
                except OSError:
                    break
        os.write(m, key)
    read_until(b"EXITED", 1)
    rc = p.wait(timeout=5)
    os.close(m)
    text = out.decode(errors="ignore")
    if not crashes:
        assert rc == 0, text[-2000:]
        assert "EXITED" in text
    return text


def seen_file(runtime):
    return os.path.join(str(runtime), "party-hud", "seen.json")


def read_json(path):
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def once():
    return report_session([b"\r"])


@pytest.fixture(scope="module")
def twice():
    return report_session([b"n", b"q"])


def test_report_pane_draws_only_the_first_rows_with_mouse_reporting(once):
    assert "L0" in once
    assert "L59" not in once
    assert "\x1b[?1003h" in once
    assert once.rindex("\x1b[?1003l") > once.index("switch-client")


def test_report_pane_uses_no_copy_mode_or_history(once):
    assert "copy-mode" not in once
    assert "clear-history" not in once
    assert "\x1b[3J" not in once


def test_report_pane_enters_and_leaves_the_alternate_screen(once):
    assert once.count("\x1b[?1049h") == 1
    assert once.count("\x1b[?1049l") == 1
    assert once.index("\x1b[?1049h") < once.index("L0")
    assert once.rindex("\x1b[?1049l") > once.index("switch-client")


def test_report_pane_leaves_the_alternate_screen_when_it_fails():
    boom = report_session(
        [], src=child.replace("ui.run_report", "ui.report_for = lambda a: 1 / 0\nui.run_report"), crashes=True
    )
    assert boom.count("\x1b[?1049h") == 1
    assert boom.rindex("\x1b[?1049l") > boom.index("\x1b[?1049h")
    assert "ZeroDivisionError" in boom


rd = child.replace(
    "ui.run_report",
    "ag = ui.get_snapshot()['towns'][0]['agents'][0]\nui.report_queue = lambda towns, pane=None, window=None: [('A', dict(ag, pane='%%1', round=3))]\nui.run_report",
    1,
)


@pytest.fixture(scope="module")
def finished(tmp_path_factory):
    """The finished-report page of round 3, then q: (output, seen.json path)."""
    runtime = tmp_path_factory.mktemp("finished")
    return report_session([b"q"], src=rd, runtime=runtime), seen_file(runtime)


def test_finished_report_page_exits_cleanly(finished):
    rd_out, _ = finished
    assert "EXITED" in rd_out
    assert "Traceback" not in rd_out


def test_showing_a_finished_report_records_its_round_as_read(finished):
    _, sf = finished
    assert read_json(sf) == {"%1": 3}


def test_a_report_of_round_3_on_screen_while_round_4_finishes_leaves_it_done(finished):
    _, sf = finished
    ts = [{"agents": [{"pane": "%1", "status": "idle", "focus": False}]}]
    collect.mark_unseen(ts, {"%1": {"status": "working", "unseen": False, "round": 3}}, read_json(sf))
    assert ts[0]["agents"][0]["status"] == "done"
    assert ts[0]["agents"][0]["round"] == 4


@pytest.fixture(scope="module")
def live_page(tmp_path_factory):
    runtime = tmp_path_factory.mktemp("live")
    rl = rd.replace(
        "ui.run_report(",
        "ui.report_for = lambda a: {'live': True, 'text': 'x', 'start': 1, 'end': 2}\nui.run_report(",
        1,
    )
    return report_session([b"q"], src=rl, runtime=runtime), seen_file(runtime)


def test_live_page_exits_cleanly(live_page):
    rl_out, _ = live_page
    assert "EXITED" in rl_out
    assert "Traceback" not in rl_out


def test_live_page_records_nothing(live_page):
    _, sf = live_page
    assert not os.path.exists(sf)


@pytest.fixture(scope="module")
def stale_round(tmp_path_factory):
    runtime = tmp_path_factory.mktemp("stale")
    stale = rd.replace(
        "ui.run_report",
        """ag = ui.get_snapshot()["towns"][0]["agents"][0]
mk = lambda p, r: dict(ag, pane=p, round=r)
ui.report_queue = lambda towns, pane=None, window=None: [('A', mk('%%1', 1)), ('A', mk('%%2', 3))]
ui.get_snapshot = lambda f=None: {"towns": [{"agents": [mk('%%1', 1), mk('%%2', 5)]}]}
ui.run_report""",
        1,
    )
    return report_session([b"n", b"q"], src=stale, runtime=runtime), seen_file(runtime)


def test_stale_round_page_exits_cleanly(stale_round):
    stale_out, _ = stale_round
    assert "EXITED" in stale_out
    assert "Traceback" not in stale_out


def test_n_to_a_member_with_a_newer_round_records_the_round_on_screen(stale_round):
    _, sf = stale_round
    assert read_json(sf) == {"%1": 1, "%2": 5}


def test_enter_jumps_to_the_members_pane_and_exits(once):
    assert "TMUX ('switch-client', '-t'" in once
    assert "EXITED" in once


def test_the_callers_window_is_asked_by_the_panes_own_tmux_pane():
    seen_win = report_session(
        [b"q"],
        marker=b"close",
        src=child.replace(
            "ui.run_report",
            "ui.report_queue = lambda t, p=None, w=None: print('WIN', w, flush=True) or []\nui.run_report",
            1,
        ),
    )
    assert "TMUX ('display-message', '-p', '-t', '%99', '#{window_id}')" in seen_win


select_child = child.replace('ui.run_report("%%1")', "ui.run_menu()")


@pytest.fixture(scope="module")
def sel_q(tmp_path_factory):
    runtime = tmp_path_factory.mktemp("select")
    return report_session([b"q"], rows=60, src=select_child, runtime=runtime), seen_file(runtime)


def test_select_screen_draws_every_member_and_q_ends_it(sel_q):
    sel_q, _ = sel_q
    names = [a["name"] for t in collect.collect(FIXTURE)["towns"] for a in t["agents"]]
    assert "EXITED" in sel_q
    assert "Traceback" not in sel_q
    assert all(n[:4] in sel_q for n in names)
    assert "PARTY SELECT" in sel_q


def test_select_screen_only_looking_records_nothing_and_restores_the_terminal(sel_q):
    sel_q, sf = sel_q
    assert not os.path.exists(sf)
    assert sel_q.count("\x1b[?1049h") == 1
    assert sel_q.count("\x1b[?1049l") == 1
    assert sel_q.rindex("\x1b[?1003l") > sel_q.index("\x1b[?1003h")


def test_select_screen_enter_opens_the_report_and_q_ends_the_program():
    sel_open = report_session([b"\r", b"q"], src=select_child)
    assert "EXITED" in sel_open
    assert "Traceback" not in sel_open
    assert "L0" in sel_open[sel_open.index("PARTY SELECT") :]
    assert "display-menu" not in sel_open


trace_child = select_child.replace(
    "ui.run_menu()",
    """_rs, _rr = ui.run_select, ui.run_report
ui.run_select = lambda sel=None, fixture=None, images=None: print("TRACE_SELECT", sel, flush=True) or _rs(sel, fixture, images)
ui.run_report = lambda pane=None, fixture=None, back=False, images=None: print("TRACE_REPORT", pane, back, flush=True) or _rr(pane, fixture, back, images)
ui.run_menu()""",
)


@pytest.fixture(scope="module")
def roster():
    """The fixture towns, the first select row's pane, and where n then h should leave the cursor."""
    tw = collect.collect(FIXTURE)["towns"]
    first = render.select_roster(tw)[0][1]["pane"]
    nxt = ui.report_queue(tw, first, "")[1][1]["pane"]
    nxt_expect = nxt if nxt in [a["pane"] for _, a, _ in render.select_roster(tw)] else first
    return tw, first, nxt_expect


def test_select_h_on_the_report_page_returns_to_the_select_screen(roster):
    _, first, _ = roster
    back_h = report_session([b"\r", b"h", b"q"], src=trace_child)
    assert "EXITED" in back_h
    assert "Traceback" not in back_h
    assert back_h.count("PARTY SELECT") == 2
    assert f"TRACE_SELECT {first}" in back_h
    assert back_h.index("TRACE_REPORT") < back_h.rindex("PARTY SELECT")
    assert back_h.count("\x1b[?1049h") == 3
    assert back_h.count("\x1b[?1049l") == 3


def test_select_after_h_a_member_can_be_opened_again():
    again = report_session([b"\r", b"h", b"\r", b"h", b"q"], src=trace_child)
    assert "EXITED" in again
    assert "Traceback" not in again
    assert again.count("TRACE_REPORT") == 2
    assert again.count("TRACE_SELECT") == 3


def test_select_n_then_h_returns_with_the_cursor_on_the_member_n_moved_to(roster):
    _, _, nxt_expect = roster
    nh = report_session([b"\r", b"n", b"h", b"q"], src=trace_child)
    assert "EXITED" in nh
    assert "Traceback" not in nh
    assert f"TRACE_SELECT {nxt_expect}" in nh[nh.index("TRACE_REPORT") :]


def test_select_q_on_the_report_page_ends_the_program():
    sel_close = report_session([b"\r", b"q"], src=trace_child)
    assert "EXITED" in sel_close
    assert "Traceback" not in sel_close
    assert sel_close.count("TRACE_SELECT") == 1
    assert sel_close.count("TRACE_REPORT") == 1
    assert sel_close.count("PARTY SELECT") == 1


def test_select_and_report_send_no_image_twice():
    share_inject = """ui.report_queue = lambda towns, pane=None, window=None: [("A", {"pane": "%%1", "round": 0})]
ui.art_supported = lambda *a: True
def counting_load_art():
    print("LOAD_ART", flush=True)
    return {11: (PNGPATH, 6, 3), 7: (PNGPATH, 10, 5)}
ui.load_art = counting_load_art
ui.portrait_id = lambda a: -1
ui.fit_report_pane = lambda *a: None
ui.select_banner = lambda *a: None
ui.select_image_plan = lambda cards, art: [(11, 6, 3)]
ui.report_image_plan = lambda *a: [(11, 6, 3), (7, 10, 5)]
ui.report_parts = lambda a, sq, rep, peek, width, *r: ([], [("L" + str(n)).ljust(width) for n in range(80)])
ui.run_menu()""".replace("PNGPATH", repr(REAL_PNG))
    sh = report_session([b"\r", b"h", b"\r", b"q"], rows=60, src=select_child.replace("ui.run_menu()", share_inject, 1))
    sh_second = sh[[m.start() for m in re.finditer(re.escape("\x1b[?1049h"), sh)][3] :]
    assert "EXITED" in sh
    assert "Traceback" not in sh
    assert sh.count("\x1b[?1049h") == 4
    assert "a=T,U=1,f=100,i=7," in sh
    assert all(sh.count(f"a=T,U=1,f=100,i={i},") == 1 for i in (11, 7))
    assert "a=d" not in sh_second
    assert sh.count("LOAD_ART") == 1
    assert sh.count("\x1b[?25h\x1b[?1049l") == 4


def test_directly_opened_report_page_has_no_h():
    direct_h = report_session([b"h", b"q"], rows=80, draws=[1, 1], hold=0.3)
    assert "EXITED" in direct_h
    assert "Traceback" not in direct_h
    assert direct_h.count("\x1b[?1049h") == 1
    assert "close" in strip(direct_h)
    assert "back" not in strip(direct_h)


def test_report_page_from_the_select_screen_shows_h(roster):
    tw, _, _ = roster
    from_sel = report_session([b"\r", b"q"], rows=80, src=trace_child)
    assert "h back" in strip(from_sel)
    assert "h back" in strip(render.render_report(tw[0]["agents"][0], "S", None, [], 60, hints="report_back"))
    assert any(
        "h back" in strip(r)
        for r in render.report_parts(tw[0]["agents"][0], "S", None, [], 150, art=True, hints="report_back")[0]
    )
    assert "h back" not in strip(render.render_report(tw[0]["agents"][0], "S", None, [], 60))


def test_select_g_does_nothing():
    sel_g = report_session([b"g", b"q"], draws=[1, 1], src=select_child, hold=0.3)
    assert "switch-client" not in sel_g
    assert "EXITED" in sel_g
    assert "L0" not in sel_g


def test_n_draws_the_next_report_in_place(twice):
    assert "\x1b[2J" not in twice
    assert twice.count("L0") == 2


def test_select_screen_redraws_at_the_new_size_as_soon_as_it_is_resized():
    src = select_child.replace("ui.run_menu()", "ui.select_wait = lambda *a: 30.0\nui.run_menu()", 1)
    sr = report_session([b"q"], rows=30, resizes=[24], src=src)
    last = sr[sr.rindex("\x1b[H") : sr.index("\x1b[J", sr.rindex("\x1b[H"))]
    assert "EXITED" in sr
    assert sr.count("\x1b[J") == 2
    assert last.count("\n") == 23
    assert "\x1b[2J" not in sr


@pytest.fixture(scope="module")
def resized():
    rs = report_session([b"q"], rows=30, resizes=[29, 28, 27, 26, 25, 24, 23, 22, 21, 20] * 2, gap=0.005)
    return rs, rs.count("\x1b[J") - 1


def test_a_resize_redraws_in_place(resized):
    rs, _ = resized
    assert "\x1b[2J" not in rs
    assert "\x1b[3J" not in rs


def test_a_resize_burst_redraws_a_bounded_number_of_times(resized):
    _, rs_draws = resized
    assert 2 <= rs_draws <= 8


def test_after_the_burst_the_last_redraw_has_the_final_size(resized):
    rs, _ = resized
    last = rs[rs.rindex("\x1b[H") : rs.index("\x1b[J", rs.rindex("\x1b[H"))]
    assert last.count("\n") == 19


anim_src = child.replace('"\\n".join(f"L{n}"', '"\\n\\n".join(f"L{n}"').replace(
    'or ("off" if "@party_anim" in a else "")', 'or ""'
)


def test_a_key_during_the_opening_animation_draws_the_whole_page():
    aq = report_session([b"q"], rows=16, lines=12, src=anim_src)
    a_first = aq[aq.index("\x1b[H") : aq.index("\x1b[H", aq.index("\x1b[H") + 1)]
    a_last = aq[aq.rindex("\x1b[H") :]
    assert aq.count("\x1b[H") == 2
    assert "L1" in a_first
    assert "L3" not in a_first
    assert "L3" in a_last
    assert "EXITED" in aq


def test_n_during_the_animation_changes_page_at_once():
    an = report_session([b"n", b"q"], rows=16, lines=12, draws=[1, 3], src=anim_src)
    assert "report 2/3" in an
    assert an.count("\x1b[H") == 4
    assert "EXITED" in an


first_img = """ag = ui.get_snapshot()["towns"][0]["agents"][0]
ui.report_queue = lambda towns, pane=None, window=None: [("A", dict(ag, pane="%%1", round=0))]
ui.art_supported = lambda *a: True
ui.load_art = lambda: {"k": 1}
ui.report_images = lambda *a: "<IMG>"
ui.report_image_plan = lambda *a: []
ui.run_report"""


def test_images_are_sent_with_the_first_animation_frame():
    wf = report_session([b"q"], rows=16, lines=12, hold=0.6, src=anim_src.replace("ui.run_report", first_img, 1))
    wf_none = report_session(
        [b"q"], rows=16, lines=12, hold=0.6, src=anim_src.replace("ui.run_report", first_img.replace("<IMG>", ""), 1)
    )
    assert wf.count("<IMG>") == 1
    assert wf.count("\x1b[H") == wf_none.count("\x1b[H") > 2
    assert wf.index("\x1b[H") < wf.index("<IMG>") < wf.index("\x1b[H", wf.index("\x1b[H") + 1)


art_inject = """ui.report_queue = lambda towns, pane=None, window=None: [("A", {"pane": "%%1", "round": 0})]
ui.art_supported = lambda *a: True
ui.load_art = lambda: {"k": 1}
ui.report_images = lambda *a: "<IMG r=%%d>" %% os.get_terminal_size(1).lines
ui.report_image_plan = lambda *a: []
ui.report_parts = lambda a, sq, rep, peek, width, *r: ([], [("L" + str(n)).ljust(width) for n in range(80)])
ui.run_report"""


def test_images_are_resent_once_after_a_resize_burst():
    ra = report_session(
        [b"q"],
        rows=30,
        resizes=[29, 28, 27, 26, 25, 24, 23, 22, 21, 20] * 2,
        gap=0.005,
        src=child.replace("ui.run_report", art_inject, 1).replace("import sys\n", "import os, sys\n", 1),
    )
    assert ra.count("<IMG") == 2
    assert ra.count("<IMG r=20>") == 1


still_inject = """import time
ag = ui.get_snapshot()["towns"][0]["agents"][0]
ui.report_queue = lambda towns, pane=None, window=None: [("A", dict(ag, pane="%%1", round=3))]
ui.report_for = lambda a: {"text": "x", "start": time.time() - 9, "end": time.time() - 5}
ui.report_parts = lambda a, sq, rep, peek, width, *r: (["left"], [("L" + str(n)).ljust(width) for n in range(3)])
ui.run_report"""


def test_a_time_tick_that_changes_no_row_writes_nothing():
    still = report_session([b"q"], rows=10, hold=3.0, src=child.replace("ui.run_report", still_inject, 1))
    assert "EXITED" in still
    assert still.count("\x1b[J") == 1


first_inject = """ui.report_queue = lambda towns, pane=None, window=None: [("A", {"pane": "%%1", "round": 0})]
ui.art_supported = lambda *a: True
ui.load_art = lambda: {"k": 1}
ui.report_images = lambda *a: ""
ui.report_image_plan = lambda *a: [(7, 10, 5)]
ui.portrait_id = lambda a: -1
ui.report_parts = lambda a, sq, rep, peek, width, *r: ([], [("L" + str(n)).ljust(width) for n in range(80)])
ui.run_report"""


def test_the_first_frame_deletes_the_unsent_image_id_once():
    fp = report_session([b"n", b"q"], src=child.replace("ui.run_report", first_inject, 1))
    assert fp.count("a=d,d=I,i=7") == 1
    assert fp.index("a=d,d=I,i=7") < fp.index("\x1b[H")


live_inject = first_inject.replace(
    "ui.report_image_plan = lambda *a: [(7, 10, 5)]",
    "ui.report_image_plan = lambda a, final, *r: [(7 if final else 8, 10, 5)]",
).replace(
    "ui.run_report",
    "ui.LIVE_REFRESH = 0.2\nui.report_for = lambda a: {'live': True, 'text': 'x', 'start': None, 'end': 2}\nui.refresh_live = lambda q, i: {'text': 'done', 'start': 1, 'end': 3}\nui.run_report",
    1,
)


def test_a_page_turning_final_deletes_the_new_banner_id_with_the_next_frame():
    lv = report_session([b"q"], draws=[2], src=child.replace("ui.run_report", live_inject, 1))
    assert "a=d,d=I,i=7" in lv
    assert lv.index("a=d,d=I,i=7") > lv.index("\x1b[H")
    assert lv.index("a=d,d=I,i=7") < lv.rindex("\x1b[H")


resend_inject = (
    live_inject.replace(
        'ui.load_art = lambda: {"k": 1}', f"ui.load_art = lambda: {{7: ({REAL_PNG!r}, 1, 1), 8: ({REAL_PNG!r}, 1, 1)}}"
    )
    .replace('ui.report_images = lambda *a: ""\n', "")
    .replace("ui.run_report", "ui.ART_SETTLE = 0.3\nui.run_report", 1)
)
T7 = "a=T,U=1,f=100,i=7"


def test_the_banner_of_a_page_turning_final_is_resent_once_after_art_settle():
    rl = report_session([b"q"], draws=[2], hold=1.2, src=child.replace("ui.run_report", resend_inject, 1))
    assert rl.count(T7) == 2
    assert rl.index(T7) < rl.rindex(T7)
    assert "a=d,d=I,i=7" not in rl[rl.index(T7) :]
    assert "a=d,d=I,i=7" in rl
    assert rl.index("a=d,d=I,i=7") < rl.index(T7)


T8 = "a=T,U=1,f=100,i=8"


def test_a_page_turning_final_resends_only_the_images_it_had_not_sent():
    both = resend_inject.replace("[(7 if final else 8, 10, 5)]", "[(7, 10, 5), (8, 10, 5)] if final else [(8, 10, 5)]")
    rb = report_session([b"q"], draws=[2], hold=1.2, src=child.replace("ui.run_report", both, 1))
    assert rb.count(T7) == 2
    assert rb.count(T8) == 1


def test_a_page_final_from_the_start_sends_each_image_once():
    rf = report_session(
        [b"q"],
        draws=[1],
        hold=1.2,
        src=child.replace(
            "ui.run_report", resend_inject.replace("ui.LIVE_REFRESH = 0.2\n", "").replace("'live': True, ", ""), 1
        ),
    )
    assert rf.count(T7) == 1


tick_inject = """ui.report_parts = lambda a, sq, rep, peek, width, *r: ([], [("T" + str(int(r[6] * 10))).ljust(width)] + [("L" + str(n)).ljust(width) for n in range(80)])
S = __import__('time').time() - 99.9
ui.report_for = lambda a: {'live': True, 'text': 'x', 'start': S, 'end': 2}
def count_refresh(q, i):
    print("REFRESH", flush=True)
    return {'live': True, 'text': 'x', 'start': S, 'end': 2}
ui.refresh_live = count_refresh
ui.run_report"""


def test_a_live_page_redraws_when_its_time_changes_without_rereading():
    tk = report_session(
        [b"q"], draws=[2], src=child.replace("ui.run_report", "ui.LIVE_REFRESH = 30\n" + tick_inject, 1)
    )
    assert len(set(re.findall("T\\d+", tk))) >= 2
    assert "REFRESH" not in tk
    assert tk.count("\x1b[?1049h") == 1


def test_time_redraws_add_no_rereads():
    tk2 = report_session([b"q"], draws=[3], src=child.replace("ui.run_report", tick_inject, 1))
    assert tk2.count("REFRESH") == 1
    assert "a=d" not in tk2


def test_a_page_without_a_time_is_not_redrawn_on_a_timer():
    idle = report_session([b"q"], draws=[1], hold=0.6)
    assert idle.count("\x1b[J") == 1


def beat_changes(phase):
    inj = tick_inject.replace(
        "S = __import__('time').time() - 99.9", f"S = __import__('time').time() - 99 - {phase}"
    ).replace(
        'ui.report_parts = lambda a, sq, rep, peek, width, *r: ([], [("T" + str(int(r[6] * 10))).ljust(width)] + [("L" + str(n)).ljust(width) for n in range(80)])',
        "from party_hud.render import fmt_took\nui.report_parts = lambda a, sq, rep, peek, width, *r: print('DRAW', __import__('time').time(), S, fmt_took(r[6] - S).replace(' ', '_'), flush=True) or ([], [('L' + str(n)).ljust(width) for n in range(80)])",
    )
    assert f"time() - 99 - {phase}" in inj
    out = report_session([b"q"], draws=[9], src=child.replace("ui.run_report", inj, 1))
    draws = [(float(t), float(s0), v) for t, s0, v in re.findall(r"DRAW ([0-9.]+) ([0-9.]+) (\S+)", out)]
    return draws, [(b[0] - b[1] - 0.5) % 1 for a, b in itertools.pairwise(draws) if a[2] != b[2]]


PHASES = ["0.0", "0.7"]


@pytest.fixture(scope="module")
def beats():
    """Both phases at once: each session waits about 8 s of real time on its own pty."""
    with ThreadPoolExecutor(len(PHASES)) as ex:
        return dict(zip(PHASES, ex.map(beat_changes, PHASES)))


@pytest.mark.parametrize("ph", PHASES)
def test_the_shown_running_time_changes_right_after_each_half_second(beats, ph):
    dr, ch = beats[ph]
    late = [o - 1 if o > 0.9 else o for o in ch]
    assert len(dr) >= 8
    assert len(ch) >= 3
    assert all(-0.02 <= o <= 0.3 for o in late)
    assert len({v for _, _, v in dr}) >= 4


def test_on_exit_no_image_is_deleted():
    ex_src = first_inject.replace("[(7, 10, 5)]", "[(7, 10, 5), (-1, 6, 3)]")
    ex = report_session([b"q"], src=child.replace("ui.run_report", ex_src, 1))
    assert "\x1b[?1049l" in ex
    assert "a=d" not in ex[ex.rindex("\x1b[H") : ex.rindex("\x1b[?1049l")]


def test_g_redraws_the_bottom_rows_in_place(once):
    scr = report_session([b"G", b"q"])
    assert "L59" in scr[scr.index("\x1b[H", scr.index("\x1b[J")) :]
    assert "L59" not in once


def test_j_draws_the_scrolled_page_once():
    sj = report_session([b"j", b"q"], hold=0.3)
    assert sj.count("\x1b[H") == 2
    assert "L1" in sj[sj.rindex("\x1b[H") :]
    assert "EXITED" in sj


def test_a_report_that_fits_does_not_redraw_on_j():
    fit = report_session([b"j", b"q"], rows=40, lines=3, draws=[1, 1])
    assert fit.count("\x1b[H") == 1


def test_q_ends_the_program(twice):
    assert "EXITED" in twice
