#!/usr/bin/env bash
# party.py unit tests not yet moved to pytest (no tmux needed): key / mouse / cursor logic, report and select
# pages, art, crew sub-commands; the fixture is tests/fixtures/sidebar.json
set -euo pipefail
# sort order follows the locale and differs on macOS; LC_ALL would override LC_COLLATE, so keep it as LC_CTYPE (UTF-8).
if [ -n "${LC_ALL:-}" ]; then export LC_CTYPE="$LC_ALL"; unset LC_ALL; fi
export LC_COLLATE=C

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
party="$root/party.py"
tmp=$(mktemp -d)
export PYTHONDONTWRITEBYTECODE=1 # don't leave __pycache__ in the repo when importing party.py
trap 'rm -rf "$tmp"' EXIT
export XDG_RUNTIME_DIR="$tmp/xdg" # state files of the tests, never the real ones
export XDG_STATE_HOME="$tmp/state"

fail=0
check() { # check <description> <command...>: passes when the command exits 0
  local desc=$1
  shift
  if "$@"; then echo "ok   $desc"; else echo "FAIL $desc"; fail=1; fi
}
across() { # file $2 matches regex $1, which may span lines (BSD grep -z does not let . match newlines)
  python3 -c 'import re, sys; sys.exit(not re.search(sys.argv[1], open(sys.argv[2], encoding="utf-8").read(), re.S))' "$1" "$2"
}

fixture="$root/tests/fixtures/sidebar.json"

