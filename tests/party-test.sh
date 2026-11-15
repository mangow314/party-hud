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
empty = towns + [dict(towns[1], name="Empty", agents=[])]

done = dict(agents[0], status="done", hp_left=410000, hp_max=1000000)
mdt = "# T\n\n- a **b** `c`\n\n| h | i |\n|---|---|\n| 1 | 2 |\n\n```\ncode line that is long\n```\nlast line of text"
rep = {"live": False, "start": 1, "end": 2, "text": mdt, "subagents": [{"desc": "d", "type": "t", "text": mdt + " 2"}]}
mk = lambda pane, status: {"pane": pane, "status": status}
import tempfile
png_dir = tempfile.mkdtemp()
def png(name, data=b"x"):
    open(os.path.join(png_dir, name), "wb").write(data)
    return os.path.join(png_dir, name)
ok(ui.handle_key("r", {"focus": "party", "sel": "%1", "squad": None, "peek": False}, towns) == "report"
   and ui.handle_key("r", {"focus": "party", "sel": None, "squad": None, "peek": False}, towns) is None,
   "r in the sidebar opens the report pane; with no member selected it does nothing")
mm = lambda pane, name, status, lead=None: dict(mk(pane, status), name=name, **({"lead": lead} if lead else {}))
mt = [{"name": "Studio", "agents": [mm("%1", "a", "idle"), mm("%2", "b", "working"), mm("%3", "c", "waiting"), mm("%4", "d", "done")]},
      {"name": "Empty", "agents": []}, {"name": "Lab", "agents": [mm("%5", "lead", "working"), mm("%6", "w1", "idle", "%5"), mm("%7", "w2", "waiting", "%5"), mm("%8", "e", "waiting")]}]
real_tmux, real_snap, real_sb_tmux = ui.tmux, ui.get_snapshot, sidebars.tmux
calls = []
ui.tmux = lambda *a: calls.append(a)
sidebars.tmux = lambda *a: calls.append(a) or ("%9\n" if a[0] in ("new-pane", "split-window") else "")
ui.get_snapshot = lambda f=None: {"towns": [{"name": "A", "agents": []}]}
ui.open_select()
ok(calls == [("display-message", "no party members")], "--menu: no members, only the message and no pane")
calls.clear()
ui.get_snapshot = lambda f=None: {"towns": mt}
sidebars._new_pane = False
ui.open_select()
opened_cmd = next(c for c in calls if c[0] == "split-window")
ok(opened_cmd[-1].endswith("party.py --select") and not any("display-menu" in " ".join(c) for c in calls),
   "--menu: with members a pane is opened that runs --select, and no display-menu is used")
sidebars._new_pane = True
calls.clear()
ui.open_select()
float_cmd = next(c for c in calls if c[0] == "new-pane")
ok(float_cmd[float_cmd.index("-T") + 1] == " Party " and float_cmd[-1].endswith("party.py --select"), "--menu: a floating pane is titled Party")
sidebars._new_pane = None
ui.tmux, ui.get_snapshot, sidebars.tmux = real_tmux, real_snap, real_sb_tmux
opened = []
real_open = ui.open_report_pane
ui.open_report_pane = lambda *a: opened.append(a)
os.environ["TMUX_PANE"] = "%5"
ui.open_report("%7")
ui.open_report_pane = real_open
ok(opened == [("%5", "%7")], "r: the report opens beside the sidebar's own window, for the selected member")
sm = lambda pane, name, status, lead=None: {**dict(done, pane=pane, name=name, status=status, round=1, summons=[], focus=False), **({"lead": lead} if lead else {})}
sst = [{"name": "S", "agents": [sm("%1", "idle1", "idle"), sm("%2", "work1", "working"), sm("%3", "done1", "done"), sm("%4", "wait1", "waiting"), sm("%5", "sleep1", "sleep"),
                               sm("%6", "c1", "waiting", "%9"), sm("%7", "c2", "done", "%2"), sm("%8", "cc", "waiting", "%6")]},
       {"name": "T", "agents": [sm("%9", "far", "idle"), sm("%10", "c3", "waiting", "%9"), sm("%11", "c4", "waiting", "%9"), sm("%12", "c5", "waiting", "%2")]}]
srs = render.select_roster(sst)
srep = {"text": "## Layout\n\nThe list fills the pane.\n\n" + "\n".join(f"- point {i}" for i in range(80)), "start": 100.0, "end": 400.0, "live": False,
        "task": {"ask": "fix the menu size", "files": [], "cmds": 0, "agents": 0, "dir": "~/work/app", "branch": None, "cwd": "/w"}}
PH = chr(0x10EEEE)
srows_of = lambda w, h, sel, rep=srep, art=False, ro=srs, tw=sst: render.render_select(ro, tw, sel, w, h, rep, 4000.0, None, art)
real_gs, real_rf = ui.get_snapshot, ui.report_for
ui.report_for = lambda a: {"status_seen": a["status"]}
q = [("S", {"pane": "%1", "status": "working"})]
ui.get_snapshot = lambda f=None: {"towns": [{"agents": [{"pane": "%1", "status": "done"}]}]}
seen = ui.refresh_live(q, 0)
ui.get_snapshot = lambda f=None: {"towns": [{"agents": []}]}
gone_ = ui.refresh_live(q, 0)
ui.get_snapshot, ui.report_for = real_gs, real_rf
ok(seen == {"status_seen": "done"} and q[0][1]["status"] == "done" and gone_ is None,
   "live page re-read: the member's new status decides the report; a member the snapshot no longer lists -> None (stop re-reading)")
calls = []
real_tmux = sidebars.tmux
def fake_tmux(usage, rows="%1 1 s1 r\n%2 0 s r\n"):
    def run(*a):
        calls.append(a)
        return usage if a[0] == "list-commands" else rows if a[0] == "list-panes" else "%9\n" if a[0] in ("new-pane", "split-window") else ""
    return run
open_cmd = lambda: next(c for c in calls if c[0] in ("new-pane", "split-window"))
sidebars._new_pane = None
sidebars.tmux = fake_tmux("new-pane (newp) [-AbCDefhIkKLMOPvWZ] [-c start-directory] [-F format] [-t target-pane] [shell-command]")
sidebars.open_report_pane("@1", "%7")
c = open_cmd()
ok(c[0] == "new-pane" and all(f in c for f in ("-x80%", "-y80%", "-X10%", "-Y10%"))
   and "-O" not in c and "-D" not in c and c[c.index("-t") + 1] == "%2" and c[-1].endswith("--report %7"),
   "report pane: tmux with new-pane (O flag in its usage) floats it at 80% x 80%, beside the first non-sidebar pane")
ok(("set-option", "-p", "-t", "%9", "@party_report", "1", ";", "set-option", "-p", "-t", "%9", "allow-passthrough", "on") in calls
   and not any("window-style" in c or "window-active-style" in c for c in calls),
   "report pane: marked @party_report and allow-passthrough on, this pane only, in one tmux call; the terminal's own background stays")
calls.clear()
sidebars.open_report_pane("@1", "")
ok(not any(c[0] == "list-commands" for c in calls) and open_cmd()[0] == "new-pane" and open_cmd()[-1].endswith("party.py --report"),
   "report pane: the new-pane answer is cached for the life of the process")
for usage in ("split-window (splitw) [-bdefhIPvZ] [-c start-directory] [-l size] [-t target-pane] [shell-command]", ""):
    calls.clear()
    sidebars._new_pane = None
    sidebars.tmux = fake_tmux(usage)
    sidebars.open_report_pane("@1", "%7")
    c = open_cmd()
    ok(c[0] == "split-window" and c[1:4] == ("-h", "-l", "50%") and "new-pane" not in [x[0] for x in calls] and c[c.index("-t") + 1] == "%2",
       "report pane: tmux without new-pane (" + ("no O flag" if usage else "command unknown") + ") splits the window in half")
sidebars.tmux = real_tmux
sidebars._new_pane = True
def sel_open(win_w, select=True, cell="19,42"):
    calls.clear()
    sidebars.tmux = lambda *a: calls.append(a) or (win_w + ("," + cell if cell else "") if a[0] == "display-message" else "%1 1 s r\n" if a[0] == "list-panes" else "%9\n" if a[0] == "new-pane" else "")
    sidebars.open_report_pane("@1", "", select)
    sidebars.tmux = real_tmux
    return open_cmd()