# Sidebar: sidebar pane not a squad member, peek, key hints, row highlight, key handling
ui_ok() {
  python3 - "$party" "$fixture" "$tmp" <<'EOF'
import os, re, sys
sys.path.insert(0, os.path.dirname(sys.argv[1])); from party_hud import art, claude_log, codex_log, collect, common, markdown, processes, render, sidebars, ui
snap = collect.collect(sys.argv[2]); towns = snap["towns"]
agents = [a for t in towns for a in t["agents"]]
strip = lambda x: re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", x)
fails = []
def ok(cond, msg):
    if not cond: fails.append(msg)

import json, tempfile
import fcntl, pty, select as _sel, signal, struct, subprocess, termios as _tm, time
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
def report_session(keys, rows=10, lines=60, draws=None, src=child, resizes=(), gap=0.0, hold=0.0):
    m, sl = pty.openpty()
    fcntl.ioctl(sl, _tm.TIOCSWINSZ, struct.pack("HHHH", rows, 60, 0, 0))
    env = dict(os.environ, TMUX_PANE="%99")
    p = subprocess.Popen([sys.executable, "-c", src % (os.path.dirname(sys.argv[1]), sys.argv[2], lines)], stdin=sl, stdout=sl, stderr=sl, env=env, close_fds=True)
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
        while _sel.select([m], [], [], 0.2)[0]:
            out += os.read(m, 65536)
    for key, n in zip(keys, draws or range(1, len(keys) + 1)):
        if not resizes:
            read_until(b"\x1b[J", n)
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
    p.wait(timeout=5)
    os.close(m)
    return out.decode(errors="ignore")
once = report_session([b"\r"])
ok("L0" in once and "L59" not in once and "\x1b[?1003h" in once and once.rindex("\x1b[?1003l") > once.index("switch-client"),
   "report pane: only the first rows are drawn; mouse reporting is on while it runs and off when it ends")
ok("copy-mode" not in once and "clear-history" not in once and "\x1b[3J" not in once, "report pane: no copy-mode, no tmux history calls, no history clearing")
ok(once.count("\x1b[?1049h") == 1 and once.count("\x1b[?1049l") == 1 and once.index("\x1b[?1049h") < once.index("L0") and once.rindex("\x1b[?1049l") > once.index("switch-client"),
   "report pane: alternate screen entered before the first draw and left on exit")
boom = report_session([], src=child.replace("ui.run_report", "ui.report_for = lambda a: 1 / 0\nui.run_report"))
ok(boom.count("\x1b[?1049h") == 1 and boom.rindex("\x1b[?1049l") > boom.index("\x1b[?1049h") and "ZeroDivisionError" in boom,
   "report pane: the alternate screen is left also when the report pane fails")
sf = os.path.join(os.environ["XDG_RUNTIME_DIR"], "party-hud", "seen.json")
if os.path.exists(sf): os.remove(sf)
rd = child.replace("ui.run_report", "ag = ui.get_snapshot()['towns'][0]['agents'][0]\nui.report_queue = lambda towns, pane=None, window=None: [('A', dict(ag, pane='%%1', round=3))]\nui.run_report", 1)
rd_out = report_session([b"q"], src=rd)
ok("EXITED" in rd_out and "Traceback" not in rd_out, "report pane: the finished-report page exits cleanly with a complete member")
ok(json.load(open(sf)) == {"%1": 3}, "report pane: showing a finished report records the member's round as read")
ts = [{"agents": [{"pane": "%1", "status": "idle", "focus": False}]}]
collect.mark_unseen(ts, {"%1": {"status": "working", "unseen": False, "round": 3}}, json.load(open(sf)))
ok(ts[0]["agents"][0]["status"] == "done" and ts[0]["agents"][0]["round"] == 4,
   "report pane: a report of round 3 on screen while the member finishes round 4 leaves it done")
os.remove(sf)
rl = rd.replace("ui.run_report(", "ui.report_for = lambda a: {'live': True, 'text': 'x', 'start': 1, 'end': 2}\nui.run_report(", 1)
rl_out = report_session([b"q"], src=rl)
ok("EXITED" in rl_out and "Traceback" not in rl_out, "report pane: the live page exits cleanly with a complete member")
ok(not os.path.exists(sf), "report pane: a live page (member still working) records nothing")
stale = rd.replace("ui.run_report", """ag = ui.get_snapshot()["towns"][0]["agents"][0]
mk = lambda p, r: dict(ag, pane=p, round=r)
ui.report_queue = lambda towns, pane=None, window=None: [('A', mk('%%1', 1)), ('A', mk('%%2', 3))]
ui.get_snapshot = lambda f=None: {"towns": [{"agents": [mk('%%1', 1), mk('%%2', 5)]}]}
ui.run_report""", 1)
stale_out = report_session([b"n", b"q"], src=stale)
ok("EXITED" in stale_out and "Traceback" not in stale_out, "report pane: the stale-round page exits cleanly")
ok(json.load(open(sf)) == {"%1": 1, "%2": 5}, "report pane: n to a member that finished a newer round records the round now on screen, not the queued one")
os.remove(sf)
ok("TMUX ('switch-client', '-t'" in once and "EXITED" in once, "report pane: Enter jumps to the member's pane and exits")
seen_win = report_session([b"q"], src=child.replace("ui.run_report", "ui.report_queue = lambda t, p=None, w=None: print('WIN', w, flush=True) or []\nui.run_report", 1))
ok("TMUX ('display-message', '-p', '-t', '%99', '#{window_id}')" in seen_win, "report pane: the caller's window is asked of tmux by the pane's own $TMUX_PANE")
select_child = child.replace('ui.run_report("%%1")', "ui.run_menu()")
names = [a["name"] for t in collect.collect(sys.argv[2])["towns"] for a in t["agents"]]
if os.path.exists(sf): os.remove(sf)
sel_q = report_session([b"q"], rows=60, src=select_child)
ok("EXITED" in sel_q and "Traceback" not in sel_q and all(n[:4] in sel_q for n in names) and "PARTY SELECT" in sel_q,
   "select screen: the pty run draws every member of the roster and q ends the program")
ok(not os.path.exists(sf) and sel_q.count("\x1b[?1049h") == 1 and sel_q.count("\x1b[?1049l") == 1 and sel_q.rindex("\x1b[?1003l") > sel_q.index("\x1b[?1003h"),
   "select screen: only looking records nothing as read; the alternate screen and mouse reporting are restored on exit")
sel_open = report_session([b"\r", b"q"], src=select_child)
ok("EXITED" in sel_open and "Traceback" not in sel_open and "L0" in sel_open[sel_open.index("PARTY SELECT"):] and "display-menu" not in sel_open,
   "select screen: Enter opens the report page in the same process and q on it ends the program")
trace_child = select_child.replace("ui.run_menu()", """_rs, _rr = ui.run_select, ui.run_report
ui.run_select = lambda sel=None, fixture=None, images=None: print("TRACE_SELECT", sel, flush=True) or _rs(sel, fixture, images)
ui.run_report = lambda pane=None, fixture=None, back=False, images=None: print("TRACE_REPORT", pane, back, flush=True) or _rr(pane, fixture, back, images)
ui.run_menu()""")
tw = collect.collect(sys.argv[2])["towns"]
first = render.select_roster(tw)[0][1]["pane"]
nxt = ui.report_queue(tw, first, "")[1][1]["pane"]
nxt_expect = nxt if nxt in [a["pane"] for _, a, _ in render.select_roster(tw)] else first
back_h = report_session([b"\r", b"h", b"q"], src=trace_child)
ok("EXITED" in back_h and "Traceback" not in back_h and back_h.count("PARTY SELECT") == 2 and f"TRACE_SELECT {first}" in back_h
   and back_h.index("TRACE_REPORT") < back_h.rindex("PARTY SELECT") and back_h.count("\x1b[?1049h") == 3 and back_h.count("\x1b[?1049l") == 3,
   "select screen: h on the report page returns to the select screen (terminal restored in between) and q there ends the program")
again = report_session([b"\r", b"h", b"\r", b"h", b"q"], src=trace_child)
ok("EXITED" in again and "Traceback" not in again and again.count("TRACE_REPORT") == 2 and again.count("TRACE_SELECT") == 3,
   "select screen: after h a member can be opened again and h used again")
nh = report_session([b"\r", b"n", b"h", b"q"], src=trace_child)
ok("EXITED" in nh and "Traceback" not in nh and f"TRACE_SELECT {nxt_expect}" in nh[nh.index("TRACE_REPORT"):],
   f"select screen: n then h returns with the cursor on the member n moved to (or the first row when that member is not in the list: {nxt_expect})")
sel_close = report_session([b"\r", b"q"], src=trace_child)
ok("EXITED" in sel_close and "Traceback" not in sel_close and sel_close.count("TRACE_SELECT") == 1 and sel_close.count("TRACE_REPORT") == 1 and sel_close.count("PARTY SELECT") == 1,
   "select screen: q on the report page ends the program, it does not go back")
REAL_PNG = os.path.join(os.path.dirname(sys.argv[1]), "art", "label-took.png")
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
sh_second = sh[[m.start() for m in re.finditer(re.escape("\x1b[?1049h"), sh)][3]:]
ok("EXITED" in sh and "Traceback" not in sh and sh.count("\x1b[?1049h") == 4 and "a=T,U=1,f=100,i=7," in sh
   and all(sh.count(f"a=T,U=1,f=100,i={i},") == 1 for i in (11, 7)) and "a=d" not in sh_second and sh.count("LOAD_ART") == 1 and sh.count("\x1b[?25h\x1b[?1049l") == 4,
   "select and report: the select screen, the report page and the select screen again sends no image twice (each id once, no delete on the second report page or when a screen is left, the files read once)")
direct_h = report_session([b"h", b"q"], rows=80)
ok("EXITED" in direct_h and "Traceback" not in direct_h and direct_h.count("\x1b[?1049h") == 1 and "close" in strip(direct_h) and "back" not in strip(direct_h),
   "report pane: h does nothing on a directly opened page, q ends it, and the hint row has no h")
from_sel = report_session([b"\r", b"q"], rows=80, src=trace_child)
ok("h back" in strip(from_sel) and "h back" in strip(render.render_report(tw[0]["agents"][0], "S", None, [], 60, hints="report_back")) and any("h back" in strip(r) for r in render.report_parts(tw[0]["agents"][0], "S", None, [], 150, art=True, hints="report_back")[0]) and "h back" not in strip(render.render_report(tw[0]["agents"][0], "S", None, [], 60)),
   "report page opened from the select screen shows h in its hint row (narrow and split page), a direct one does not")
sel_g = report_session([b"g", b"q"], src=select_child)
ok("switch-client" not in sel_g and "EXITED" in sel_g and "L0" not in sel_g, "select screen: g does nothing (no switch to the pane, no report)")
if os.path.exists(sf): os.remove(sf)
twice = report_session([b"n", b"q"])
ok("\x1b[2J" not in twice and twice.count("L0") == 2, "report pane: n draws the next report in place, without clearing the screen")
rs = report_session([b"q"], rows=30, resizes=[29, 28, 27, 26, 25, 24, 23, 22, 21, 20] * 2, gap=0.005)
rs_draws = rs.count("\x1b[J") - 1
ok("\x1b[2J" not in rs and "\x1b[3J" not in rs, "report pane: a resize redraws in place, never clears the screen")
ok(2 <= rs_draws <= 8, f"report pane: 20 size changes in about 0.1 s redraw a bounded number of times (got {rs_draws})")
last = rs[rs.rindex("\x1b[H") : rs.index("\x1b[J", rs.rindex("\x1b[H"))]
ok(last.count("\n") == 19, "report pane: after the burst the last redraw has the final size")
anim_src = child.replace('"\\n".join(f"L{n}"', '"\\n\\n".join(f"L{n}"').replace('or ("off" if "@party_anim" in a else "")', 'or ""')
aq = report_session([b"q"], rows=16, lines=12, src=anim_src)
a_first = aq[aq.index("\x1b[H") : aq.index("\x1b[H", aq.index("\x1b[H") + 1)]
a_last = aq[aq.rindex("\x1b[H") :]
ok(aq.count("\x1b[H") == 2 and "L1" in a_first and "L3" not in a_first and "L3" in a_last and "EXITED" in aq,
   "report pane: a key during the opening animation draws the whole page at once and is still handled (q exits)")
an = report_session([b"n", b"q"], rows=16, lines=12, draws=[1, 3], src=anim_src)
ok("report 2/3" in an and an.count("\x1b[H") == 4 and "EXITED" in an, "report pane: n during the animation changes page at once, and the new page starts its own animation")
first_img = """ag = ui.get_snapshot()["towns"][0]["agents"][0]
ui.report_queue = lambda towns, pane=None, window=None: [("A", dict(ag, pane="%%1", round=0))]
ui.art_supported = lambda *a: True
ui.load_art = lambda: {"k": 1}
ui.report_images = lambda *a: "<IMG>"
ui.report_image_plan = lambda *a: []
ui.run_report"""
wf = report_session([b"q"], rows=16, lines=12, hold=0.6, src=anim_src.replace("ui.run_report", first_img, 1))
wf_none = report_session([b"q"], rows=16, lines=12, hold=0.6, src=anim_src.replace("ui.run_report", first_img.replace("<IMG>", ""), 1))
ok(wf.count("<IMG>") == 1 and wf.count("\x1b[H") == wf_none.count("\x1b[H") > 2 and wf.index("\x1b[H") < wf.index("<IMG>") < wf.index("\x1b[H", wf.index("\x1b[H") + 1),
   "report pane: on a new page with the opening animation the images are sent with the first frame, before the second animation frame, and the animation still plays out")
art_inject = """ui.report_queue = lambda towns, pane=None, window=None: [("A", {"pane": "%%1", "round": 0})]
ui.art_supported = lambda *a: True
ui.load_art = lambda: {"k": 1}
ui.report_images = lambda *a: "<IMG r=%%d>" %% os.get_terminal_size(1).lines
ui.report_image_plan = lambda *a: []
ui.report_parts = lambda a, sq, rep, peek, width, *r: ([], [("L" + str(n)).ljust(width) for n in range(80)])
ui.run_report"""
ra = report_session([b"q"], rows=30, resizes=[29, 28, 27, 26, 25, 24, 23, 22, 21, 20] * 2, gap=0.005, src=child.replace("ui.run_report", art_inject, 1).replace("import sys\n", "import os, sys\n", 1))
ok(ra.count("<IMG") == 2 and ra.count("<IMG r=20>") == 1,
   "report pane: images are resent once, at the final size, after the resize burst stops")
still_inject = """import time
ag = ui.get_snapshot()["towns"][0]["agents"][0]
ui.report_queue = lambda towns, pane=None, window=None: [("A", dict(ag, pane="%%1", round=3))]
ui.report_for = lambda a: {"text": "x", "start": time.time() - 9, "end": time.time() - 5}
ui.report_parts = lambda a, sq, rep, peek, width, *r: (["left"], [("L" + str(n)).ljust(width) for n in range(3)])
ui.run_report"""
still = report_session([b"q"], rows=10, hold=3.0, src=child.replace("ui.run_report", still_inject, 1))
ok("EXITED" in still and still.count("\x1b[J") == 1, f"report pane: a time tick that leaves the rows as they were writes nothing (got {still.count(chr(27) + '[J')} writes in 3 s)")
first_inject = """ui.report_queue = lambda towns, pane=None, window=None: [("A", {"pane": "%%1", "round": 0})]
ui.art_supported = lambda *a: True
ui.load_art = lambda: {"k": 1}
ui.report_images = lambda *a: ""
ui.report_image_plan = lambda *a: [(7, 10, 5)]
ui.portrait_id = lambda a: -1
ui.report_parts = lambda a, sq, rep, peek, width, *r: ([], [("L" + str(n)).ljust(width) for n in range(80)])
ui.run_report"""
fp = report_session([b"n", b"q"], src=child.replace("ui.run_report", first_inject, 1))
ok(fp.count("a=d,d=I,i=7") == 1 and fp.index("a=d,d=I,i=7") < fp.index("\x1b[H"),
   "report pane: the first frame is written with a delete of the unsent image id, and n does not delete it again")
live_inject = first_inject.replace("ui.report_image_plan = lambda *a: [(7, 10, 5)]", "ui.report_image_plan = lambda a, final, *r: [(7 if final else 8, 10, 5)]").replace(
    "ui.run_report", "ui.LIVE_REFRESH = 0.2\nui.report_for = lambda a: {'live': True, 'text': 'x', 'start': None, 'end': 2}\nui.refresh_live = lambda q, i: {'text': 'done', 'start': 1, 'end': 3}\nui.run_report", 1)
lv = report_session([b"q"], draws=[2], src=child.replace("ui.run_report", live_inject, 1))
ok("a=d,d=I,i=7" in lv and lv.index("a=d,d=I,i=7") > lv.index("\x1b[H") and lv.index("a=d,d=I,i=7") < lv.rindex("\x1b[H"),
   "report pane: when the in-progress page turns into the final report, the new banner id is deleted with the next frame, as for a new page")
resend_inject = live_inject.replace("ui.load_art = lambda: {\"k\": 1}", "ui.load_art = lambda: {7: (%r, 1, 1), 8: (%r, 1, 1)}" % (REAL_PNG, REAL_PNG)).replace("ui.report_images = lambda *a: \"\"\n", "").replace("ui.run_report", "ui.ART_SETTLE = 0.3\nui.run_report", 1)
T7 = "a=T,U=1,f=100,i=7"
rl = report_session([b"q"], draws=[2], hold=1.2, src=child.replace("ui.run_report", resend_inject, 1))
ok(rl.count(T7) == 2 and rl.index(T7) < rl.rindex(T7) and "a=d,d=I,i=7" not in rl[rl.index(T7) :] and "a=d,d=I,i=7" in rl and rl.index("a=d,d=I,i=7") < rl.index(T7),
   "report pane: the banner sent when the page turns final is sent once more after ART_SETTLE, with no delete between, and not a third time")
rf = report_session([b"q"], draws=[1], hold=1.2, src=child.replace("ui.run_report", resend_inject.replace("ui.LIVE_REFRESH = 0.2\n", "").replace("'live': True, ", ""), 1))
ok(rf.count(T7) == 1, "report pane: a page that was final from the start has each image sent once, with no later resend")
tick_inject = """ui.report_parts = lambda a, sq, rep, peek, width, *r: ([], [("T" + str(int(r[6] * 10))).ljust(width)] + [("L" + str(n)).ljust(width) for n in range(80)])
S = __import__('time').time() - 99.9
ui.report_for = lambda a: {'live': True, 'text': 'x', 'start': S, 'end': 2}
def count_refresh(q, i):
    print("REFRESH", flush=True)
    return {'live': True, 'text': 'x', 'start': S, 'end': 2}
ui.refresh_live = count_refresh
ui.run_report"""
tk = report_session([b"q"], draws=[2], src=child.replace("ui.run_report", "ui.LIVE_REFRESH = 30\n" + tick_inject, 1))
ok(len(set(re.findall(r"T\d+", tk))) >= 2 and "REFRESH" not in tk and tk.count("\x1b[?1049h") == 1,
   "report pane: a live page redraws with a new time when its second changes without waiting for LIVE_REFRESH, and does not re-read")
tk2 = report_session([b"q"], draws=[3], src=child.replace("ui.run_report", tick_inject, 1))
ok(tk2.count("REFRESH") == 1 and "a=d" not in tk2,
   "report pane: the time redraws do not add re-reads: one LIVE_REFRESH period reads once")
idle = report_session([b"q"], draws=[1], hold=0.6)
ok(idle.count("\x1b[J") == 1, "report pane: a page with no time value on it is not redrawn on a timer")
def beat_changes(phase):
    inj = tick_inject.replace("S = __import__('time').time() - 99.4", "S = __import__('time').time() - 99 - %s" % phase).replace("ui.report_parts = lambda a, sq, rep, peek, width, *r: ([], [(\"T\" + str(int(r[6] * 10))).ljust(width)] + [(\"L\" + str(n)).ljust(width) for n in range(80)])", "from party_hud.render import fmt_took\nui.report_parts = lambda a, sq, rep, peek, width, *r: print('DRAW', __import__('time').time(), S, fmt_took(r[6] - S).replace(' ', '_'), flush=True) or ([], [('L' + str(n)).ljust(width) for n in range(80)])")
    out = report_session([b"q"], draws=[9], src=child.replace("ui.run_report", inj, 1))
    draws = [(float(t), float(s0), v) for t, s0, v in re.findall(r"DRAW ([0-9.]+) ([0-9.]+) (\S+)", out)]
    return draws, [(b[0] - b[1] - 0.5) % 1 for a, b in zip(draws, draws[1:]) if a[2] != b[2]]
for ph in ("0.0", "0.7"):
    dr, ch = beat_changes(ph)
    late = [o - 1 if o > 0.9 else o for o in ch]
    ok(len(dr) >= 8 and len(ch) >= 3 and all(-0.02 <= o <= 0.3 for o in late) and len({v for _, _, v in dr}) >= 4,
       f"report pane: the shown running time (fmt_took) changes within 0.3 s after each S + n + 0.5 (phase {ph}); a re-read between two changes does not move it (offsets {[round(o, 3) for o in late]})")
ex_src = first_inject.replace("[(7, 10, 5)]", "[(7, 10, 5), (-1, 6, 3)]")
ex = report_session([b"q"], src=child.replace("ui.run_report", ex_src, 1))
ok("\x1b[?1049l" in ex and "a=d" not in ex[ex.rindex("\x1b[H"):ex.rindex("\x1b[?1049l")],
   "report pane: on exit it deletes no image, since another pane may show the same ids")
scr = report_session([b"G", b"q"])
ok("L59" in scr[scr.index("\x1b[H", scr.index("\x1b[J")):] and "L59" not in once, "report pane: G redraws the bottom rows in place")
sj = report_session([b"j", b"q"], hold=0.3)
ok(sj.count("\x1b[H") == 2 and "L1" in sj[sj.rindex("\x1b[H"):] and "EXITED" in sj, "report pane: j draws the scrolled page once and nothing after it")
fit = report_session([b"j", b"q"], rows=40, lines=3, draws=[1, 1])
ok(fit.count("\x1b[H") == 1, "report pane: a report that fits the pane does not redraw on j")
ok("EXITED" in twice, "report pane: q ends the program, which closes the pane")
print("\n".join(fails), file=sys.stderr)
sys.exit(1 if fails else 0)
EOF
}
check "Sidebar: peek, hint bar, highlight, key handling" ui_ok

# --summon: tmux arguments, exit codes, readiness; @party_lead / @xv grouping and card widths
summon_ok() {
  python3 - "$party" "$tmp" <<'EOF2'
import os, re, sys, time
sys.path.insert(0, os.path.dirname(sys.argv[1])); from party_hud import claude_log, codex_log, collect, processes, render, sidebars
fails = []
def ok(cond, msg):
    if not cond: fails.append(msg)
calls = []
shows = []
opened = lambda: next(c for c in calls if c[0] in ("split-window", "new-window", "new-session"))
has_crew = [False]
crew_lead = [""]
lead_alive = [True]
FS = collect.FIELD_SEP
def fake_run(args, timeout=None):
    calls.append(tuple(args))
    if args[0] == "display-message" and args[-1] == FS.join(["#{pane_id}", "#{@party_lead}"]): return 0, args[3] + FS + crew_lead[0] + "\n", ""
    # tmux exits 0 for a pane that does not exist and prints no pane id
    if args[0] == "display-message" and args[-1] == "#{pane_id}": return 0, (args[3] if lead_alive[0] else "") + "\n", ""
    if args[0] in ("split-window", "new-window", "new-session"): return 0, "%9\n", ""
    if args[0] == "has-session": return (0 if has_crew[0] else 1), "", ""
    if args[0] == "display-message" and args[-1] == FS.join(["#{window_width}", "#{window_height}"]): return 0, f"132{FS}41\n", ""
    if args[0] == "display-message": return 0, (args[3] + FS if pane_alive[0] else "") + (shows.pop(0) if len(shows) > 1 else shows[0]), ""
    return 0, "", ""
pane_alive = [True]
sidebars.tmux_run = collect.tmux_run = fake_run
sidebars.tmux = lambda *a: calls.append(a) or ("screen" if a[0] == "capture-pane" else "")
sidebars.time.sleep = lambda s: None
listed = [True]
sidebars.get_snapshot = lambda: {"towns": [{"agents": [{"pane": "%9"}] if listed[0] else []}]}
sep = collect.FIELD_SEP
ready = [f"claude{sep}123\n"]
os.environ["TMUX_PANE"] = "%1"
shows[:] = ready
tmp = sys.argv[2]
rc, out, err = sidebars.summon("claude", tmp, False, 5)
ok(rc == 0 and out == "%9\n" and err == "", "summon: ready -> pane id on stdout, rc 0")
ok(("new-session", "-d", "-s", "crew-1", "-x", "132", "-y", "41", "-P", "-F", "#{pane_id}", "-c", tmp, "claude") in calls,
   "summon: default creates the detached session crew-<caller number> at the caller's window size")
ok(("set-option", "-p", "-t", "%9", "@party_lead", "%1") in calls, "summon: the new pane gets @party_lead = caller pane")
calls.clear(); shows[:] = ready; has_crew[0] = True
sidebars.summon("claude", tmp, False, 5)
ok(("new-window", "-d", "-t", "crew-1:", "-P", "-F", "#{pane_id}", "-c", tmp, "claude") in calls and not any(c[0] == "new-session" for c in calls),
   "summon: default with crew-N already there opens a window in it")
has_crew[0] = False
calls.clear(); shows[:] = ready
sidebars.summon("claude", tmp, False, 5, here=True)
ok(opened() == ("split-window", "-t", "%1", "-P", "-F", "#{pane_id}", "-c", tmp, "claude"), "summon --here: splits the caller's window")
calls.clear()
ok(sidebars.summon("claude", tmp, True, 5, here=True)[0] == 2 and not calls, "summon --window --here -> 2, tmux not called")
calls.clear(); shows[:] = ready
sidebars.summon("codex", tmp, True, 5)
ok(opened() == ("new-window", "-P", "-F", "#{pane_id}", "-c", tmp, "codex -c check_for_update_on_startup=false"),
   "summon --window: new-window, --cwd passed to -c; codex starts with its startup update prompt turned off")
hashed = os.path.join(tmp, "a#(b)#{c}")
os.makedirs(hashed, exist_ok=True)
calls.clear(); shows[:] = ready
sidebars.summon("codex", hashed, True, 5)
ok(opened()[opened().index("-c") + 1] == os.path.join(tmp, "a##(b)##{c}"), "summon: every # in --cwd is doubled for tmux's format expansion")
calls.clear(); shows[:] = ready
sidebars.summon("codex", tmp, False, 5, True, True)
ok(opened() == ("split-window", "-t", "%1", "-P", "-F", "#{pane_id}", "-c", tmp, "codex -c check_for_update_on_startup=false -s read-only"),
   "summon --read-only: codex starts with -s read-only, update prompt off")
calls.clear(); shows[:] = ready
sidebars.summon("claude", tmp, False, 5, True)
ok(any(c[0] == "new-session" and c[-1] == "claude --permission-mode plan" for c in calls), "summon --read-only: the default crew session also gets the read-only command")
for kind, cmd in (("claude", "claude --permission-mode plan"), ("agy", "agy --mode plan"), ("grok", "grok --permission-mode plan")):
    calls.clear(); shows[:] = ready
    rc, out, err = sidebars.summon(kind, tmp, False, 5, True, True)
    ok(rc == 0 and opened()[-1] == cmd, f"summon --read-only: {kind} starts with its plan mode")
calls.clear()
crew_lead[0] = "%0"
blocked = lambda: any(c[0] in ("new-session", "new-window", "split-window", "set-option") for c in calls)
for label, kw in (("default", {}), ("--window", {"window": True}), ("--here", {"here": True}), ("--read-only", {"read_only": True})):
    calls.clear(); shows[:] = ready
    rc, out, err = sidebars.summon("claude", tmp, kw.get("window", False), 5, kw.get("read_only", False), kw.get("here", False))
    ok(rc == 6 and out == "" and "report to your lead" in err and not blocked(), f"summon {label}: caller is crew and its lead pane exists -> 6, nothing opened")
lead_alive[0] = False
calls.clear(); shows[:] = ready
rc, out, err = sidebars.summon("claude", tmp, False, 5)
ok(rc == 0 and any(c[0] == "new-session" for c in calls), "summon: @party_lead points at a pane that is gone -> summons as usual")
lead_alive[0] = True; crew_lead[0] = ""
calls.clear()
ok(sidebars.summon("vim", tmp, False, 5)[0] == 2 and not calls, "summon: an agent outside AGENT_CMDS -> 2, tmux not called")
del os.environ["TMUX_PANE"]
ok(sidebars.summon("claude", tmp, False, 5)[0] == 2 and not calls, "summon: outside tmux -> 2")
os.environ["TMUX_PANE"] = "%1"
shows[:] = [f"bash{sep}1\n"]
t = [0.0]
time.monotonic = lambda: t[0]
sidebars.time.sleep = lambda s: t.__setitem__(0, t[0] + s)
rc, out, err = sidebars.summon("claude", tmp, False, 3)
ok(rc == 3 and out == "" and "%9" in err, "summon: timeout -> 3, pane id on stderr")
shows[:] = ready; listed[0] = False; t[0] = 0.0
rc, out, err = sidebars.summon("claude", tmp, False, 3)
ok(rc == 3 and "%9" in err, "summon: not ready until the snapshot lists the pane (ask and report-text read the snapshot)")
listed[0] = True
shows[:] = [f"{sep}\n"]; pane_alive[0] = False; t[0] = 0.0
ok(sidebars.summon("claude", tmp, False, 3) == (2, "", "no such pane: %9\n"), "summon: the new pane goes away before it is ready -> 2 at once, not a timeout")
pane_alive[0] = True
agent = lambda pane, kind="claude", window="@1": {"pane": pane, "kind": kind, "window": window, "status": "idle"}
mk_towns = lambda *ts: {n: {"name": n, "agents": list(ag)} for n, ag in ts}
towns = mk_towns(("main", [agent("%1"), agent("%7")]), ("crew-1", [agent("%2", "codex"), agent("%3", "grok")]))
collect.adopt_crews(towns, {"%1": ("", False, "@1"), "%2": ("%1", False, "@2"), "%3": ("%1", False, "@2")})
ok(list(towns) == ["main"] and [x["pane"] for x in collect.group_under_leads(towns["main"]["agents"], {"%2": ("%1", False, "@2"), "%3": ("%1", False, "@2")})] == ["%1", "%2", "%3", "%7"],
   "crew: members of a crew squad join the lead's squad right under the lead and the empty squad is dropped")
towns = mk_towns(("main", [agent("%7")]), ("crew-1", [agent("%2", "codex")]))
collect.adopt_crews(towns, {"%2": ("%1", False, "@2")})
ok(list(towns) == ["main", "crew-1"] and [x["pane"] for x in towns["crew-1"]["agents"]] == ["%2"], "crew: lead gone -> the crew squad stays as it is")
nest = {"%5": ("%0", False, "@5"), "%6": ("%5", False, "@6")}
seen = []
for order in (("crew-0", "crew-5", "main"), ("crew-5", "crew-0", "main")):
    pool = {"main": [agent("%0")], "crew-0": [agent("%5")], "crew-5": [agent("%6")]}
    towns = mk_towns(*((n, pool[n]) for n in order))
    collect.adopt_crews(towns, nest)
    seen.append({n: sorted(x["pane"] for x in t["agents"]) for n, t in towns.items()})
ok(seen[0] == seen[1] and sorted(p for v in seen[0].values() for p in v) == ["%0", "%5", "%6"],
   "crew: a crew inside a crew keeps every agent in exactly one squad, whatever the squad order")
a, b, c = agent("%1"), agent("%2", "codex"), agent("%3", "claude", "@2")
got = collect.group_under_leads([a, c, b], {"%1": ("", False, "@1"), "%2": ("%1", False, "@1"), "%3": ("", False, "@2")})
ok([x["pane"] for x in got] == ["%1", "%2", "%3"] and b.get("lead") == "%1" and "lead" not in c,
   "@party_lead: the member is listed under its lead")
a, x = agent("%1"), agent("%4", "codex")
got = collect.group_under_leads([x, a], {"%1": ("", False, "@1"), "%4": ("", True, "@1")})
ok([m["pane"] for m in got] == ["%1", "%4"] and x.get("lead") == "%1", "@xv: the only Claude of the window becomes the lead")
a, a2, x = agent("%1"), agent("%2"), agent("%4", "codex")
got = collect.group_under_leads([a, a2, x], {"%1": ("", False, "@1"), "%2": ("", False, "@1"), "%4": ("", True, "@1")})
ok([m["pane"] for m in got] == ["%1", "%2", "%4"] and "lead" not in x, "@xv: two Claudes in the window -> an ordinary member")
a, b, c = agent("%1"), agent("%2", "codex"), agent("%3", "claude", "@2")
got = collect.group_under_leads([c, b, a], {"%1": ("", False, "@1"), "%2": ("", False, "@1"), "%3": ("", False, "@2")})
ok([m["pane"] for m in got] == ["%3", "%2", "%1"] and not any("lead" in m for m in got), "group under leads: no lead or xv keeps order")
a = {**agent("%1"), "name": "boss", "hp": 50, "hp_max": 100, "hp_left": 50, "sp": None, "fresh": False, "model": "", "summons": [], "cls": 0, "focus": False, "id": "i1"}
for art in (False, True):
    for lead in ("", "%1"):
        rows = render.card({**a, "lead": lead}, 40, False, art)
        ok({render.cw(re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", r)) for r in rows} == {40}, f"card: every line exactly 40 columns (art={art}, lead={lead!r})")
crew_done = {**a, "pane": "%2", "status": "done", "lead": "%1"}
ok("✓ done" in re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", "\n".join(render.card(crew_done, 40, False, False))), "crew done: the card still says done")
print("\n".join(fails), file=sys.stderr)
sys.exit(1 if fails else 0)
EOF2
}
check "summon: tmux arguments, exit codes, timeout; @party_lead / @xv grouping" summon_ok

# --dismiss: only a member you summoned, not working, report read; kill-pane only then
dismiss_ok() {
  python3 - "$party" <<'EOF2'
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(sys.argv[1])); from party_hud import claude_log, codex_log, collect, processes, sidebars
fails = []
def ok(cond, msg):
    if not cond: fails.append(msg)
collect.PARTY_DIR = tempfile.mkdtemp()
def write_seen(seen):
    with open(os.path.join(collect.PARTY_DIR, "seen.json"), "w") as f: json.dump(seen, f)
calls = []
lead = ["%1"]
exists = [True]
def fake_run(args, timeout=None):
    calls.append(tuple(args))
    # tmux exits 0 for a pane that does not exist and prints no pane id
    if args[0] == "display-message": return 0, (args[3] if exists[0] else "") + collect.FIELD_SEP + lead[0] + "\n", ""
    return 0, "", ""
sidebars.tmux_run = collect.tmux_run = fake_run
member = {"pane": "%9", "kind": "codex", "status": "idle", "summons": [], "round": 3}
sidebars.get_snapshot = lambda: {"towns": [{"agents": [member]}]}
os.environ["TMUX_PANE"] = "%1"
killed = lambda: any(c[0] == "kill-pane" for c in calls)
def run(pane="%9", **kw):
    calls.clear()
    member.update({"status": "idle", "summons": []}); member.update(kw)
    return sidebars.dismiss(pane)
rc, out, err = run()
ok(rc == 0 and ("kill-pane", "-t", "%9") in calls, "dismiss: summoned by the caller, idle, report read -> kill-pane, rc 0")
lead[0] = "%2"
rc, out, err = run()
ok(rc == 6 and "not summoned by you" in err and not killed(), "dismiss: @party_lead is another pane -> 6, no kill-pane")
lead[0] = ""
rc, out, err = run()
ok(rc == 6 and "not summoned by you" in err and not killed(), "dismiss: no @party_lead -> 6, no kill-pane")
lead[0] = "%1"
rc, out, err = run(status="waiting")
ok(rc == 6 and "not dismissed" in err and not killed(), "dismiss: waiting for input -> 6, no kill-pane")
lead[0] = "%2"
rc, out, err = run(status="waiting")
ok(rc == 6 and "not summoned by you" in err and not killed(), "dismiss: waiting and @party_lead is another pane -> still not summoned by you")
lead[0] = "%1"
rc, out, err = run(status="waiting", summons=[{"type": "executor"}])
ok(rc == 6 and "still working" in err and not killed(), "dismiss: waiting with running subagents -> still working")
rc, out, err = run(status="working")
ok(rc == 6 and "still working" in err and not killed(), "dismiss: working -> 6, no kill-pane")
rc, out, err = run(summons=[{"type": "executor"}])
ok(rc == 6 and "still working" in err and not killed(), "dismiss: running subagents -> 6, no kill-pane")
rc, out, err = run(status="done")
ok(rc == 6 and "report not read yet; run --report-text first" in err and not killed(), "dismiss: done (report not read) -> 6, no kill-pane")
write_seen({"%9": 2})
rc, out, err = run(status="done")
ok(rc == 6 and "report not read yet" in err and not killed(), "dismiss: done, seen round below the member round -> 6, no kill-pane")
write_seen({"%9": 3})
rc, out, err = run(status="done")
ok(rc == 0 and calls.count(("kill-pane", "-t", "%9")) == 1, "dismiss: done, seen round reached the member round -> rc 0, one kill-pane")
write_seen({})
rc, out, err = run("%8")
ok(rc == 4 and not killed(), "dismiss: a pane that is not a known agent -> 4, no kill-pane")
exists[0] = False
rc, out, err = run()
ok((rc, err) == (2, "no such pane: %9\n") and not killed(), "dismiss: pane does not exist -> 2, no kill-pane")
exists[0] = True
rc, out, err = run("9")
ok(rc == 2 and not calls, "dismiss: bad pane id -> 2, tmux not called")
del os.environ["TMUX_PANE"]
rc, out, err = run()
ok(rc == 2 and not calls, "dismiss: outside tmux -> 2, tmux not called")
print("\n".join(fails), file=sys.stderr)
sys.exit(1 if fails else 0)
EOF2
}
check "dismiss: four rules before kill-pane; exit codes 2, 4, 6" dismiss_ok

# crew: every round saved under $XDG_STATE_HOME/party-hud/crew/<UTC start>-<pane>/round-NNN/
crew_ok() {
  python3 - "$party" "$tmp" <<'EOF3'
import json, os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(sys.argv[1])); from party_hud import claude_log, codex_log, collect, processes, sidebars
import party
fails = []
def ok(cond, msg):
    if not cond: fails.append(msg)
state = os.path.join(sys.argv[2], "crewstate")
os.environ["XDG_STATE_HOME"] = state
root = os.path.join(state, "party-hud", "crew")
read = lambda *p: open(os.path.join(root, *p), encoding="utf-8").read()
party.get_snapshot = lambda: {"towns": [{"agents": [{"pane": "%5", "kind": "codex", "round": 4}]}]}
party.tmux_run = collect.tmux_run = lambda args, timeout=None: (0, "%5" + collect.FIELD_SEP + "/work/dir\n", "")
party.subprocess.run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", "")
rc, out, err = party.ask("%5", "first?")
sess = os.listdir(root)
ok(rc == 0 and len(sess) == 1 and sess[0].endswith("Z-5"), "crew: first --ask on a pane not summoned creates <UTC time>-<pane id without %> ")
meta = json.loads(read(sess[0], "round-001", "meta.json"))
ok(read(sess[0], "round-001", "question.md") == "first?" and meta["pane"] == "%5" and meta["agent"] == "codex"
   and meta["cwd"] == "/work/dir" and "asked_at" in meta, "crew: --ask writes round-001/question.md and meta.json (asked_at, pane, agent, cwd)")
ok(sidebars.crew_replied("%5", "answer\n", 0) == "", "crew: --report-text save succeeds")
meta = json.loads(read(sess[0], "round-001", "meta.json"))
ok(read(sess[0], "round-001", "reply.md") == "answer\n" and meta["rc"] == 0 and "replied_at" in meta and meta["agent"] == "codex",
   "crew: --report-text writes reply.md into the latest round and adds replied_at, rc to meta.json")
ok(sidebars.crew_replied("%5", "screen\n", 7) == "" and json.loads(read(sess[0], "round-001", "meta.json"))["rc"] == 7
   and read(sess[0], "round-001", "reply.md") == "screen\n", "crew: --report-text rc 7 is saved to reply.md and meta.json rc")
import contextlib, io
real_rt, real_cr, real_argv = party.report_text, party.crew_replied, sys.argv
def run_main(result, save_err, rnd=None):
    saved.clear()
    party.report_text = lambda *a: result if rnd is None else a[-1].update(round=rnd) or result
    party.crew_replied = lambda pane, out, rc: saved.append((pane, out, rc)) or save_err
    sys.argv = ["party.py", "--report-text", "%5"]
    so, se = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
            party.main()
    except SystemExit as e:
        return e.code, so.getvalue(), se.getvalue()
    finally:
        party.report_text, party.crew_replied, sys.argv = real_rt, real_cr, real_argv
saved = []
ok(run_main((7, "screen\n", "%5 is waiting for input\n"), "") == (7, "screen\n", "%5 is waiting for input\n")
   and saved == [("%5", "screen\n", 7)], "party --report-text: rc 7 prints the screen and saves it with rc 7")
ok(run_main((7, "screen\n", "%5 is waiting for input\n"), "save failed\n") == (7, "screen\n", "%5 is waiting for input\nsave failed\n"),
   "party --report-text: rc 7 with a failed save stays 7 and reports the save error on stderr")
ok(run_main((0, "answer\n", ""), "save failed\n") == (5, "answer\n", "save failed\n"),
   "party --report-text: rc 0 with a failed save -> 5")
sf = os.path.join(sidebars.PARTY_DIR, "seen.json")
if os.path.exists(sf): os.remove(sf)
run_main((3, "", "timed out waiting for %5\n"), "")
run_main((7, "screen\n", "%5 is waiting for input\n"), "")
run_main((0, "", "no report for %5\n"), "")
ok(not os.path.exists(sf), "party --report-text: rc 3, rc 7 and an empty report do not record a round as read")
run_main((0, "answer\n", ""), "")
ok(not os.path.exists(sf), "party --report-text: a report that carries no round records nothing")
run_main((0, "answer\n", ""), "", 3)
ok(json.load(open(sf)) == {"%5": 3}, "party --report-text: rc 0 records the round of the report it read, not the snapshot's current round (4)")
os.remove(sf)
ok(run_main((0, "answer\\n", ""), "save failed\\n", 3) == (5, "answer\\n", "save failed\\n") and json.load(open(sf)) == {"%5": 3},
   "party --report-text: rc 5 from a failed crew save still records the round as read")
os.remove(sf)
class Broken:
    def write(self, s): raise OSError("broken pipe")
    def flush(self): pass
real_out = sys.stdout
party.report_text = lambda *a: a[-1].update(round=3) or (0, "answer\\n", "")
party.crew_replied = lambda pane, out, rc: ""
sys.argv = ["party.py", "--report-text", "%5"]
sys.stdout = Broken()
try:
    party.main()
except OSError:
    pass
finally:
    sys.stdout = real_out
    party.report_text, party.crew_replied, sys.argv = real_rt, real_cr, real_argv
ok(not os.path.exists(sf), "party --report-text: a failed stdout write does not record the round as read")
party.ask("%5", "second?")
ok(read(sess[0], "round-002", "question.md") == "second?" and os.listdir(root) == sess, "crew: the second --ask makes round-002 in the same session")
os.rename(os.path.join(root, sess[0]), os.path.join(root, "20261101T000000Z-5"))
sess = ["20261101T000000Z-5"]
sidebars.crew_replied("%7", "lone\n", 0)
lone = [d for d in os.listdir(root) if d.endswith("Z-7")][0]
ok(read(lone, "round-001", "reply.md") == "lone\n" and not os.path.exists(os.path.join(root, lone, "round-001", "question.md")),
   "crew: --report-text with no round yet makes a round holding only the reply")
old, new = os.path.join(root, "20200101T000000Z-9"), os.path.join(root, "20261101T000000Z-8")
os.makedirs(old); os.makedirs(new)
past = time.time() - 15 * 86400
os.utime(old, (past, past))
ok(sidebars.crew_summoned("%5") == "" and not os.path.exists(old) and os.path.isdir(new) and os.path.isdir(os.path.join(root, sess[0])),
   "crew: --summon deletes session dirs older than 14 days and keeps newer ones")
fresh = [d for d in os.listdir(root) if d.endswith("Z-5") and d != sess[0]]
ok(len(fresh) == 1, "crew: --summon always makes a new session dir, even when the pane id has an older one")
party.ask("%5", "after summon")
ok(read(fresh[0], "round-001", "question.md") == "after summon" and not os.path.exists(os.path.join(root, sess[0], "round-003")),
   "crew: --ask after --summon writes round-001 of the new session, not the old one")
blocked = os.path.join(sys.argv[2], "blocked")
open(blocked, "w").close()
os.environ["XDG_STATE_HOME"] = blocked
rc, out, err = party.ask("%5", "third?")
ok(rc == 5 and out and "could not save" in err, "crew: --ask save failure -> rc 5 with a message on stderr, send time still printed")
print("\n".join(fails), file=sys.stderr)
sys.exit(1 if fails else 0)
EOF3
}
check "crew: rounds saved under XDG_STATE_HOME, 14-day cleanup, save failure -> rc 5" crew_ok

# transcript: time of the last usage entry; TTL from the latest usage that wrote cache (1h -> 3600)
cat >"$tmp/t.jsonl" <<'EOF'
{"type":"assistant","timestamp":"2026-11-03T04:00:00.000Z","message":{"usage":{"cache_creation":{"ephemeral_1h_input_tokens":500,"ephemeral_5m_input_tokens":0}}}}
{"type":"user","timestamp":"2026-11-03T04:05:00.000Z","message":{"content":"hi"}}
{"type":"assistant","timestamp":"2026-11-03T04:06:00.000Z","message":{"usage":{"input_tokens":10,"cache_read_input_tokens":40000,"cache_creation_input_tokens":90,"cache_creation":{"ephemeral_1h_input_tokens":0,"ephemeral_5m_input_tokens":0}}}}
{"type":"assistant","isSidechain":true,"timestamp":"2026-11-03T04:07:00.000Z","message":{"usage":{"input_tokens":999999}}}
EOF
ci=$(python3 -c 'import os,sys
sys.path.insert(0, os.path.dirname(sys.argv[1])); from party_hud import art, claude_log, codex_log, collect, common, markdown, processes, render, sidebars, ui
from datetime import datetime
last, ttl, used = claude_log.cache_info(sys.argv[2])
print(int(last - datetime.fromisoformat("2026-11-03T04:06:00+00:00").timestamp()), ttl, used)' "$party" "$tmp/t.jsonl")
check "transcript: last usage 04:06, TTL 3600, context 40100 tokens (subagent usage excluded)" test "$ci" = "0 3600 40100"

# a resumed session: 300 KB of attachments after the last usage entry
pad=$(printf 'x%.0s' $(seq 1000))
for _ in $(seq 300); do echo "{\"type\":\"attachment\",\"content\":\"$pad\"}"; done >>"$tmp/t.jsonl"
ci=$(python3 -c 'import os,sys
sys.path.insert(0, os.path.dirname(sys.argv[1])); from party_hud import art, claude_log, codex_log, collect, common, markdown, processes, render, sidebars, ui
print(claude_log.cache_info(sys.argv[2])[1:])' "$party" "$tmp/t.jsonl")
check "transcript: last usage found behind 300 KB of attachments, not taken for a new session" test "$ci" = "(3600, 40100)"

# statusline integration: Claude Code statusline JSON -> party-hud/<pane>.json; party.py reads HP max and model
sl="$root/integrations/claude-statusline.sh"
echo '{"session_id":"abc-1","context_window":{"used_percentage":12.4,"context_window_size":1000000},"transcript_path":"/p/abc-1.jsonl","model":{"display_name":"Opus 5.5 (1M context)"}}' |
  XDG_RUNTIME_DIR="$tmp/xdg" TMUX_PANE=%7 "$sl"
got=$(XDG_RUNTIME_DIR="$tmp/xdg" python3 -c 'import os,sys
sys.path.insert(0, os.path.dirname(sys.argv[1])); from party_hud import art, claude_log, codex_log, collect, common, markdown, processes, render, sidebars, ui
d=collect.read_party("%7"); print(d["session_id"], d["ctx_left"], d["ctx_size"], d["transcript"], d["model"])' "$party")
check "statusline integration: writes session, 88% left, max 1M, transcript, model base name" test "$got" = "abc-1 88 1000000 /p/abc-1.jsonl Opus 5.5"
check "statusline integration: broken JSON or outside tmux -> no error, no output" \
  test -z "$(echo garbage | XDG_RUNTIME_DIR="$tmp/xdg" TMUX_PANE=%9 "$sl"; echo '{}' | TMUX_PANE='' "$sl")"

check "art: the 8 big portraits are 384x432 RGBA PNGs (color type 6) so the frame corners and glow stay transparent" \
  python3 -c 'import glob, struct, sys
fs = glob.glob(sys.argv[1] + "/art/portrait-big-*.png")
ok = len(fs) == 8
for f in fs:
    b = open(f, "rb").read(33)
    ok = ok and struct.unpack(">II", b[16:24]) == (384, 432) and b[24:26] == bytes([8, 6])
sys.exit(not ok)' "$root"

check "art: the 8 small portraits are 192x216 RGBA PNGs (color type 6) so the frame corners stay transparent" \
  python3 -c 'import glob, struct, sys
fs = [f for f in glob.glob(sys.argv[1] + "/art/portrait-*.png") if "-big-" not in f]
ok = len(fs) == 8
for f in fs:
    b = open(f, "rb").read(33)
    ok = ok and struct.unpack(">II", b[16:24]) == (192, 216) and b[24:26] == bytes([8, 6])
sys.exit(not ok)' "$root"

check "art: the 7 heading labels are RGBA PNGs 44 px high, 20 px per cell wide (8, 10, 9, 9, 8, 9, 11 cells)" \
  python3 -c 'import struct, sys
cols = {"took": 8, "waited": 10, "asked": 9, "files": 9, "work": 8, "where": 9, "running": 11}
ok = True
for n, c in cols.items():
    b = open(sys.argv[1] + "/art/label-" + n + ".png", "rb").read(33)
    ok = ok and struct.unpack(">II", b[16:24]) == (c * 20, 44) and b[24:26] == bytes([8, 6])
sys.exit(not ok)' "$root"

check "art: the 5 select banners are 960 px wide PNGs, 240/192/159/138/120 high" \
  python3 -c 'import struct, sys
ok = True
for n, h in (("", 240), ("-5x1", 192), ("-6x1", 159), ("-7x1", 138), ("-8x1", 120)):
    b = open(sys.argv[1] + "/art/banner-select" + n + ".png", "rb").read(33)
    ok = ok and b[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", b[16:24]) == (960, h)
sys.exit(not ok)' "$root"

# cw: same result as the plain per-character algorithm for every BMP char, sampled astral chars and mixed strings; the char cache stays bounded
cw_ok() {
  python3 - "$party" <<'EOF'
import os, sys, unicodedata
sys.path.insert(0, os.path.dirname(sys.argv[1])); from party_hud import art, common
old = lambda s: sum(0 if unicodedata.combining(ch) else 2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)
astral = [chr(c) for c in (0x1F600, 0x1F468, 0x1F1E6, 0x20000, 0x2FFFD, 0xE0001, 0xF0000, 0xF0953, 0xF1841, 0xFFFFD, 0x10EEEE, 0x10FFFF)]
mixed = ["", "abc", "a一b" + chr(0x301) + "c", "\x00\x1f\x7f", "ab\u4e00\u0301\U0001F600x", chr(0x10EEEE) + chr(art.DIAC[1]) + chr(art.DIAC[2]), "plain ascii " * 20]
fails = []
bmp = [chr(c) for c in range(0x10000) if not 0xD800 <= c < 0xE000]
for s in bmp + astral + [chr(c) for c in art.DIAC] + mixed + ["".join(bmp[i : i + 50]) for i in range(0, len(bmp), 50)]:
    if common.cw(s) != old(s) or common.cw(s) != old(s):
        fails.append(repr(s[:20]))
cache = common._char_width
for i in range(cache.cache_info().maxsize + 500):
    common.cw(chr(0x4E00 + i))
if cache.cache_info().currsize > cache.cache_info().maxsize or cache.cache_info().maxsize is None:
    fails.append("cache over its bound")
print("\n".join(fails[:5]), file=sys.stderr)
sys.exit(1 if fails else 0)
EOF
}
check "cw: matches the per-character width algorithm, repeated calls agree, the cache is bounded" cw_ok

# party.py imports only what a sub-command needs: the long-running ones skip argparse, every short-lived one skips ui and render
imports_only_ok() {
  python3 - "$party" <<'EOF'
import json, os, subprocess, sys
root = os.path.dirname(sys.argv[1])
CHILD = """
import importlib, json, sys
argv, targets = json.loads(sys.argv[1]), json.loads(sys.argv[2])
sys.argv = ["party.py", *argv]
sys.path.insert(0, %r)
import party
calls = []
def fake(name):
    return lambda *a, **k: calls.append([name, list(a)]) or (0, "", "")
for t in targets:
    mod, _, name = t.rpartition(".")
    setattr(importlib.import_module(mod), name, fake(t))
    if mod == "party_hud.ui":
        importlib.import_module(mod).leave_without_teardown = lambda: None
rc = 0
try:
    party.main()
except SystemExit as e:
    rc = e.code
print(json.dumps({"calls": calls, "rc": rc, "loaded": [m for m in ("argparse", "shutil", "typing", "traceback", "party_hud.ui", "party_hud.render") if m in sys.modules]}))
""" % root
fails = []
def run(argv, targets):
    r = subprocess.run([sys.executable, "-c", CHILD, json.dumps(argv), json.dumps(targets)], capture_output=True, text=True, cwd=root)
    if r.returncode != 0 or not r.stdout.strip():
        fails.append("%s: rc %s %s" % (argv, r.returncode, r.stderr[-300:]))
        return None
    return json.loads(r.stdout)
def case(argv, target, args, forbidden):
    out = run(argv, [target])
    if out is None:
        return
    if out["calls"] != [[target, args]]:
        fails.append("%s: calls %s" % (argv, out["calls"]))
    if out["rc"] not in (0, None, 5, 6, 7):
        fails.append("%s: rc %s" % (argv, out["rc"]))
    bad = [m for m in out["loaded"] if m in forbidden]
    if bad:
        fails.append("%s: loaded %s" % (argv, bad))
long_run = ("argparse", "shutil", "typing", "traceback")
short = ("party_hud.ui", "party_hud.render")
case(["--sidebar"], "party_hud.ui.run_ui", [], long_run)
case(["--select"], "party_hud.ui.run_menu", [], long_run)
case(["--report"], "party_hud.ui.run_report", [None], long_run)
case(["--report", "%5"], "party_hud.ui.run_report", ["%5"], long_run)
for argv, target, args in (
    (["--ensure", "@1"], "party.ensure", ["@1"]),
    (["--reflow", "@1"], "party.reflow", ["@1"]),
    (["--nudge"], "party.nudge", [""]),
    (["--nudge", "@2"], "party.nudge", ["@2"]),
    (["--tidy"], "party.tidy", []),
    (["--restore-begin"], "party.restore_begin", []),
    (["--restore-end"], "party.restore_end", [[]]),
    (["--restore-end", "a:1.1", "b:2.1"], "party.restore_end", [["a:1.1", "b:2.1"]]),
    (["--remember-width"], "party.remember_width", []),
    (["--toggle"], "party.toggle", []),
    (["--ask", "%5", "hi"], "party.ask", ["%5", "hi"]),
    (["--dismiss", "%5"], "party.dismiss", ["%5"]),
    (["--summon", "codex"], "party.summon", ["codex", None, False, 60, False, False]),
    (["--report-text", "%5"], "party.report_text", ["%5", False, 600, None, {}]),
    (["--open-report", "%5"], "party.open_report_pane", ["", "%5"]),
):
    case(argv, target, args, short)
# the argparse path: same dispatch as before
case(["--sidebar", "--fixture", "F"], "party_hud.ui.run_ui", ["F"], ())
case(["--select", "--fixture", "F"], "party_hud.ui.run_menu", ["F"], ())
case(["--report", "%1", "--fixture", "F"], "party_hud.ui.run_report", ["%1", "F"], ())
case(["--report", "--fixture", "F"], "party_hud.ui.run_report", [None, "F"], ())
case(["--report", ""], "party_hud.ui.run_report", [None], long_run)
out = run(["--report", "%1", "--fixture", "F"], ["party_hud.ui.run_report"])
if out and "argparse" not in out["loaded"]:
    fails.append("--fixture did not go through argparse")
help_out = subprocess.run([sys.executable, sys.argv[1], "--help"], capture_output=True, text=True, cwd=root)
flat = " ".join(help_out.stdout.split())
if help_out.returncode != 0 or not flat.startswith("usage: party.py") or "tmux party sidebar: sessions as squads, agents as members" not in flat or "Exit code 6: the rules do not allow it (stderr says which one)." not in flat:
    fails.append("--help: rc %s %r" % (help_out.returncode, help_out.stdout[:80]))
typo = subprocess.run([sys.executable, sys.argv[1], "--sidbar"], capture_output=True, text=True, cwd=root)
if typo.returncode != 2 or "unrecognized arguments: --sidbar" not in typo.stderr:
    fails.append("typo flag: rc %s %r" % (typo.returncode, typo.stderr[-80:]))
print("\n".join(fails[:8]), file=sys.stderr)
sys.exit(1 if fails else 0)
EOF
}
check "party.py imports only what it needs: resident sub-commands skip argparse, short-lived ones skip ui and render" imports_only_ok

# the resident sub-commands leave through ui.leave_without_teardown, and only when their screen returns
leaves_ok() {
  python3 - "$party" "$fixture" <<'EOF'
import fcntl, io, os, pty, select, struct, subprocess, sys, termios, time
root = os.path.dirname(sys.argv[1])
sys.path.insert(0, root)
import party
from party_hud import ui
fails = []
def ok(cond, msg):
    if not cond: fails.append(msg)
events = []
class Stream(io.StringIO):
    def __init__(self, name):
        super().__init__()
        self.name = name
    def flush(self):
        events.append(self.name + " flush")
real = (ui.run_ui, ui.run_menu, ui.run_report, os._exit, sys.stdout, sys.stderr, sys.argv)
def main_with(argv, screen_error=None):
    events.clear()
    def screen(*a, **k):
        events.append("screen")
        sys.stdout.write("last bytes")
        if screen_error:
            raise screen_error
    ui.run_ui = ui.run_menu = ui.run_report = screen
    os._exit = lambda rc: events.append("exit %s" % rc)
    sys.stdout, sys.stderr, sys.argv = Stream("out"), Stream("err"), ["party.py", *argv]
    raised = None
    try:
        party.main()
    except Exception as e:
        raised = e
    finally:
        ui.run_ui, ui.run_menu, ui.run_report, os._exit, sys.stdout, sys.stderr, sys.argv = real
    return list(events), raised
for argv in (["--sidebar"], ["--select"], ["--report"], ["--report", "%5"]):
    ev, raised = main_with(argv)
    ok(raised is None and ev == ["screen", "out flush", "err flush", "exit 0"], "%s: flushes stdout and stderr, then exits with 0 after the screen returns (%s %s)" % (argv, ev, raised))
    ev, raised = main_with(argv, RuntimeError("boom"))
    ok(type(raised) is RuntimeError and ev == ["screen"], "%s: a screen that raises propagates and does not exit early (%s %r)" % (argv, ev, raised))
for argv in (["--sidebar", "--fixture", "F"], ["--select", "--fixture", "F"], ["--report", "%1", "--fixture", "F"]):
    ev, raised = main_with(argv)
    ok(raised is None and ev == ["screen"], "%s: the argparse path does not exit early (%s %r)" % (argv, ev, raised))
CHILD = """
import sys
sys.path.insert(0, %r)
sys.argv = ["party.py", "--report", "%%1"]
import party
from party_hud import claude_log, codex_log, collect, processes, ui
ui.get_snapshot = lambda f=None: collect.collect(%r)
ui.report_for = lambda a: {"text": "\\n".join(f"L{n}" for n in range(30)), "start": 1, "end": 2}
ui.tmux = lambda *a: "off" if "@party_anim" in a else ""
party.main()
print("NOT REACHED", flush=True)
""" % (root, sys.argv[2])
m, sl = pty.openpty()
fcntl.ioctl(sl, termios.TIOCSWINSZ, struct.pack("HHHH", 10, 60, 0, 0))
before = termios.tcgetattr(sl)
p = subprocess.Popen([sys.executable, "-c", CHILD], stdin=sl, stdout=sl, stderr=sl, env=dict(os.environ, TMUX_PANE="%99"), close_fds=True)
out = b""
def pump(until):
    global out
    while time.monotonic() < until:
        if select.select([m], [], [], 0.1)[0]:
            try:
                out += os.read(m, 65536)
            except OSError:
                return
        elif p.poll() is not None:
            return
t_end = time.monotonic() + 10
while b"\x1b[J" not in out and time.monotonic() < t_end:
    pump(time.monotonic() + 0.1)
os.write(m, b"q")
pump(time.monotonic() + 10)
try:
    rc = p.wait(timeout=5)
except subprocess.TimeoutExpired:
    p.kill()
    rc = None
while select.select([m], [], [], 0.2)[0]:
    out += os.read(m, 65536)
after = termios.tcgetattr(sl)
text = out.decode(errors="ignore")
tail = ui.MOUSE_OFF + "\x1b[?25h\x1b[?1049l"
ok(rc == 0, "report pane through party.py: exit code 0 (%r)" % rc)
ok(text.endswith(tail) and "NOT REACHED" not in text, "report pane through party.py: the last bytes written are mouse reporting off, cursor shown, alternate screen left (%r)" % text[-60:])
# macOS sets PENDIN in the local flags when a terminal goes back to canonical mode
settled = lambda t: [t[0], t[1], t[2], t[3] & ~termios.PENDIN, *t[4:]]
diff = [(i, a, b) for i, (a, b) in enumerate(zip(settled(before), settled(after))) if a != b]
ok(not diff, "report pane through party.py: the terminal settings are the ones it started with, PENDIN aside (%r)" % diff)
print("\n".join(fails[:8]), file=sys.stderr)
sys.exit(1 if fails else 0)
EOF
}
check "party.py leaves without the interpreter's teardown: the resident sub-commands flush and os._exit(0) after their screen returns, with the terminal restored" leaves_ok

exit "$fail"