ok((sidebars.report_cols(0.5), sidebars.select_cols(0.5), sidebars.report_cols(0.452), sidebars.select_cols(0.452)) == (105, 82, 113, 90),
   "pane widths: report_cols and select_cols are 105 / 82 at cell ratio 0.5 and 113 / 90 at 0.452")
c = sel_open("200")
ok(c[c.index("-x90") + 1] == "-y80%" and "-X55" in c and "-Y10%" in c,
   "select pane: tmux says cells of 19 x 42 pixels, so in a 200-column window it is select_cols(19 / 42) = 90 wide, centred, 80% high from 10%")
c = sel_open("200", cell="")
ok(c[c.index("-x82") + 1] == "-y80%" and "-X59" in c, "select pane: tmux saying no cell size gives the 0.5 width, 82 columns")
c = sel_open("200", cell="0,0")
ok("-x82" in c and "-X59" in c, "select pane: a cell size of 0 gives the 0.5 width, 82 columns")
c = sel_open("60")
ok("-x60" in c and "-X0" in c, "select pane: in a 60-column window it is no wider than the window")
c = sel_open("", select=False)
ok(c[1:5] == ("-x80%", "-y80%", "-X10%", "-Y10%"), "report pane: an unreadable window width keeps -x80% -y80% -X10% -Y10%")
c = sel_open("400", select=False)
ok(c[1:5] == ("-x113", "-y80%", "-X143", "-Y10%"),
   "report pane: cells of 19 x 42 pixels, in a 400-column window it is report_cols(19 / 42) = 113 wide, centred, 80% high from 10%")
c = sel_open("400", select=False, cell="")
ok(c[1:5] == ("-x105", "-y80%", "-X147", "-Y10%"), "report pane: tmux saying no cell size gives the 0.5 width, 105 columns")
c = sel_open("400", select=False, cell="x,0")
ok(c[1:5] == ("-x105", "-y80%", "-X147", "-Y10%"), "report pane: a cell size that is not a number gives the 0.5 width, 105 columns")
c = sel_open("100", select=False)
ok(c[1:5] == ("-x80", "-y80%", "-X10", "-Y10%"), "report pane: in a 100-column window it is 80% of the window, centred")
c = sel_open("n/a")
ok("-x80%" in c and "-X10%" in c, "select pane: an unreadable window width keeps the 80% / 10% size")
def fit(flag, select, new=True, win_w=200, cell="19,42"):
    calls.clear()
    sidebars._new_pane = new
    sidebars.tmux = lambda *a: calls.append(a) or (f"{flag},{win_w},50,{cell}" if a[0] == "display-message" else "")
    sidebars.fit_report_pane("%9", select)
    sidebars.tmux = real_tmux
    return [c for c in calls if c[0] != "display-message"]
ok(fit("1", True) == [("resize-pane", "-t", "%9", "-x", "90", "-y", "40", ";", "move-pane", "-t", "%9", "-X", "55", "-Y", "5")],
   "fit pane: cells of 19 x 42 pixels, a floating pane is resized and moved to the select screen's size (90 columns) and place")
ok(fit("1", True, cell=",") == [("resize-pane", "-t", "%9", "-x", "82", "-y", "40", ";", "move-pane", "-t", "%9", "-X", "59", "-Y", "5")]
   and fit("1", True, cell="0,0") == fit("1", True, cell=","),
   "fit pane: no cell size, or 0, gives the select screen's 0.5 width, 82 columns")
ok(fit("1", False, win_w=100) == [("resize-pane", "-t", "%9", "-x", "80", "-y", "40", ";", "move-pane", "-t", "%9", "-X", "10", "-Y", "5")],
   "fit pane: in a 100-column window the report page's pane is 80% wide, centred, 80% high from 10%")
ok(sidebars.report_span(400, 0.5) == (105, 147) and sidebars.report_span(100, 0.5) == (80, 10) and sidebars.select_span(200, 0.5) == (82, 59),
   "report span: report_cols wide and centred in a wide window, 80% of a narrow one; select span likewise")
ok(fit("1", False, win_w=400) == [("resize-pane", "-t", "%9", "-x", "113", "-y", "40", ";", "move-pane", "-t", "%9", "-X", "143", "-Y", "5")]
   and fit("1", False, win_w=400, cell=",") == [("resize-pane", "-t", "%9", "-x", "105", "-y", "40", ";", "move-pane", "-t", "%9", "-X", "147", "-Y", "5")],
   "fit pane: in a 400-column window the report page's pane is report_cols wide (113 at 19 x 42 pixels cells, 105 without a cell size), centred")
for r_ in (0.4, 0.452, 0.5, 0.55, 0.6):
    sb = ui.select_banner(sidebars.select_cols(r_) - 1, 50, r_)
    ok(sb[1:3] == (10, 4) and abs(sb[0] - (sidebars.select_cols(r_) - 1)) <= 1,
       f"pane widths: at cell ratio {r_} the select banner is the 10-row 4:1 image, as wide as its column")
for r_ in (0.4, 0.452, 0.5):
    right = sidebars.report_cols(r_) - 1 - ui.SPLIT_SIDE_COLS - ui.SPLIT_GAP
    bc = ui.banner_cells(sidebars.report_cols(r_) - 1, r_)
    ok(abs(bc[0] - right) <= 1 and bc[1:] == (6, 6),
       f"pane widths: at cell ratio {r_} the report banner is the 6-row 6:1 image, as wide as its column")
ok(all(sidebars.report_cols(r_) - 3 >= art.SPLIT_MIN_WIDTH for r_ in (0.4, 0.452, 0.5, 0.55, 0.6, 0.65)),
   "pane widths: the report pane at its widest still draws the split report page (two columns) at cell ratios 0.4 to 0.65")
def shape_ok(cols_in, rows_max, r_, b):
    cols, rows, k = b
    a = cols_in * r_ / rows
    return (rows == max(1, min(rows_max, round(min(len(art.DIAC), cols_in) * r_ / 4))) and cols <= cols_in
            and cols - rows * k / r_ <= 1 + 1e-9 and abs(a - k) <= min(abs(a - j) for j in art.BANNER_RATIOS) + 1e-9)
fit_scan = [(w - ui.SPLIT_SIDE_COLS - ui.SPLIT_GAP, r_, b) for r_ in (0.4, 0.452, 0.5, 0.55, 0.6) for w in [*range(100, 260, 7), sidebars.report_cols(r_) - 1] for b in [ui.banner_cells(w, r_)]]
ok(all(shape_ok(min(len(art.DIAC), w), ui.REPORT_BANNER_MAX_ROWS, r_, b) for w, r_, b in fit_scan),
   "report banner: in split widths rows follow the width, cols never exceed it, the cells are at most one column wider than the image, and the image is the closest k:1 to the cells' shape")
sel_scan = [(w, r_, b) for r_ in (0.4, 0.452, 0.5, 0.55, 0.6) for w in [*range(60, 200, 7), sidebars.select_cols(r_) - 1] for b in [ui.select_banner(w, 50, r_)] if b]
ok(sel_scan and all(shape_ok(w, ui.SELECT_BANNER_MAX_ROWS, r_, b[:3]) for w, r_, b in sel_scan)
   and all(b[3] == (w - b[0]) // 2 and b[0] <= w for w, r_, b in sel_scan),
   "select banner: rows follow the width, the cells are at most one column wider than the closest k:1 image, centred, never wider than the screen")
ok(ui.select_banner(87, 50, 19 / 42)[:3] == (87, 10, 4) and ui.banner_cells(136, 19 / 42) == (104, 6, 8),
   "banners: a drawable width one or two columns short of the pane's keeps the row count and the image size")
ok(fit("0", True) == [] and fit("1", True, new=False) == [], "fit pane: a pane that is not floating, or tmux without new-pane, is left alone")
sidebars._new_pane = None
fit_calls = []
real_fit, real_rs, real_rr = ui.fit_report_pane, ui.run_select, ui.run_report
ui.fit_report_pane = lambda p, s: fit_calls.append(("fit", p, s))
ui.run_select = lambda p=None, f=None, images=None: fit_calls.append(("select", p)) or ("%1" if p is None else None)
ui.run_report = lambda p, f=None, back=False, images=None: fit_calls.append(("report", p)) or "%1"
os.environ["TMUX_PANE"] = "%5"
ui.run_menu()
ui.fit_report_pane, ui.run_select, ui.run_report = real_fit, real_rs, real_rr
ok(fit_calls == [("select", None), ("fit", "%5", False), ("report", "%1"), ("fit", "%5", True), ("select", "%1")],
   "--menu: the pane is enlarged before the report page and shrunk again before the select screen")
killed = []
sidebars.tmux = lambda *a: "%1 @1 s1 r\n%2 @1 s r1\n%3 @2 s1 r\n%4 @2 s r\n" if a[0] == "list-panes" else killed.append(a[2]) or ""
sidebars.tidy()
sidebars.tmux = real_tmux
ok(sorted(killed) == ["%1", "%2"], "Tidy: a report pane counts as a sidebar, so a window with only a sidebar and a report is closed")
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
for t in towns:
    for a in t["agents"]:
        a["window"] = "@" + a["pane"][1:]  # in the fixture every member has its own window
fh = {"focus": "party", "sel": "%1", "squad": None, "peek": False}
ui.follow_here(fh, towns, {"session": "Server", "window": "@4"})
ok(fh["sel"] == "%4" and fh["focus"] == "party", "Switching to another window: cursor follows to the member there")
ui.follow_here(fh, towns, {"session": "Studio", "window": "@9"})
ok(fh["focus"] == "squad" and fh["squad"] == 0, "Switching to a window without members: cursor rests on that squad")
fh = {"focus": "party", "sel": "%2", "squad": None, "peek": False}
towns[0]["agents"][1]["window"] = towns[0]["agents"][0]["window"]  # %1 and %2 share a window
ui.follow_here(fh, towns, {"session": "Studio", "window": towns[0]["agents"][0]["window"]})
ok(fh["sel"] == "%2", "Cursor already on a member of that window (just clicked): keep it")
import os, unicodedata
art.ART_DIR = tempfile.mkdtemp()
ok(art.load_art() is None, "No images in art/: load_art returns None (text version)")
flat_banners = [f"{n}-{k}x1" for k in range(5, 9) for n in art.BANNER_FILES]
for i, n in enumerate(art.PORTRAIT_FILES + art.CREST_FILES + art.BANNER_FILES + art.PORTRAIT_FILES + flat_banners + list(art.LABEL_COLS)):
    prefix = "portrait-" if i < 8 else "crest-" if i < 16 else "banner-" if i < 20 or i >= 28 and i < 44 else "label-" if i >= 44 else "portrait-big-"
    open(os.path.join(art.ART_DIR, prefix + n + ".png"), "wb").write(b"PNG" + bytes([i]))
for j, n in enumerate(["select"] + [f"select-{k}x1" for k in range(5, 9)]):
    open(os.path.join(art.ART_DIR, "banner-" + n + ".png"), "wb").write(b"PNG" + bytes([51 + j]))
imgs = art.load_art()
rd = lambda k: (open(imgs[k][0], "rb").read(), *imgs[k][1:])
ok(imgs and len(imgs) == 56 and rd(art.select_banner_id(7)) == (b"PNG" + bytes([51 + 3]),) and rd(art.label_id("running")) == (b"PNG" + bytes([50]),) and rd(art.banner_id("waiting", True, False, 7)) == (b"PNG" + bytes([28 + 2 * 4 + 1]),) and rd(art.BIG_PORTRAIT_ID + 3) == (b"PNG\x17",) and rd(art.PORTRAIT_ID + 2) == (b"PNG\x02", 6, 3) and rd(art.CREST_ID + 7) == (b"PNG\x0f", 4, 2)
   and rd(art.BANNER_ID + 2) == (b"PNG\x12",),
   "All 56 images present: portraits 6x3 cells, crests 4x2 cells, 4 banners and the select banner in 5 ratios, 8 big portraits and 7 heading labels (no cell size stored)")
import builtins
reads, real_open = [], builtins.open
class Spy:
    def __init__(self, f, path): self.f, self.path = f, path
    def __enter__(self): return self
    def __exit__(self, *e): self.f.close()
    def read(self, *n): reads.append(self.path); return self.f.read(*n)
builtins.open = lambda path, *a, **k: Spy(real_open(path, *a, **k), path) if str(path).startswith(art.ART_DIR) else real_open(path, *a, **k)
try:
    loaded = art.load_art()
    n_load = len(reads)
    sent_one = art.send_image(loaded, art.PORTRAIT_ID + 2, 6, 3)
    n_one = len(reads)
    lost = loaded[art.LABEL_ID][0]
    lost_bytes = real_open(lost, "rb").read()
    os.remove(lost)
    real_err, real_pdir = common.ERROR_LOG, common.PARTY_DIR
    common.PARTY_DIR = png_dir
    common.ERROR_LOG = os.path.join(png_dir, "err.log")
    try:
        sent_lost, lost_err = art.send_image(loaded, art.LABEL_ID, 8, 1), None
    except Exception as e:
        sent_lost, lost_err = None, e
    common.ERROR_LOG, common.PARTY_DIR = real_err, real_pdir
    real_open(lost, "wb").write(lost_bytes)
finally:
    builtins.open = real_open
ok(loaded and not any(isinstance(x, bytes) for v in loaded.values() for x in v) and n_load == 0
   and sent_one == art.kitty_image(art.PORTRAIT_ID + 2, b"PNG\x02", 6, 3) and n_one == 1 and reads == [loaded[art.PORTRAIT_ID + 2][0]]
   and lost_err is None and sent_lost == "" and "FileNotFoundError" in real_open(os.path.join(png_dir, "err.log")).read(),
   "Images: a file is read when it is sent, not by load_art (no bytes kept, one file per image sent); an unreadable file sends nothing, raises nothing and is logged")
old_ids = [art.BANNER_ID + 4 * j + i for j in range(5) for i in range(4)] + [art.BIG_PORTRAIT_ID + i for i in range(8)] + [art.LABEL_ID + i for i in range(7)]
sel_ids = [art.select_banner_id(k) for k in range(4, 9)]
ok(len(set(sel_ids)) == 5 and not set(sel_ids) & set(old_ids) and not set(sel_ids) & set(range(art.PORTRAIT_ID, art.PORTRAIT_ID + 8))
   and not set(sel_ids) & set(range(art.CREST_ID, art.CREST_ID + 8)) and art.select_banner_id() == art.SELECT_BANNER_ID == 0x7A0600,
   "select banner: five image ids of its own, clear of every portrait, crest, report banner, big portrait and label id")
ok([art.banner_id(s, r, m) for s, r, m in (("done", True, False), ("waiting", True, False), ("working", True, False), ("done", False, False))] == [0x7A0300, 0x7A0301, 0x7A0302, 0x7A0303]
   and art.banner_id("waiting", True, False, 8) == 0x7A0311,
   "report banner ids stay as they were: select banner does not change banner_id")
ok(art.art_supported("", "xterm-ghostty") and art.art_supported("", "xterm-kitty") and not art.art_supported("", "xterm-256color")
   and not art.art_supported("", "wezterm") and art.art_supported("on", "xterm-256color") and not art.art_supported("off", "xterm-ghostty"),
   "Images: auto on for Ghostty / Kitty, text elsewhere; @party_art on / off forces it")
os.remove(os.path.join(art.ART_DIR, "crest-moon.png"))
ok(art.load_art() is None, "One image missing -> whole UI falls back to text")
ok(common.cw(strip(art.image_row(art.PORTRAIT_ID, 2, 6))) == 6 and art.image_row(art.PORTRAIT_ID, 2, 6).count("\U0010EEEE") == 6,
   "Placeholder row is 6 cells: diacritics (row, column) take no width")
row = art.image_row(0x7A0103, 1, 2)
ok(len(art.DIAC) >= 80 and art.DIAC[:3] == [0x305, 0x30D, 0x30E] and len(set(art.DIAC)) == len(art.DIAC)
   and common.cw(strip(art.image_row(art.BANNER_ID, 9, 297))) == 297 and len(art.DIAC) == 297,
   "Placeholders: 297 distinct diacritics, so a banner row can fill a wide right column")
bp = art.big_portrait_id(done)
ok(bp != art.portrait_id(done) and bp not in range(art.PORTRAIT_ID, art.PORTRAIT_ID + 8) and bp >> 8 != art.BANNER_ID >> 8,
   "Report: the big portrait has its own image id, apart from the sidebar portrait and the banners")
ok(row.startswith("\x1b[38;2;122;1;3m") and "\U0010EEEE̍̅\U0010EEEE̍̍" in row,
   "Placeholders: foreground = image id, row-2 diacritic 030D, column diacritics 0305 / 030D")
os.environ["TMUX"] = "x"
seq = art.kitty_image(7, b"x" * 5000, 6, 3)
ok(seq.startswith("\x1bPtmux;\x1b\x1b_Ga=T,U=1,f=100,i=7,c=6,r=3,q=2,m=1;") and seq.count("\x1bPtmux;") == 2
   and seq.endswith("m=0;" + __import__("base64").b64encode(b"x" * 5000).decode()[4096:] + "\x1b\x1b\\\x1b\\"),
   "Image upload: base64 in 4096-char chunks, wrapped in tmux passthrough, last chunk m=0")
ok(art.kitty_delete(5) == "\x1bPtmux;\x1b\x1b_Ga=d,d=I,i=5,q=2\x1b\x1b\\\x1b\\",
   "Image delete: a=d,d=I for the id, wrapped in tmux passthrough, so a resend with new cells is not shown at the old size")
nw = [{"pane": p, "status": s} for p, s in (("%1", "idle"), ("%2", "done"), ("%3", "waiting"), ("%4", "done"))]
ok(ui.next_waiting(nw, "%1") == "%3" and ui.next_waiting(nw, "%3") == "%3"
   and ui.next_waiting([dict(a, status="idle") if a["status"] == "waiting" else a for a in nw], "%2") == "%4",
   "n / prefix a: jump to waiting first, then cycle unseen done")
lead_idle = {"pane": "%1", "status": "idle"}
crew_done = {"pane": "%2", "status": "done", "lead": "%1"}
solo_done = {"pane": "%3", "status": "done"}
crew_wait = {"pane": "%4", "status": "waiting", "lead": "%1"}
ok([m["pane"] for _, m in ui.report_queue([{"name": "A", "agents": [lead_idle, crew_done, solo_done]}])] == ["%3", "%1", "%2"]
   and [m["pane"] for _, m in ui.report_queue([{"name": "A", "agents": [lead_idle, crew_done, crew_wait]}])][0] == "%4"
   and ui.report_queue([{"name": "A", "agents": [lead_idle, crew_done, solo_done]}], "%2")[0][1]["pane"] == "%2",
   "crew done: report queue skips it, a waiting crew and a plain done member still lead, the pane asked for stays first")
ok(ui.next_waiting([lead_idle, crew_done, solo_done], "%1") == "%3" and ui.next_waiting([lead_idle, crew_done], "%1") is None
   and ui.next_waiting([lead_idle, crew_done, crew_wait], "%1") == "%4",
   "crew done: prefix a skips it; a waiting crew still counts")
cr = art.crest_ids(["dotfiles", "homelab", "notes", "projects", "scratch"])
ok(len(set(cr.values())) == 5, "Crests: unique for up to 8 squads (real collisions: notes/projects, dotfiles/scratch)")
ok(len(set(art.crest_ids(f"s{i}" for i in range(8)).values())) == 8 and len(art.crest_ids(f"s{i}" for i in range(9))) == 9,
   "Crests: exactly 8 squads use all 8; repeats start at the 9th")
ph = ["", "BANNER1", "BANNER2", ""]
pbody = ["P1a", "P1b", "", "P2", "", common.fg("green") + "c1", "", common.fg("green") + "c2", "", "P3", "", "P4", "", "P5"]
pf = render.report_frames(ph + pbody, 100)
pn = len(ph + pbody)
ok(pf[-1] == ph + pbody and 2 <= len(pf) <= 5 and all(len(f) == pn for f in pf), "Report animation: at most 5 frames, the last one is the whole page")
ok(all(f[:3] == ph[:3] for f in pf) and pf[0][3:9] == ["", "P1a", "P1b", "", "P2", ""] and pf[0][9:] == [""] * (pn - 9) and [r for r in pf[0] if r] == ["BANNER1", "BANNER2", "P1a", "P1b", "P2"],
   "Report animation: the first frame has the head rows and the first paragraphs; the rest is blank")
cb = next(i for i, r in enumerate(ph + pbody) if r.endswith("c1"))
ok(all(bool(f[cb]) == bool(f[cb + 2]) for f in pf) and any(f[cb] for f in pf) and not pf[0][cb], "Report animation: a code block with a blank row inside is never cut")
ok(render.report_frames(ph + ["only", "one"], 100) == [ph + ["only", "one"]] and render.report_frames(ph + ["a"], 100) == [ph + ["a"]],
   "Report animation: fewer than 2 paragraphs after the head does not animate")
ok(render.report_frames(ph + pbody, 6)[-1] == ph + pbody and len(render.report_frames(ph + pbody, 6)) < len(pf)
   and render.report_frames(ph + pbody + ["", "hint"], 100, tail=2)[0][-2:] == ["", "hint"],
   "Report animation: steps that change nothing in the visible rows are dropped; the tail rows are always shown")
fl_, fr_ = render.report_parts(done, "Studio", dict(rep, text="\n\n".join(f"para {n}" for n in range(9))), [], 150, art=True, banner=(88, 10), portrait=(24, 14), height=40, fixed=True)
ff = render.report_frames(fr_, 40)
ok(len(ff) > 1 and all([common.cw(r) for r in render.report_view(fl_, f, 40, 0)[0]][:14] == [common.cw(r) for r in render.report_view(fl_, fr_, 40, 0)[0]][:14] for f in ff)
   and all(common.cw(r) <= common.cw(g) for f in ff for r, g in zip(render.report_view(fl_, f, 40, 0)[0], render.report_view(fl_, fr_, 40, 0)[0])),
   "Report animation: every frame keeps the left column and never makes a row wider than the full page")
vf = ["", "B", "", "p0", "", "p1", "p1b", "", "p2", "", "p3"]
vf_ = render.report_frames(vf, 8)
vg = ["", "B", "", "p0", "p0b", "", "p1", "", "p2"]
ok(len(vf_) == 2 and vf_[-1] == vf and len(render.report_frames(vf, 100)) == 4 and render.report_frames(vg, 6) == [vg],
   "Report animation: a frame whose first `height` rows equal the next frame's is not drawn; fewer than 2 distinct frames give [right]")
ok(ui.report_anim_enabled("") and ui.report_anim_enabled("on") and not ui.report_anim_enabled("off\n") and not ui.report_anim_enabled(" off "),
   "@party_anim: off turns the animation off; unset or anything else keeps it")
fe = next(a for a in agents if a["pane"] == "%1")
an, a0 = {}, dict(fe, status="working")
a1 = dict(a0, hp=48, hp_left=96000, sp=(1320, 3600))
sm = dict(a0, hp=86, hp_left=172000, sp=(2460, 3600))
ui.animate(an, [a0], 0.0)
d1 = ui.animate(an, [a1], 10.0)
ok(not d1[2] and d1[0][0]["hp"] == 48 and d1[0][0]["hp_delta"] == 48 - a0["hp"] and d1[0][0]["sp_delta"] == 22 - render.sp_points(a0),
   "Sidebar animation: HP and SP show the new value at once, with the change as hp_delta / sp_delta")
lab = [ui.animate(an, [a1], t) for t in (19.9, 20.0)]
ok(not lab[0][2] and lab[0][0][0]["hp_delta"] is not None and not lab[1][2] and lab[1][0][0] is a1,
   "Sidebar animation: the change labels stay 10 s (still there at 9.9 s, gone at 10 s) and never make the loop busy; then nothing is copied")
a2, rs = dict(a1, hp=88, hp_left=176000), {}
ui.animate(rs, [a0], 0.0)
ui.animate(rs, [a1], 10.0)
ui.animate(rs, [a2], 12.0)
r1, r2 = ui.animate(rs, [a2], 21.9), ui.animate(rs, [a2], 22.0)
ok(r1[0][0]["hp_delta"] == 40 and r2[0][0] is a2,
   "Sidebar animation: a new change within 10 s of the old label shows the new change and restarts the 10 s")
sa = {}
ui.animate(sa, [a0], 0.0)
sd, _, sbusy = ui.animate(sa, [sm], 10.0)
ok(not sbusy and sd[0] is sm, "Sidebar animation: a change under 5 points (HP 88 to 86, SP 42 to 41) shows no label and is not busy")
nb, nl, nbusy = ui.animate({}, [a0], 5.0)
ok(nb[0] is a0 and not nl and not nbusy and "hp_delta" not in nb[0],
   "Sidebar animation: a member seen for the first time has no label, nothing copied, nothing due")
fa = {}
ui.animate(fa, [a0], 0.0)
d0 = dict(a0, status="done")
lit = [bool(ui.animate(fa, [d0], t)[1]) for t in (30.0, 30.4, 30.5, 31.0, 31.5, 33.5, 33.9, 34.0)]
fc = {}
ui.animate(fc, [a0], 0.0)
fb = ui.animate(fc, [d0], 30.0)[2], ui.animate(fc, [d0], 33.9)[2], ui.animate(fc, [d0], 34.0)[2]
ok(lit == [True, True, False, True, False, False, False, False] and fb == (True, True, False),
   "Sidebar animation: a member turning done pulses the frame every 0.5 s (lit, plain, lit, plain...) for 4 s, then the frames stop")
ok(not ui.animate({}, [dict(a0, status="done")], 30.0)[1] and not ui.animate(fa, [dict(d0, status="idle")], 40.0)[1],
   "Sidebar animation: no flash for a member first seen as done, or leaving to idle")
fw = ui.animate({"%1": {"last": [88, 42], "delta": [None, None], "t0": [0, 0], "status": "done", "flash": None}}, [dict(a0, status="waiting")], 1.0)[1]
ok(fw == {"%1"}, "Sidebar animation: turning waiting flashes too")
gone = {}
ui.animate(gone, [a0, dict(a0, pane="%9")], 0.0)
ui.animate(gone, [a0], 1.0)
ok(set(gone) == {"%1"}, "Sidebar animation: the state of a member that disappeared is dropped")
on = render.render(towns, 33, "%2", flash={"%1", "%2"})
off = render.render(towns, 33, "%2")
ok(on != off and strip(on) == strip(off) and render.render(towns, 33, "%2", flash=()) == off and [common.cw(l) for l in strip(on).split("\n")] == [common.cw(l) for l in strip(off).split("\n")],
   "Flash changes only the frame color: same text, same widths; no flash is the same output as before")
fl_sel = render.card(dict(fe, status="done"), 33, True, False, True)
fl_not = render.card(dict(fe, status="done"), 33, False, False, True)
ok(fl_sel != render.card(dict(fe, status="done"), 33, True) and fl_not != render.card(dict(fe, status="done"), 33, False),
   "Flash lights the frame of a selected card and of an unselected card")
for sq_art in (False, True):
    sq_on = render.render(towns, 33, "%2", flash={"%1"}, art=sq_art, focus="squad", squad=1)
    sq_off = render.render(towns, 33, "%2", art=sq_art, focus="squad", squad=1)
    sq_diff = [i for i, (x, y) in enumerate(zip(sq_on.split("\n"), sq_off.split("\n"))) if x != y]
    ok(sq_diff and strip(sq_on) == strip(sq_off) and [common.cw(l) for l in strip(sq_on).split("\n")] == [common.cw(l) for l in strip(sq_off).split("\n")]
       and render.render(towns, 33, "%2", flash={"%99"}, art=sq_art, focus="squad", squad=1) == sq_off,
       f"Flash pulses the name row of the squad whose member is flashing, also when another squad is viewed (art={sq_art}): same text and widths")
lw = lambda rows: [common.cw(strip(r)) for r in rows]
tl = [dict(fe, hp_delta=40, sp_delta=-12), dict(fe, hp_delta=-12), dict(fe, summons=[1, 2], hp_delta=40, sp_delta=-12)]
ok(all("+40%" in strip(render.stat_rows(a, 29)[0]) for a in tl[:1] + tl[2:]) and "-12" in strip(render.stat_rows(tl[0], 29)[1])
   and "-12%" not in strip(render.stat_rows(tl[0], 29)[1])
   and all(lw(render.stat_rows(a, wd)) == lw(render.stat_rows(fe, wd)) for a in tl for wd in range(10, 40)),
   "Change labels: +N% on the HP row (HP shows tokens, the label is percentage points), -N on the SP row, and every row keeps its width from 10 to 39 cells")
ok(all(lw(render.card(a, 33, False)) == lw(render.card(fe, 33, False)) for a in tl)
   and all(lw(render.card(a, 33, False, True)) == lw(render.card(fe, 33, False, True)) for a in tl),
   "Change labels: a card with labels is as wide on every line as one without, with or without art")
ok(common.fg("green") in render.stat_rows(dict(fe, hp_delta=40), 29)[0] and common.fg("red") in render.stat_rows(dict(fe, hp_delta=-40), 29)[0]
   and common.fg("red") not in render.stat_rows(dict(fe, hp_delta=40, hp=88), 29)[0],
   "Change labels: an increase is green, a decrease is red")
ok(strip(render.stat_rows(dict(fe, hp_delta=40), 12)[0]) == strip(render.stat_rows(fe, 12)[0]),
   "Change labels: where the row has no room the label is left out")
op = dict(fe, model="Opus 5.5", hp=66, hp_left=131353, hp_max=200000)
ok("+58%" in strip(render.card(dict(op, hp_delta=58), 33, False, True)[2]) and "Opus" not in strip(render.card(dict(op, hp_delta=58), 33, False, True)[2])
   and "Opus" in strip(render.card(op, 33, False, True)[2]),
   "Change labels: on a 33-column art card the label takes the model badge's place while it is shown")
pid = art.portrait_id(fe)
ok(f"\x1b[38;2;{pid >> 16 & 255};{pid >> 8 & 255};{pid & 255}m" in render.render(towns, 33, "%1", art=True)
   and pid == art.PORTRAIT_ID + fe["cls"], "Portrait chosen by class")
ok(all(len({a["cls"] for a in t["agents"]}) == len(t["agents"]) for t in towns)
   and len(set(common.spread([f"sess-{i}" for i in range(6)], 8).values())) == 6, "Classes: unique within a squad (6 agents -> 6 classes)")
pi = ui.parse_input
ok(pi("\x1b[<0;5;7M\x1b[<0;5;7m") == [("click", 6)], "Left mouse press -> click row 7 (release ignored)")
ok(pi("\x1b[<35;5;3M") == [("hover", 2)], "Mouse move -> hover row 3")
ok(pi("\x1b[<64;1;1M\x1b[<65;1;1M") == [("key", "k"), ("key", "j")], "Wheel -> k / j")
ok(pi("\x1b[A\x1b[B") == [("key", "k"), ("key", "j")], "Arrow keys -> k / j")
ok(pi("\x1b") == [("key", "\x1b")] and pi("jv") == [("key", "j"), ("key", "v")], "Lone Esc and plain keys")
ok(pi("\x1b[5~\x1b[6~j") == [("key", "PgUp"), ("key", "PgDn"), ("key", "j")], "PgUp / PgDn -> own keys, no stray ~")
ok(ui.handle_key("PgUp", {"focus": "party", "sel": "%1", "squad": None, "peek": False}, towns) is None,
   "Sidebar ignores PgUp")
ok([ui.report_scroll(k, 5, 20, 10) for k in ["k", "j", "PgUp", "PgDn", "g", "G", "b", " ", "x"]] == [4, 6, 0, 14, 0, 20, 5, 5, 5],
   "Report scroll keys -> offset: k / j one row, PgUp / PgDn a page (height - 1), g / G top / bottom; other keys keep it")
sel_ros, sel_towns = [("Studio", done, False)], [{"name": "Studio", "agents": [done]}]
other_ = dict(done, cls=(done["cls"] + 1) % 4)
sel_art = {art.portrait_id(done): (png("G"), 6, 3), art.portrait_id(other_): (png("H"), 6, 3)}
plan_a = ui.select_image_plan([done, other_], sel_art)
ok(plan_a == [(art.portrait_id(done), 6, 3), (art.portrait_id(other_), 6, 3)] and ui.select_image_plan([done], None) == [],
   "select images: the plan holds the small portrait of each card on screen with its cells; no art -> empty")
ok(ui.select_images_due(plan_a, {i: (c, r) for i, c, r in plan_a}) == [] and ui.select_images_due(plan_a, {plan_a[0][0]: (7, 3)})[0] == plan_a[0]
   and ui.select_images_due(plan_a, {}) == plan_a,
   "select images: same id at the same cells is not sent again, other cells are, an id never sent is")
real_card, ncard, once_ok = render.card, [0], True
def counted_card(*a, **k):
    ncard[0] += 1
    return real_card(*a, **k)
render.card = counted_card
for w_, h_, art_ in [(120, 40, False), (120, 40, True), (80, 12, False), (80, 10, False), (60, 40, False), (120, 8, False), (36, 40, False)]:
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
        once_ok = (once_ok and frame_calls == built and built == (0 if view_[0] else sum(not c for _, _, c in srs)) and rows_ == again
                   and all(a_["name"] in text_ for a_ in shown_) and len(shown_) <= built)
        ncard[0] = 0
        render.render_select(srs, sst, cur_, w_ - 1, h_, srep, 4000.0, None, art_)
        once_ok = once_ok and ncard[0] == built
render.card = real_card
ok(once_ok, "select screen builds each card once a frame: card() runs once per card item for the layout and the draw together, and the output is the same with or without the shared view")
same_ = {i: (c, r) for i, c, r in plan_a}
out_new = ui.select_images_out(plan_a, sel_art, {}, set())
ok(ui.select_images_out(plan_a, sel_art, same_, set()) == "" and out_new.index(f"a=d,d=I,i={plan_a[0][0]}") < out_new.index(f"a=T,U=1,f=100,i={plan_a[0][0]},c=6,r=3")
   and "a=d" not in ui.select_images_out(plan_a, sel_art, {**same_, plan_a[0][0]: (7, 3)}, set())
   and "a=d" not in ui.select_images_out(plan_a, sel_art, {}, {i for i, _, _ in plan_a}),
   "select images: a repaint sends nothing, an id never sent is deleted first unless the sidebars share it, a resized one is resent without a delete")
sel_banner = (60, 7, 4)
ok(ui.select_title_plan(sel_art, sel_banner, True) == [(art.select_banner_id(4), 60, 7)] and ui.select_title_plan(None, sel_banner, True) == []
   and ui.select_title_plan(sel_art, sel_banner, False) == [] and ui.select_title_plan(sel_art, (88, 10, 6), True)[0][0] == art.select_banner_id(6),
   "select images: the plan holds the banner id of its k:1 shape with its cells; none without art or when the title block is not drawn")
sel_title = [art.image_row(art.select_banner_id(4), r, 60) for r in range(7)]
sel_rows = render.render_select(sel_ros, sel_towns, done["pane"], 80, 24, None, None, sel_title)
ok(sel_rows[:7] == [t + " " * 20 for t in sel_title] and len(sel_rows) == 24 and render.select_layout(24, 7)[3] == render.select_layout(24, 1)[3] - 6
   and not any(art.image_row(art.select_banner_id(4), 0, 60) in r for r in render.render_select(sel_ros, sel_towns, done["pane"], 80, 8, None, None, sel_title)),
   "select screen with art: the banner rows open the screen, the list is shorter by the extra title rows, a short window draws no banner")
sb_wide, sb_short, sb_narrow, sb_huge = ui.select_banner(150, 40, 0.5), ui.select_banner(150, 16, 0.5), ui.select_banner(60, 40, 0.5), ui.select_banner(300, 60, 0.5)
ok(sb_wide and sb_wide[0] <= 150 and sb_wide[1] <= 10 and abs(sb_wide[3] - (150 - sb_wide[0] - sb_wide[3])) <= 1
   and sb_short is None and sb_narrow and sb_narrow[0] <= 60
   and sb_huge and sb_huge[0] <= len(art.DIAC) and abs(sb_huge[3] - (300 - sb_huge[0] - sb_huge[3])) <= 1,
   "select banner: as wide as the screen and centered; none when the roster would get under 8 rows; capped at the placeholder diacritics")
sb_scan = [(w, h, r) for w in range(40, 301, 20) for h in range(8, 61) for r in (0.4, 0.5, 0.6) if ui.select_banner(w, h, r)]
ok(ui.select_banner(100, 12, 0.5) is None and sb_scan
   and all(render.select_layout(h, ui.select_banner(w, h, r)[1])[2] and render.select_layout(h, ui.select_banner(w, h, r)[1])[3] >= 8 for w, h, r in sb_scan),
   "select banner: only returned when the title block fits it and the roster keeps 8 rows")
sb_title = [" " * sb_huge[3] + art.image_row(art.select_banner_id(sb_huge[2]), r, sb_huge[0]) for r in range(sb_huge[1])]
sb_rows = render.render_select(sel_ros, sel_towns, done["pane"], 300, 60, None, None, sb_title)
ok(ui.select_title_plan(sel_art, sb_short, True) == [] and ui.select_title_plan(sel_art, sb_wide, True)[0][0] == art.select_banner_id(sb_wide[2])
   and len(sb_rows) == 60 and all(render.cw(strip(r)) == 300 for r in sb_rows),
   "select banner: no banner image in the plan when there is no banner; with one the screen keeps height rows of width cells")
ok(ui.banner_cells(120, 0.5) == (84, 6, 7) and ui.banner_cells(80, 0.5) == (48, 6, 4),
   "report banner sizes are unchanged by the select banner")
ok(PH not in "".join(srows_of(180, 47, "%2")) and PH in "".join(srows_of(180, 47, "%2", srep, True)),
   "select screen without art: no image placeholders, the cards are the text version")
ok(all(len(o_) == hh and all(common.cw(strip(r)) == 80 for r in o_) and (("j/k" in strip(o_[-1])) == (hh >= 2))
       for hh in range(1, 41) for o_ in [srows_of(80, hh, "%9")]),
   "select screen: every height from 1 to 40 gives exactly that many rows, the hint last from 2 rows up")
ok(len(render.report_side_rows(done, "Studio", rep, 2, 3, (24, 14), rows_total=30)) == 30 and "n/N" in strip(render.report_side_rows(done, "Studio", rep, 2, 3, (24, 14), rows_total=30)[-2]),
   "report_side_rows: the report hints are on the last row inside the frame and rows_total rows are kept")
ok(ui.report_scroll("j", 20, 20, 10) == 20 and ui.report_scroll("k", 0, 20, 10) == 0 and ui.report_scroll("PgDn", 15, 20, 10) == 20
   and all(ui.report_scroll(k, 0, 0, 10) == 0 for k in ["j", "k", "PgUp", "PgDn", "g", "G"]),
   "Report offset stays inside 0..limit; a report that fits never moves")
ok([ui.report_step("N", 0, 3), ui.report_step("N", 1, 3), ui.report_step("n", 2, 3), ui.report_step("N", 0, 1), ui.report_step("x", 1, 3)] == [2, 0, 0, 0, 1],
   "Report N goes to the previous report and wraps from the first to the last; n unchanged; a single report stays")
rh = [re.sub(r"\x1b\[[0-9;]*m", "", r) for r in render.report_side_rows(done, "Studio", rep, 2, 3, (24, 14), rows_total=30)]
ok(any("n/N" in r and "? keys" in r for r in rh), "Report left column hint row (24 columns) shows n/N and ? keys")
lt = {"ask": "請幫我把這個很長的需求完整地實作並且測試一下然後回報給我 " * 3, "files": [f"/w/party_hud/f{n}.py" for n in range(8)], "cmds": 14, "agents": 2, "dir": "/w/party_hud/some/dir", "branch": "feature/x", "cwd": "/w"}
lrep = dict(rep, text="\n".join(f"L{n}" for n in range(60)), task=lt)
lparts = {h: render.report_parts(done, "Studio", lrep, [], 100, 2, 3, art=True, banner=(68, 8), portrait=(24, 14), height=h, now=860 + 3725, fixed=True) for h in (24, 40)}
ok(all(len(lparts[h][0]) == h and "? keys" in strip(lparts[h][0][-2]) and strip(lparts[h][0][-1]).startswith("┗")
       and all(common.cw(strip(r)) == render.SPLIT_SIDE_COLS for r in lparts[h][0])
       and len(render.report_view(*lparts[h], h, 0)[0]) == h
       and "? keys" in strip(render.report_view(*lparts[h], h, 0)[0][h - 2])
       for h in (24, 40)),
   "Report split page, left column taller than the pane (24 and 40 rows): the frame is exactly height rows, every row 30 wide, the hint stays on its last content row")
ok(all(strip(lparts[h][0][-3]).strip("┃ ") == "…" for h in (24, 40))
   and not any(strip(r).strip("┃ ") == "…" for r in render.report_parts(done, "Studio", lrep, [], 100, 2, 3, art=True, banner=(68, 8), portrait=(24, 14), height=60, now=860 + 3725, fixed=True)[0]),
   "Report left column: a cut shows a dim … row above the hint (the column does not scroll, so no arrow), and a column that fits has none")
fit_args = (done, "Studio", dict(rep, task={"ask": "q", "files": [], "cmds": 0, "agents": 0, "dir": None, "branch": None}), 1, 1, (24, 14))
ok(render.report_side_rows(*fit_args, rows_total=30, now=860 + 3725, labels=True, fit=True) == render.report_side_rows(*fit_args, rows_total=30, now=860 + 3725, labels=True),
   "Report left column that fits rows_total is byte-identical with and without fit")
pref = art.image_row(art.big_portrait_id(done), 0, 1).split(chr(0x10EEEE))[0]
for h in (8, 12, 17, 24):
    lp = render.report_parts(done, "Studio", lrep, [], 100, 2, 3, art=True, banner=(68, 8), portrait=(24, 14), height=h, now=860 + 3725, fixed=True)[0]
    nport = sum(pref in r for r in lp)
    ok(nport in (0, 14) and len(lp) == h and "? keys" in strip(lp[-2]), f"Report left column at height {h}: the portrait image is kept whole or dropped whole, never split ({nport} rows)")
need = {
    "report": "n N j k ↑ ↓ wheel PgUp PgDn g G ⏎ q Esc ?",
    "sidebar": "j k J K 1-9 n v r ⏎ q Esc P ?",
}
ok(all(set(need[m].split()) <= {t for k, _ in render.HELP[m] for t in k.replace(" / ", " ").split()} for m in need),
   "Key help lists every key of its mode")
ok(all(len(rows) == h and all(common.cw(r) == w for r in rows) for m in need for w in (28, 33, 80) for h in (3, 12, 30)
       for rows in [[strip(r) for r in render.help_screen(m, w, h)]]),
   "Key help: exactly height rows, every row exactly width cells (CJK-safe), also in a short pane")
hb = [strip(r) for r in render.help_screen("report", 80, 30)]
hk = max(common.cw(k) for k, _ in render.HELP["report"]) + 1
hw = 5 + hk + max(common.cw(t) for _, t in render.HELP["report"])
hn = len(render.HELP["report"]) + 2
ok(hb[(30 - 1 - hn) // 2].startswith(" " * ((80 - hw) // 2) + "╭") and not any("╭" in r for r in hb[:(30 - 1 - hn) // 2])
   and hb[(30 - 1 - hn) // 2].rstrip().endswith("╮") and common.cw(hb[(30 - 1 - hn) // 2].rstrip()) == (80 - hw) // 2 + hw,
   "Key help box is centred in the pane: top row and left margin follow (height - 1 - box) // 2 and (width - box) // 2, box width wraps the content")
ph = art.image_row(art.BANNER_ID, 0, 60)
FAINT = "\x1b[2m"
pg = [ph + "  \x1b[1;31mred\x1b[0m text", "\x1b[32m" + "你好" * 40 + "\x1b[0m", "short"] + ["\x1b[34mrow\x1b[0m " + "x" * 70] * 27
ov = render.help_overlay(pg, "report", 80, 30)
ovt = [strip(r) for r in ov]
ot, ol = (30 - 1 - hn) // 2, (80 - hw) // 2
box_rows = [strip(r) for r in render.help_box("report", 80, 30)[0]]
ok(len(ov) == 30 and all(common.cw(r) == 80 for r in ovt[ot : ot + hn])
   and [r[ol : ol + hw] for r in ovt[ot : ot + hn]] == box_rows and ovt[ot].startswith("row ") and ovt[ot][ol - 1] == "x",
   "Key help overlay: height rows, rows with the box exactly width, box centred, page text kept on both sides")
ok(ov[1] == render.dim_row(pg[1]) and ov[1].startswith(FAINT) and ov[1].endswith("\x1b[0m")
   and all(r.startswith(FAINT) and FAINT in r[len(FAINT) :] for r in (ov[ot - 1], ov[ot + hn])),
   "Key help overlay: page rows outside the box are in faint text (SGR 2 again after every SGR)")
ok(strip(render.cols_of("a你b", 2, 4)) == " b" and strip(render.cols_of("a你b", 0, 2)) == "a " and strip(render.cols_of("ab", 0, 5)) == "ab   ",
   "Key help overlay: a wide character cut in half becomes a space, a short row is padded")
ok(all(common.cw(strip(r)) == w for w in (79, 80) for r in render.help_overlay(["你" * 40] * 30, "report", w, 30)[ot : ot + hn]),
   "Key help overlay: wide characters under the box edge keep every row at the width (odd and even)")
left_part, right_part = render.cols_of(ph, 0, ol), render.cols_of(ph, ol + hw, 80)
ok(left_part.count("\U0010eeee") == ol and right_part.count("\U0010eeee") == 60 - ol - hw and "\x1b[38;2;" in right_part
   and strip(left_part) + strip(render.cols_of(ph, ol, ol + hw)) + strip(right_part) == strip(render.cols_of(ph, 0, 80)),
   "Key help overlay: placeholder cells left and right of the box keep their color and marks")
ok(all(t.startswith("next") for k, t in render.HELP["sidebar"] if k in ("j k", "J K")),
   "Key help: j / J are listed as next and k / K as prev, the way handle_key moves")
ok(all("? keys" in strip(render.hint_line(m, w)) for m, w in (("sidebar", 28), ("report", 24)))
   and "q close" in strip(render.hint_line("report", 60)) and "? keys" in strip(render.render(towns, 28, "%1", None, "sidebar")).splitlines()[-1],
   "Key hints keep ? keys at the narrowest widths (sidebar 28, report left column 24)")
ok([ui.help_toggle(k, s) for k, s in [("?", False), ("j", False), ("?", True), ("\x1b", True), ("q", True), ("n", True), ("\r", True)]]
   == [(True, True), (False, False), (False, True), (False, True), (False, True), (True, True), (True, True)],
   "Key help: ? opens; ?, Esc, q close it and are eaten (q never reaches the report's close); other keys are eaten while it is open")
rl, rr = [f"S{n:02}".ljust(30) for n in range(12)], [f"R{n:02}" for n in range(40)]
v0, o0 = render.report_view(rl, rr, 10, 0)
v7, o7 = render.report_view(rl, rr, 10, 7)
ok(o7 == 7 and [r[:30] for r in v7] == [r[:30] for r in v0] == rl[:10] and [r[32:] for r in v7] == rr[7:17] and [r[32:] for r in v0] == rr[:10],
   "Report view: the left column keeps its first rows, the right column shifts with the offset")
ok(render.report_view(rl, rr, 10, 99) == (render.report_view(rl, rr, 10, 30)[0], 30) and render.report_view(rl, rr, 10, -3)[1] == 0
   and render.report_view(rl, rr[:6], 10, 4)[1] == 0,
   "Report view: the offset is clamped to 0..len(right) - height, and to 0 when the right column fits")
ok(all(common.cw(r) == 30 + 2 + 3 for r in v7) and len(v7) == 10 and len(render.report_view(rl, rr[:4], 20, 0)[0]) == 12,
   "Report view: rows are left + gap + right wide, at most height rows")
np_ = [f"P{n}" for n in range(30)]
nv, no = render.report_view([], np_, 8, 5)
ok(nv == np_[5:13] and no == 5, "Report view, narrow page: no left column, the whole page scrolls")
fl, fr = render.report_parts(done, "Studio", dict(rep, text="\n".join(f"L{n}" for n in range(60))), [], 150, art=True, banner=(88, 10), portrait=(24, 14), height=40, fixed=True)
ok(len(fl) == 40 and strip(fl[-1]).startswith("┗") and len(fr) > 40,
   "Report page, fixed left column: the frame closes on the pane's last row however long the text is")
fe = next(a for a in agents if a["pane"] == "%1")
ok(common.class_icon(fe) in render.render(towns, 33) and collect.collect(sys.argv[2])["towns"][0]["agents"][1]["cls"] == fe["cls"],
   "Class icon fixed by session id (same after re-reading the snapshot)")
def hk(k, sel="%1", focus="party", squad=None, ts=None):
    st = {"focus": focus, "sel": sel, "squad": squad, "peek": False}
    return st, ui.handle_key(k, st, ts or towns)
# After sorting: Studio = [%2 waiting, %1 busy], Server = [%4]
ok(hk("k")[0]["sel"] == "%2" and hk("j", "%2")[0]["sel"] == "%1", "j / k step one member at a time within the squad")
ok(hk("j")[0]["sel"] == "%1" and hk("k", "%2")[0]["sel"] == "%2" and hk("j", "%4")[0]["sel"] == "%4",
   "j / k stop at the squad's first / last member, never cross squads")
ok(hk("J")[0]["sel"] == "%4" and hk("K", "%4")[0]["sel"] == "%2", "J / K jump to the next / previous squad, selecting its first (most urgent) member")
ok(hk("2")[0]["sel"] == "%1" and hk("1")[0]["sel"] == "%2" and hk("3")[0]["sel"] == "%1", "1-9 select the Nth card of this squad; out of range does nothing")
ok(hk("n")[0]["sel"] == "%2" and hk("n", "%2")[0]["sel"] == "%2", "n jumps to the next waiting / done (stays put when it's the only one)")
ok(hk("v")[0]["peek"] is True, "v toggles peek")
ok(hk("\r")[1] == "jump" and hk("\r", focus="squad", squad=1)[1] == "jump_squad", "Enter goes to the member; on a squad, goes to that session")
st, _ = hk("J", "%4", ts=empty)
ok(st["focus"] == "squad" and st["squad"] == 2, "J onto a squad without members: cursor rests on the squad")
ok(all(hk(k, "%4", focus="squad", squad=2, ts=empty)[0]["focus"] == "squad" for k in "jk"),
   "On an empty squad j / k do nothing (J / K switch squads)")
calls, real_tmux = [], sidebars.tmux
def fake_tmux(*a):
    calls.append(a)
    if a[0] == "show-option":
        return "34"
    return "%9 1 22\n%8 1 34\n" if a[0] == "list-panes" else ""
sidebars.tmux = fake_tmux
sidebars.remember_width()
sidebars.tmux = real_tmux
ok(("set-option", "-g", "@party_sidebar_width", "30") in calls and ("resize-pane", "-t", "%9", "-x", "30") in calls
   and ("resize-pane", "-t", "%8", "-x", "30") in calls, "Sidebar dragged below 30: remembered as 30, the dragged one bounces back to 30")
def nudge_tmux(*a):
    calls.append(a)
    return {"display-message": "@5\n", "show-option": "46", "list-panes": "%7 1 36\n%8 0 175\n"}.get(a[0], "")
sidebars.tmux = nudge_tmux
calls.clear()
sidebars.nudge()
sidebars.tmux = real_tmux
ok(("resize-pane", "-t", "%7", "-x", "46") in calls and not any(c[:3] == ("resize-pane", "-t", "%8") for c in calls),
   "Window switch: that window's sidebar at the wrong width (36) is reset to the configured 46, other panes untouched")
def restore_tmux(restoring, sidebar_on=""):
    sep = collect.FIELD_SEP
    places = {"a:1.1": sep.join(["a:1.1", "%1", ""]), "a:2.1": sep.join(["a:2.1", "%5", ""]), "a:3.1": sep.join(["a:3.1", "%6", "1"]),
              "@1": "a\t" + restoring, "@2": "a\t" + restoring}
    def fake(*a):
        calls.append(a)
        if a[0] == "show-option":
            return restoring if a[2] == "@party_restoring" else sidebar_on
        if a[0] == "display-message":
            return places.get(a[3], sep.join(["a:2.0", "%7", ""])) + "\n"  # a missing place: tmux answers for the active pane
        return {"list-windows": "@1\n@2\n", "list-panes": "%1\n%2\n" if "-a" in a else "1\n", "split-window": "%9\n"}.get(a[0], "")
    return fake
calls.clear()
sidebars.tmux = restore_tmux("")
sidebars.restore_begin()
ok(calls[-1] == ("set-option", "-g", "@party_restoring", "%1 %2"), "--restore-begin: remembers the panes that exist now")
calls.clear()
sidebars.tmux = restore_tmux("%1 %2")
rc = sidebars.restore_end(["a:1.1", "a:2.1", "a:3.1", "gone:1.1", ""])[0]
respawned = [c[3] for c in calls if c[0] == "respawn-pane"]
ok(rc == 0 and respawned == ["%5"] and calls[calls.index(("respawn-pane", "-k", "-t", "%5", sidebars.EXE + " --sidebar")) - 1][-6:] == (";", "select-pane", "-t", "%5", "-T", "party-hud"),
   "--restore-end: only a pane made during the restore becomes a sidebar (titled party-hud); one from before, an existing sidebar and a missing place are left alone")
unset = calls.index(("set-option", "-gu", "@party_restoring"))
ok(unset > calls.index(("respawn-pane", "-k", "-t", "%5", sidebars.EXE + " --sidebar")) and any(c[:4] == ("set-option", "-g", "@party_sidebar_on", "1") for c in calls[unset:]),
   "--restore-end: --ensure is released after the panes are taken over, then the hooks go in")
calls.clear()
sidebars.ensure("@1")
ok(not any(c[0] == "split-window" for c in calls), "--ensure during a restore: adds no sidebar")
calls.clear()
sidebars.tmux = restore_tmux("")
ok(sidebars.restore_end(["a:2.1"])[0] == 2 and [c[0] for c in calls] == ["show-option"], "--restore-end without --restore-begin: exit 2, no pane is touched")
sidebars.tmux = real_tmux
pt = {"focus": "party", "sel": "%1", "squad": None, "peek": False}
ui.point_at(("squad", 0), pt, towns)
ok(pt["sel"] == "%1", "Mouse over the current squad's row: selected member unchanged")
ui.point_at(("squad", 1), pt, towns)
ok(pt["focus"] == "party" and pt["sel"] == "%4", "Mouse over another squad -> select its first member")
ui.point_at(("agent", "%2"), pt, towns)
ok(pt["focus"] == "party" and pt["sel"] == "%2", "Mouse over a card -> select that member")
ok(ui.next_waiting(agents, "%1") == "%2" and ui.next_waiting(agents, "%2") == "%2"
   and ui.next_waiting([a for a in agents if a["status"] != "waiting"], "%1") is None,
   "\"Next waiting\" for prefix a: searches forward, returns self if alone, None if none")
common.CURSOR = os.path.join(sys.argv[3], "fixture.cursor")
a = {"focus": "squad", "sel": "%4", "squad": 1, "peek": True}
b = {"focus": "party", "sel": "%1", "squad": None, "peek": False}
common.save_cursor(a); common.load_cursor(b)
ok(b == {"focus": "squad", "sel": "%4", "squad": 1, "peek": False}, "Shared cursor: one sidebar writes, another reads the same cursor (peek not shared)")
ok(hk("q")[1] == "hide" and hk("\x1b")[1] == "back" and hk("P")[1] == "back", "Sidebar: q hides, Esc and P return to the previous pane")
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
