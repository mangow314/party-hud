#!/usr/bin/env bash
# party.py unit tests (no tmux needed):
# fixture rendering (card widths, status, HP bars, non-agent panes hidden) + key / mouse / cursor logic
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

fail=0
check() { # check <description> <command...>: passes when the command exits 0
  local desc=$1
  shift
  if "$@"; then echo "ok   $desc"; else echo "FAIL $desc"; fail=1; fi
}
across() { # file $2 matches regex $1, which may span lines (BSD grep -z does not let . match newlines)
  python3 -c 'import re, sys; sys.exit(not re.search(sys.argv[1], open(sys.argv[2], encoding="utf-8").read(), re.S))' "$1" "$2"
}

cat >"$tmp/fixture.json" <<'EOF'
{
  "panes": [
    {"session_name":"Studio","window_index":"1","window_name":"Frontend","window_active":"1","session_attached":"1",
     "pane_id":"%1","pane_active":"1","pane_current_command":"claude","pane_current_path":"/r/studio","@workmux_pane_status":"🤖"},
    {"session_name":"Studio","window_index":"2","window_name":"Review","window_active":"0","session_attached":"1",
     "pane_id":"%2","pane_active":"1","pane_current_command":"claude","pane_current_path":"/r/studio/src","@workmux_pane_status":"💬"},
    {"session_name":"Studio","window_index":"3","window_name":"nvim","window_active":"0","session_attached":"1",
     "pane_id":"%3","pane_active":"1","pane_current_command":"nvim","pane_current_path":"/r/lib","@workmux_pane_status":""},
    {"session_name":"Studio","window_index":"3","window_name":"nvim","window_active":"0","session_attached":"1",
     "pane_id":"%9","pane_active":"0","pane_current_command":"python3","pane_current_path":"/r/side","@workmux_pane_status":"",
     "@party_sidebar":"1"},
    {"session_name":"Server","window_index":"1","window_name":"一個很長很長的中文視窗名稱","window_active":"1","session_attached":"0",
     "pane_id":"%4","pane_active":"1","pane_current_command":"claude","pane_current_path":"/r/server","@workmux_pane_status":""}
  ],
  "now": 10000,
  "sessions": {"%1":{"sid":"s1","name":"","status":"busy"},"%2":{"sid":"s2","name":"審查員","status":"idle"},
               "%4":{"sid":"s4","name":"","status":"idle"}},
  "transcripts": {"s2":"/t/2","s4":"/t/4"},
  "party": {"%1":{"session_id":"s1","ctx_left":88,"ctx_size":200000,"transcript":"/t/1","model":"Opus 5.5"},"%2":{"session_id":"old","ctx_left":32,"transcript":"/t/old"}},
  "cache": {"/t/1":[8920,3600,24000],"/t/2":[9000,300,60000],"/t/4":[5000,300,150000]},
  "summons": {"/t/1":[{"type":"executor","desc":"Execute ticket 001"}]}
}
EOF

# Width 33 = drawable width of the default 34-column sidebar / 36-column popup after borders
python3 "$party" --fixture "$tmp/fixture.json" --width 33 >"$tmp/out.ansi"
sed $'s/\x1b\\[[0-9;?]*[a-zA-Z]//g' "$tmp/out.ansi" >"$tmp/out.txt"

# Every box line (starting with a frame char) must be exactly 33 columns wide (CJK counts as 2)
widths_ok() {
  python3 - "$1" <<'EOF'
import sys, unicodedata
lines = [l for l in open(sys.argv[1]).read().splitlines() if l[:1] in ("╭", "│", "╰", "╔", "║", "╚")]
width = lambda l: sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in l)
bad = [l for l in lines if width(l) != 33]
print("\n".join(bad), file=sys.stderr)
sys.exit(1 if bad or not lines else 0)
EOF
}
check "Every box line is 33 columns wide" widths_ok "$tmp/out.txt"
check "Layout: Squads 2, then cards of the viewed squad right below (Studio: 2 agents -> 2 cards, nvim excluded)" \
  across "╭─ Squads 2 .*[╭╔][─═] claude [─═].*[╭╔][─═] claude [─═]" "$tmp/out.txt"
lacks() { ! grep -q -- "$1" "$2"; } # file $2 does not contain $1
check "Cards don't list other squads' members" lacks "z zzz" "$tmp/out.txt"
check "Viewed squad (Studio): gold ▌ bar in the left column" grep -qE "^│▌ .* Studio" "$tmp/out.txt"
check "Studio summary: waiting !1, busy ⠋1; own squad gets the location pin after its name" grep -qE "Studio 󰍎 +!1 ⠋1 +│" "$tmp/out.txt"
check "Server: only an asleep member -> summary zzz 1 (expired cache still visible)" grep -qE "Server +zzz 1 │" "$tmp/out.txt"
next_line_has() { grep -A1 -- "$1" "$tmp/out.txt" | sed -n 2p | grep -q -- "$2"; } # the line after $1 contains $2
check "Waiting member sorts before busy (Frontend)" across "審查員.*! wait.*Frontend.*⠋ busy" "$tmp/out.txt"
check "Text card (no art): class icon, name, class, ... workmux 🤖 -> spinner + busy, on one line" \
  grep -qE "Frontend (Warrior|Merchant|Thief|Cleric|Scholar|Hunter|Apothecary|Dancer) +⠋ busy ║" "$tmp/out.txt"
check "Selected card: gold double frame, ❯ at the far left of the first row" across "38;2;226;178;74m╔═[^╝]*❯[^╝]*Frontend" "$tmp/out.ansi"
check "Squad with someone waiting: name in orange (selected or not)" grep -qE "1;38;2;240;160;80mStudio" "$tmp/out.ansi"
check "Unselected card: dim thin frame (a waiting card keeps its orange frame), dimmed name" \
  across "38;2;240;160;80m╭─[^╯]*38;2;138;143;168m審查員" "$tmp/out.ansi"
check "HP: 14-column value area = heart icon + label + right-aligned value (176k left / 200k max)" grep -qE "║ .HP  176k/200k " "$tmp/out.txt"
check "SP: minutes left / 60m, on the line right after HP" next_line_has "HP  *176k/200k" "SP  *42/60m "
check "HP row right side: chip icon + space + model base name (no version or effort)" grep -qE "HP +176k/200k +. Opus ║" "$tmp/out.txt"
check "SP row right side: number of summoned subagents (no longer listed one per line)" grep -qE "SP +42/60m +.1 ║" "$tmp/out.txt"
check "No subagent detail lines in the card" lacks "executor" "$tmp/out.txt"
check "Name from the Claude session name; stale pane cache with another session is dropped, HP estimated from transcript (140k)" \
  across "審查員.*! wait.*HP +140k/200k" "$tmp/out.txt"
check "HP threshold color: 88% teal (bar = colored underline)" grep -qE "4m.\[58;2;126;214;168m" "$tmp/out.ansi"

# Selecting a member of another squad: the viewed squad and the cards follow
python3 -c 'import os,sys
sys.path.insert(0, os.path.dirname(sys.argv[1])); from party_hud import art, collect, common, render, sidebars, ui
print(render.render(collect.collect(sys.argv[2])["towns"], 33, "%4"))' "$party" "$tmp/fixture.json" >"$tmp/sel.ansi"
sed $'s/\x1b\\[[0-9;?]*[a-zA-Z]//g' "$tmp/sel.ansi" >"$tmp/sel.txt"
bar_only_server() { grep -qE "^│▌ .* Server" "$1" && ! grep -qE "^│▌ .* Studio" "$1"; }
check "Select %4 -> Server has the gold bar, Studio doesn't" bar_only_server "$tmp/sel.txt"
check "Select %4 -> only Server's 1 card" test "$(grep -cE '^[╭╔][─═] claude [─═]' "$tmp/sel.txt")" = 1
check "Select %4 -> Studio members not listed" lacks "審查員" "$tmp/sel.txt"
check "Idle with expired cache -> z asleep; no statusline cache -> HP 50k estimated from transcript, SP 0" \
  across "一個很.*z zzz.*HP +50k/200k +║.*SP +0/60m +║" "$tmp/sel.txt"
check "HP threshold color: 25% yellow, value turns yellow too" across "58;2;226;178;74m.*1;38;2;226;178;74m5" "$tmp/sel.ansi"
check "Viewed squad with nothing to flag: gold name; unviewed squad with someone waiting: orange ! on the left" \
  across "38;2;240;160;80m!.*Studio.*38;2;226;178;74mServer" "$tmp/sel.ansi"
check "Select %4 -> every box line is 33 wide" widths_ok "$tmp/sel.txt"
python3 -c 'import os,sys
sys.path.insert(0, os.path.dirname(sys.argv[1])); from party_hud import art, collect, common, render, sidebars, ui
t=collect.collect(sys.argv[2])["towns"]; e=t+[dict(t[1],name="Empty",agents=[])]
print(render.render(e,33,"%1",focus="squad",squad=2))' "$party" "$tmp/fixture.json" \
  | sed $'s/\x1b\\[[0-9;?]*[a-zA-Z]//g' >"$tmp/squad.txt"
check "Empty squad selected -> every box line is 33 wide" widths_ok "$tmp/squad.txt"

# Popup / sidebar: sidebar pane not a squad member, peek, key hints, row highlight, key handling
ui_ok() {
  python3 - "$party" "$tmp/fixture.json" <<'EOF'
import os, re, sys
sys.path.insert(0, os.path.dirname(sys.argv[1])); from party_hud import art, collect, common, render, sidebars, ui
snap = collect.collect(sys.argv[2]); towns = snap["towns"]
agents = [a for t in towns for a in t["agents"]]
strip = lambda x: re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", x)
fails = []
def ok(cond, msg):
    if not cond: fails.append(msg)
ok(snap["panes"]["%9"]["window_panes"] == 0 and "%9" not in [a["pane"] for a in agents], "Sidebar pane is not a squad member")
peek = strip(render.render(towns, 33, "%1", ["line1", "", "最後一行", "", ""], "popup"))
ok("Peek · Frontend" in peek and "最後一行" in peek and "│ HP" not in peek, "v peek: pane output replaces the status box")
hint = strip(render.render(towns, 34, "%1", None, "popup")).splitlines()[-1]
ok("jk/JK nav" in hint and "q quit" in hint and not re.search(r"[一-鿿]", hint), "Popup key hints are in English")
ok("q hide" in strip(render.render(towns, 34, "%1", None, "sidebar")).splitlines()[-1], "Sidebar key hints are in English")
ok(any(common.bg("view") in l and "Server" in l for l in render.render(towns, 33, "%1", focus="squad", squad=1).splitlines()), "Selected squad row gets the warm-gold background")
tall = strip(render.render(towns, 33, "%1", [f"L{i}" for i in range(100)], "popup", 40)).splitlines()
ok(len(tall) == 40 and any("L99" in l for l in tall) and sum(l.startswith("│L") for l in tall) > 12, "v peek fills the remaining height")
ok(len(tall) == 40 and "q quit" in tall[-1], "v peek: key hints stay on the last line; q still fits at width 33")
low = strip(render.render(towns, 33, "%1", None, "sidebar", 40)).splitlines()
ok(len(low) == 40 and "q hide" in low[-1], "Key hints pinned to the last line (blank gap when content is short)")
empty = towns + [dict(towns[1], name="Empty", agents=[])]
eq = strip(render.render(empty, 33, "%1", focus="squad", squad=2))
ok(re.search(r"Empty +\(empty\) │", eq) and "no agents ⏎ open session" in eq and "╭─ claude" not in eq,
   "Squad without agents: row says (empty), plus one info card: no agents, Enter opens the session")
rm3 = []
st3 = strip(render.render(towns, 33, "%1", row_map=rm3)).splitlines()
ok(all(rm3[i] == ("agent", "%2") for i, l in enumerate(st3) if "Thief" in l or "140k" in l), "Clicking a row of a member's status box selects that member")

done = dict(agents[0], status="done", hp_left=410000, hp_max=1000000)
rep = {"text": "## 結果\n完成了報告畫面\n" + "很長的一行中文" * 20, "start": 100, "end": 860}
frame = render.render_report(done, "Studio", rep, [], 60)
rf = strip(frame).splitlines()
ok("Quest complete" in rf[0] and f"{done['name']}  claude · Studio" in rf[1] and "q close" in rf[-1] and "scroll" not in rf[-1],
   "report: title, who and which squad, key hints on the last line (j / k are gone: copy-mode scrolls)")
ok("took 12m 40s" in rf[2] and "HP 410k/1M" in rf[2], "report: time from prompt to answer, HP left")
ok(all(common.cw(l) <= 60 for l in rf) and sum(common.cw(l) == 60 for l in rf) >= 1,
   "report: no row is wider than the width, CJK wraps by display width")
ok(common.fg("gold", True) + "結果" in frame and "## " not in strip(frame), "report: the text goes through render_markdown (heading in gold, marker dropped)")
long = dict(rep, text="\n".join(f"L{n}" for n in range(50)))
lf = strip(render.render_report(done, "Studio", long, [], 60)).splitlines()
ok(all(f"L{n}" in lf for n in range(50)), "report: a report taller than any pane is printed in full, every line (no paging)")
ar = render.render_report(done, "Studio", rep, [], 60, art=True).splitlines()
pid = art.portrait_id(done)
ok(all(ar[r].startswith(art.image_row(pid, r, art.PORTRAIT_CELLS[0])) for r in range(3)) and chr(0x10EEEE) not in frame
   and all(common.cw(strip(l)) <= 60 for l in ar),
   "report: with art the portrait stands left of the first three rows; without art there are no placeholders")
last = strip(render.render_report(dict(done, status="waiting"), "Studio", None, ["$ make", "ok", "", ""], 60))
ok("Last output" in last and "$ make" in last and "took" not in last, "report: no report -> the pane's last lines")
ok("no report yet" in strip(render.render_report(done, "Studio", None, [], 60)), "report: nothing at all -> says so")
sub = {"type": "executor", "desc": "Execute ticket 001", "text": "## 子結果\nsubagent said hi"}
busy = dict(done, summons=[{"type": "executor", "desc": "Branch 還在跑" * 8}])
bf = strip(render.render_report(busy, "Studio", dict(rep, subagents=[sub]), [], 60))
ok("Quest complete" not in bf and "還有 1 個分支任務進行中" in bf.splitlines()[0] and "進行中" in bf.split("\n\n", 1)[1]
   and all(common.cw(l) <= 60 for l in bf.splitlines()),
   "report: a branch task still running -> title says so instead of Quest complete, task listed as 進行中, rows fit")
sf = strip(render.render_report(done, "Studio", dict(rep, subagents=[sub]), [], 60))
ok("Quest complete" in sf.splitlines()[0] and sf.index("Execute ticket 001") > sf.index("完成了報告畫面") and "subagent said hi" in sf
   and "## " not in sf and "進行中" not in sf,
   "report: finished subagent listed below the main report with its own report (Markdown), no 進行中")
nr = strip(render.render_no_report(40, 10)).splitlines()
ok(len(nr) == 10 and "Nobody is waiting or done." in nr[1] and all(common.cw(l) == 40 for l in nr[:3]) and "q close" in nr[-1],
   "report popup with nobody waiting or done: says so and waits (a popup that exits at once only flashes)")
ok(render.wrap("一二三四五", 4) == ["一二", "三四", "五"] and render.wrap("a\tb\x1b[31m", 9) == ["a   b[31m"],
   "report: wrap by display width; tabs expanded, control characters dropped")
md = render.render_markdown
B, I, R, fgc = "\033[1m", "\033[3m", common.RESET, common.fg
ok(md("# T\n###### s", 20) == [fgc("gold", True) + "T" + R, fgc("gold", True) + "s" + R], "markdown: # to ###### headings in gold bold, marker dropped")
ok(md("a **b** c", 20) == ["a " + B + "b" + R + " c"], "markdown: **bold**")
ok(md("*x* _y_ snake_case_name", 30) == [I + "x" + R + " " + I + "y" + R + " snake_case_name"], "markdown: *italic* and _italic_, not the underscores inside a word")
ok(md("a `**x**` b", 20) == ["a " + fgc("amber") + "**x**" + R + " b"], "markdown: `inline code` is literal")
ok([strip(r) for r in md("- a\n* b\n1. c", 20)] == ["• a", "• b", "1. c"] and [strip(r) for r in md("- 一二三四五", 6)] == ["• 一二", "  三四", "  五"],
   "markdown: -, * and 1. lists; wrapped items hang under the text")
ok(md("```py\n**x**\n```\nabcdef", 20) == [fgc("green") + "**x**" + R, "abcdef"] and [strip(r) for r in md("```\nabcdef", 4)] == ["abcd", "ef"],
   "markdown: fenced code block is literal, fences dropped, long lines wrap")
ok(md("see [doc](http://u/x) ok", 40) == ["see " + fgc("blue") + "\033[4m" + "doc" + R + fgc("dim") + " (http://u/x)" + R + " ok"], "markdown: [text](url) shows the text and the url")
ok(md("---", 10) == [fgc("dim") + "─" * 10 + R], "markdown: --- is a rule as wide as the pane")
ok([strip(r) for r in md("a\nb\n\nc", 5)] == ["a", "b", "", "c"], "markdown: every source line stays a line, blank lines stay")
ok([strip(r) for r in md("一二三e\u0301f", 5)] == ["一二", "三e\u0301f"] and all(common.cw(strip(r)) <= 5 for r in md("一二三e\u0301f", 5)),
   "markdown: CJK = 2 columns, combining marks = 0")
ok([strip(r) for r in md("1. abcdefgh", 6)] == ["1. abc", "   def", "   gh"], "markdown: 1. lists keep the number and hang wrapped rows under the text")
ok([strip(r) for r in md("e\u0301" * 5, 5)] == ["e\u0301" * 5], "markdown: combining marks take no column, five e+accent fit in width 5")
wr = md("**aaa bbb ccc**", 5)
ok(len(wr) == 3 and all(r.startswith(B) and r.endswith(R) and common.cw(strip(r)) <= 5 for r in wr), "markdown: styled text wraps, every row carries its own style and reset")
raw = ["  - **x**", "  - nested", "| a | b |", "![img](u.png)", "<b>x</b>", "> *q*"]
ok(md("\n".join(raw), 30) == raw, "markdown: nested lists, tables, images, HTML and quotes are shown as written")
mk = lambda pane, status: {"pane": pane, "status": status}
qt = [{"name": "A", "agents": [mk("%1", "done"), mk("%2", "working"), mk("%3", "waiting")]},
      {"name": "B", "agents": [mk("%4", "done")]}]
ok([a["pane"] for _, a in ui.report_queue(qt)] == ["%3", "%1", "%4"], "report queue: waiting first, then done")
ok([a["pane"] for _, a in ui.report_queue(qt, "%2")] == ["%2", "%3", "%1", "%4"] and ui.report_queue(qt, "%2")[0][0] == "A",
   "report queue: the pane asked for comes first, whatever its status")
qs = [{"name": "A", "agents": [dict(mk("%1", "working"), summons=[{}]), mk("%2", "working"), mk("%3", "done"), dict(mk("%4", "working"), summons=[])]},
      {"name": "B", "agents": [mk("%5", "waiting"), dict(mk("%6", "working"), summons=[{}])]}]
ok([a["pane"] for _, a in ui.report_queue(qs)] == ["%5", "%3", "%1", "%6"],
   "report queue: working member with running subagents comes after waiting and done; working without subagents is left out")
ok(ui.handle_key("r", {"focus": "party", "sel": "%1", "squad": None, "peek": False}, towns, "sidebar") == "report"
   and ui.handle_key("r", {"focus": "party", "sel": "%1", "squad": None, "peek": False}, towns, "popup") is None,
   "r in the sidebar opens the report pane (not inside the P popup)")
opened = []
real_open = ui.open_report_pane
ui.open_report_pane = lambda *a: opened.append(a)
os.environ["TMUX_PANE"] = "%5"
ui.open_report("%7")
ui.open_report_pane = real_open
ok(opened == [("%5", "%7")], "r: the report opens beside the sidebar's own window, for the selected member")
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
ok(("set-option", "-p", "-t", "%9", "@party_report", "1", ";", "set-option", "-p", "-t", "%9", "allow-passthrough", "on") in calls,
   "report pane: marked @party_report and allow-passthrough on, this pane only, in one tmux call")
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
sidebars._new_pane = None
killed = []
sidebars.tmux = lambda *a: "%1 @1 s1 r\n%2 @1 s r1\n%3 @2 s1 r\n%4 @2 s r\n" if a[0] == "list-panes" else killed.append(a[2]) or ""
sidebars.tidy()
sidebars.tmux = real_tmux
ok(sorted(killed) == ["%1", "%2"], "Tidy: a report pane counts as a sidebar, so a window with only a sidebar and a report is closed")
import json, tempfile
import fcntl, pty, select as _sel, struct, subprocess, termios as _tm
child = """
import sys
sys.path.insert(0, %r)
from party_hud import collect, ui
ui.get_snapshot = lambda f=None: collect.collect(%r)
ui.report_for = lambda a: {"text": "\\n".join(f"L{n}" for n in range(%d)), "start": 1, "end": 2}
ui.tmux = lambda *a: print("TMUX", a, flush=True) or ""
ui.run_report("%%1")
print("EXITED", flush=True)
"""
def report_session(keys, rows=10, lines=60):
    m, sl = pty.openpty()
    fcntl.ioctl(sl, _tm.TIOCSWINSZ, struct.pack("HHHH", rows, 60, 0, 0))
    env = dict(os.environ, TMUX_PANE="%99")
    p = subprocess.Popen([sys.executable, "-c", child % (os.path.dirname(sys.argv[1]), sys.argv[2], lines)], stdin=sl, stdout=sl, stderr=sl, env=env, close_fds=True)
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
    for n, key in enumerate(keys, 1):
        read_until(b"close", n)
        os.write(m, key)
    read_until(b"EXITED", 1)
    p.wait(timeout=5)
    os.close(m)
    return out.decode(errors="ignore")
once = report_session([b"\r"])
ok(all(f"L{n}" in once for n in range(60)), "report pane: a report taller than the terminal is printed in full, so copy-mode can scroll it")
ok("\x1b[?1049h" not in once and "\x1b[H" not in once and "\x1b[?1003h" not in once, "report pane: normal screen, no cursor homing, no mouse reporting (tmux needs both for copy-mode)")
ok("TMUX ('switch-client', '-t'" in once and "EXITED" in once, "report pane: Enter jumps to the member's pane and exits")
twice = report_session([b"n", b"q"])
ok(twice.count("close") == 2 and twice.index("clear-history', '-t', '%99'") < twice.index("\x1b[2J") < twice.rindex("close"),
   "report pane: n clears this pane's history, then clears the screen and prints the next report")
ok(once.index("TMUX ('copy-mode', '-t', '%99')") < once.index("TMUX ('send-keys', '-t', '%99', '-X', 'history-top')") < once.index("switch-client"),
   "report pane: a report taller than the pane opens in copy-mode at its first line")
ok("copy-mode" not in report_session([b"q"], rows=40, lines=3), "report pane: a report that fits the pane does not enter copy-mode")
ok("EXITED" in twice and "L59" in twice[twice.rindex("\x1b[2J"):], "report pane: q ends the program, which closes the pane")
from datetime import datetime
pane = lambda pid, cmd: {"session_name": "New", "window_index": "1", "window_name": "w", "window_active": "1",
                         "session_attached": "1", "pane_id": pid, "pane_active": "1", "pane_current_command": cmd,
                         "pane_current_path": "/n", "@workmux_pane_status": "", "pane_pid": ""}
with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
    json.dump({"panes": [pane("%20", "claude"), pane("%21", "agy"), pane("%22", "grok"), pane("%23", "codex")], "now": 10000,
               "sessions": {"%20": {"sid": "s20", "name": "新開", "status": "idle"}}, "screen_changed": ["%22"],
               "codex": {"%23": [64000, 256000]}}, f)
new = {a["pane"]: a for t in collect.collect(f.name)["towns"] for a in t["agents"]}
nl = strip(render.render(collect.collect(f.name)["towns"], 33, "%20"))
ok(new["%20"]["hp"] == 100 and new["%20"]["fresh"] and re.search(r"新開.*· idle.*\n.*HP +100% +║\n.*SP +60/60m +║", nl),
   "Freshly started Claude (no request sent yet): HP 100%, SP full at 60")
ok(render.sp_points({"sp": (10.0, 300)}) == 1 and render.sp_points({"sp": (3600.0, 3600)}) == 60 and render.sp_points({"sp": None}) is None,
   "SP = cache minutes left (rounded up, max 60); unknown is --")
with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as g:
    json.dump({"panes": [pane("%30", "claude"), dict(pane("%31", "python3"), **{"@party_report": "1", "window_id": "@7"})], "now": 10000,
               "sessions": {"%30": {"sid": "s30", "name": "x", "status": "idle"}}}, g)
rs = collect.collect(g.name)
ok(rs["panes"]["%31"]["sidebar"] is True and rs["panes"]["%30"]["sidebar"] is False
   and [a["pane"] for t in rs["towns"] for a in t["agents"]] == ["%30"],
   "A report pane (@party_report) is treated like a sidebar: not a member, and it does not keep a window alive")
ok(new["%21"]["hp"] is None and not new["%21"]["fresh"] and re.search(r"agy.*\n.*· idle.*\n.*HP +-- +│\n.*SP +-- +│", nl),
   "Other agents with unreadable context: HP / SP stay --")
ok(new["%22"]["status"] == "working" and new["%21"]["status"] == "idle", "Other agents: recent screen change = busy, no change = idle")
with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
    json.dump({"panes": [pane("%30", "claude"), dict(pane("%31", "claude"), **{"@workmux_pane_status": "✅"}),
                         dict(pane("%32", "claude"), **{"@workmux_pane_status": "🤖"})], "now": 10000,
               "sessions": {"%30": {"sid": "s30", "name": "w", "status": "waiting"},
                            "%31": {"sid": "s31", "name": "d", "status": "waiting"},
                            "%32": {"sid": "s32", "name": "r", "status": "waiting"}}}, f)
wt = {a["pane"]: a for t in collect.collect(f.name)["towns"] for a in t["agents"]}
ok(wt["%30"]["status"] == "waiting" and "!1" in strip(render.squad_summary([wt["%30"]])[0]),
   "Claude Code sessions status waiting (no workmux icon) = waiting member, squad summary shows !1")
ok(wt["%31"]["status"] == "done", "workmux done icon wins over sessions status waiting")
ok(wt["%32"]["status"] == "waiting", "sessions status waiting wins over a stale workmux working icon")
ok(new["%23"]["kind"] == "codex" and new["%23"]["name"] == "codex", "codex pane: kind and name are both codex")
ok(new["%23"]["hp"] == 75 and new["%23"]["hp_left"] == 192000, "codex HP: 64k used of a 256k window -> 75% left (192k)")
with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
    f.write('{"type":"session_meta","payload":{}}\n')
    f.write('{"type":"event_msg","payload":{"type":"token_count","info":null}}\n')
    f.write('{"type":"event_msg","payload":{"type":"token_count","info":{"last_token_usage":{"total_tokens":18981},'
            '"model_context_window":258400}}}\n')
    f.write('{"type":"event_msg","payload":{"type":"token_count","info":null}}\n')
ok(collect.codex_usage(f.name) == (18981, 258400) and collect.codex_usage("/nope") is None,
   "codex rollout: use the last token_count with usage (skip info: null)")
with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
    f.write('{"type":"event_msg","payload":{"type":"task_complete","last_agent_message":"old","started_at":1,"completed_at":2}}\n')
    f.write('{"type":"event_msg","payload":{"type":"task_complete","last_agent_message":"## 結果\\n完成","started_at":100,'
            '"completed_at":160,"duration_ms":60000}}\n')
    f.write('{"type":"event_msg","payload":{"type":"token_count","info":null}}\n')
with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as g:
    g.write('{"type":"event_msg","payload":{"type":"task_complete","last_agent_message":null}}\n')
ok(collect.codex_report(f.name) == {"text": "## 結果\n完成", "start": 100, "end": 160},
   "codex report: last task_complete's message and start / end time")
ok(collect.codex_report(g.name) is None and collect.codex_report("/nope") is None,
   "codex report: no message or no file -> None")

def transcript(*recs):
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    return f.name
def rec(kind, t, content, **extra):
    return {"type": kind, "timestamp": f"2026-11-07T10:{t:02d}:00Z", "message": {"content": content}, **extra}
text = lambda s: {"type": "text", "text": s}
turn = [rec("user", 0, "earlier"), rec("assistant", 1, [text("old answer")]),
        rec("user", 2, "fix it"), rec("assistant", 3, [{"type": "thinking", "thinking": "hm"}]),
        rec("assistant", 3, [text("I'll look first")]), rec("assistant", 4, [{"type": "tool_use", "id": "x"}]),
        rec("user", 5, [{"type": "tool_result", "tool_use_id": "x"}]),
        rec("assistant", 6, [text("## 結果\nDone")]), rec("assistant", 7, [text("One more line")]),
        rec("assistant", 8, [text("subagent noise")], isSidechain=True), rec("user", 9, "caveat", isMeta=True)]
t0 = datetime.fromisoformat("2026-11-07T10:00:00+00:00").timestamp()
r = collect.claude_report(transcript(*turn))
ok(r == {"text": "## 結果\nDone\n\nOne more line", "start": t0 + 120, "end": t0 + 420},
   "claude report: text after the last tool call, from the prompt's time to the last text (subagent and meta skipped)")
r = collect.claude_report(transcript(*turn, rec("user", 10, "<bash-input>ls</bash-input>"), rec("user", 10, "<bash-stdout>a</bash-stdout>")))
ok(r is not None and r["text"].startswith("## 結果") and r["start"] == t0 + 120,
   "claude report: a ! command after the answer (no reply) does not hide the report")
ok(collect.claude_report(transcript(*turn[:6])) is None and collect.claude_report(transcript(*turn[:7])) is None
   and collect.claude_report("/nope") is None,
   "claude report: turn still in a tool call, or no file -> None")
ok(collect.claude_report(transcript(*turn[:4])) is None, "claude report: turn with only thinking so far -> None")
ok(collect.claude_report(transcript(*turn[:2])) == {"text": "old answer", "start": t0, "end": t0 + 60},
   "claude report: answer without tool calls")
sess = transcript(*turn)
sdir = os.path.join(sess[:-6], "subagents")
os.makedirs(sdir)
def agent(name, meta, *recs):
    if meta is not None:
        open(os.path.join(sdir, f"agent-{name}.meta.json"), "w").write(meta if isinstance(meta, str) else json.dumps(meta))
    with open(os.path.join(sdir, f"agent-{name}.jsonl"), "w") as g:
        for r in recs:
            g.write(json.dumps(r) + "\n")
agent("a", {"agentType": "executor", "description": "Fin one", "finished": True},
      rec("user", 0, "go", isSidechain=True), rec("assistant", 1, [text("sub final")], isSidechain=True))
agent("b", {"agentType": "executor", "description": "Still running"}, rec("user", 0, "go", isSidechain=True))
agent("c", "not json {", rec("user", 0, "go", isSidechain=True))
agent("e", "[1]", rec("user", 0, "go", isSidechain=True))
agent("d", {"agentType": "executor", "description": "No log text", "finished": True}, rec("user", 0, "go", isSidechain=True))
ok(collect.claude_report(os.path.join(sdir, "agent-a.jsonl")) is None
   and collect.claude_report(os.path.join(sdir, "agent-a.jsonl"), sidechain=True)["text"] == "sub final",
   "subagent report: its log is all sidechain records, read only on request")
fin = collect.finished_subagents(sess)
ok(fin == [{"type": "executor", "desc": "Fin one", "text": "sub final"}, {"type": "executor", "desc": "No log text", "text": ""}],
   "subagents: only finished: true metas, with their final text (unfinished, broken or non-object metas skipped)")
ok(collect.report_for({"kind": "claude", "transcript": sess})["subagents"] == fin
   and collect.report_for({"kind": "claude", "transcript": sess})["text"].startswith("## 結果")
   and collect.report_for({"kind": "claude", "transcript": transcript(*turn)})["subagents"] == [],
   "report_for: main report carries the finished subagents; no subagents/ directory -> empty list, same report")
handback = [rec("user", 0, "go", isSidechain=True), rec("assistant", 1, [text("working")], isSidechain=True),
            rec("assistant", 2, [{"type": "tool_use", "id": "h", "name": "SubagentHandback", "input": {"message": "  ## 報告\nall good \n"}}], isSidechain=True),
            rec("user", 3, [{"type": "tool_result", "tool_use_id": "h", "content": [text('{"success":true}')]}], isSidechain=True)]
agent("h", {"agentType": "general-purpose", "description": "Handback", "finished": True}, *handback)
hb_log = os.path.join(sdir, "agent-h.jsonl")
ok(collect.claude_report(hb_log, sidechain=True) == {"text": "## 報告\nall good", "start": t0, "end": t0 + 120}
   and [s for s in collect.finished_subagents(sess) if s["desc"] == "Handback"][0]["text"] == "## 報告\nall good"
   and collect.claude_report(hb_log) is None
   and collect.claude_report(transcript(*[{**r_, "isSidechain": False} for r_ in handback])) is None,
   "subagent report: SubagentHandback message (stripped), main conversation unaffected")
common_tmux = collect.tmux
agy_screen = "old\n\nI changed 2 files.\nAll tests pass.\n\n\u256d\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256e\n\u2502 > ask   \u2502\n\u2570\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256f\n  ? for shortcuts\n"
grok_screen = "first\n\nDone: \u4fee\u597d\u4e86\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n> \n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n grok-4  ctx 3%\n"
for screen in (agy_screen, grok_screen):
    collect.tmux = lambda *args, s=screen: s
    got = collect.report_for({"kind": "agy" if screen is agy_screen else "grok", "pane": "%3"})
    want = "I changed 2 files. All tests pass." if screen is agy_screen else "Done: \u4fee\u597d\u4e86"
    ok(got and got["text"] == want, f"report_for agy/grok: last paragraph above the input box and status bar ({want[:8]!r})")
agy_real = "\n".join([
    "\u2500" * 49, "> 分三段回答，不要用工具：第一段說明 tmux session", "  persistence 是什麼；第二段列出三個常用指令（用 -", "  開頭的清單）；第三段一句話總結。", "",
    "\u26a0 Sign-in update needed", "  \u23bf  Your sign-in is missing permissions that are", "     now required, so some requests may fail. Run", "     /logout to sign in again.", "",
    "\u25b8 Thought for 10s, 829 tokens", "",
    "  tmux session", "  persistence（工作階段持久化）是指當終端機關閉、", "  SSH 連線中斷或網路異常時，tmux", "  仍能在伺服器背景持續運行所有程式與終端狀態，讓",
    "  使用者隨時能重新連回原先的作業環境；廣義上亦包", "  含透過外掛（如 tmux-", "  resurrect）在伺服器重新開機後復原 session", "  與視窗佈局的機制。", "",
    "  \u2022 tmux new -s <名稱>：建立並進入一個具名的全新", "  session。", "  \u2022 tmux detach：將目前的 session", "  脫離至背景繼續執行（或使用快捷鍵 Ctrl+b 接", "  d）。",
    "  \u2022 tmux attach -t", "  <名稱>：重新附加並回到指定的背景 session", "  繼續作業。", "",
    "  tmux session persistence", "  能徹底避免因斷線導致工作中斷或進度遺失，實現隨", "  時暫停且無縫接續的終端工作流。", "",
    "\u2500" * 52, ">", "\u2500" * 52, "? for shortcuts              Gemini 3.8 Flash · high", ""])
grok_real = "\n".join([
    "  sdlc/quest-report-v2 ~/projects/party-hud [Click here to Upgrade]                 32K / 256K \u2502 [Dashboard]", "", "",
    "     \u276f 分三段回答，不要用工具：第一段說明 tmux session persistence 是什麼；第二段列出三個常用指令（用 - 開頭的清單）；第三段   12:47 AM   \u2588",
    "       一句話總結。          \u2588", "          \u2588",
    "     \u25c6 Thought for 0.8s       \u2588", "          \u2588",
    "     tmux session persistence 是指終端機視窗關掉、SSH 斷線，或你登出之後，tmux 裡的工作階段仍留在背景繼續跑。程序、視窗配置和  12:47 AM   \u2588",
    "     工作目錄都還在，之後重新連上同一台機器就能接回去。        \u2588", "          \u2588",
    "     \u2022 tmux new -s work：建立名為 work 的工作階段       \u2588", "     \u2022 tmux ls：列出目前還在的工作階段       \u2588",
    "     \u2022 tmux attach -t work：接回名為 work 的工作階段       \u2588", "          \u2588",
    "     一句話：tmux 把終端工作留在伺服器上，斷線後還能原樣接回來。       \u2588", "          \u2588",
    "     Worked for 4.9s        \u2588", "          \u2588", "",
    "  Help improve Grok                                    [Opt out] [Opt in]",
    "  Off by default. Opt-in to allow SpaceXAI to retain coding data, e.g., prompts, traces, & metrics, for training and",
    "  debugging purposes. Change anytime via settings.", "  Read Terms and Privacy Policy.", "",
    "  \u256d" + "\u2500" * 40 + "\u256e", "  \u2502 \u276f" + " " * 38 + "\u2502", "  \u2570" + "\u2500" * 20 + " Grok 4.7 (high) \u2500\u256f", "",
    "  Shift+Tab:mode  \u2502  Ctrl+x:shortcuts"])
for kind, screen, want in (
    ("agy", agy_real, "tmux session persistence（工作階段持久化）是指當終端機關閉、SSH 連線中斷或網路異常時，tmux 仍能在伺服器背景持續運行所有程式與終端狀態，讓"
     "使用者隨時能重新連回原先的作業環境；廣義上亦包含透過外掛（如 tmux-resurrect）在伺服器重新開機後復原 session 與視窗佈局的機制。\n\n"
     "\u2022 tmux new -s <名稱>：建立並進入一個具名的全新 session。\n\u2022 tmux detach：將目前的 session 脫離至背景繼續執行（或使用快捷鍵 Ctrl+b 接 d）。\n"
     "\u2022 tmux attach -t <名稱>：重新附加並回到指定的背景 session 繼續作業。\n\n"
     "tmux session persistence 能徹底避免因斷線導致工作中斷或進度遺失，實現隨時暫停且無縫接續的終端工作流。"),
    ("grok", grok_real, "tmux session persistence 是指終端機視窗關掉、SSH 斷線，或你登出之後，tmux 裡的工作階段仍留在背景繼續跑。程序、視窗配置和工作目錄都還在，之後重新連上同一台機器就能接回去。\n\n"
     "\u2022 tmux new -s work：建立名為 work 的工作階段\n\u2022 tmux ls：列出目前還在的工作階段\n\u2022 tmux attach -t work：接回名為 work 的工作階段\n\n"
     "一句話：tmux 把終端工作留在伺服器上，斷線後還能原樣接回來。")):
    collect.tmux = lambda *args, s=screen: s
    got = collect.report_for({"kind": kind, "pane": "%3"})
    ok(got and got["text"] == want, f"screen report: whole last reply, unwrapped ({kind})")
collect.tmux = lambda *args: "> ask\n\nonly line\n"
ok(collect.report_for({"kind": "agy", "pane": "%3"})["text"] == "only line", "screen report: prompt then one output line -> that line")
collect.tmux = lambda *args: "no border\n\nlast words\n"
ok(collect.report_for({"kind": "agy", "pane": "%3"})["text"] == "last words", "screen report: no box on screen -> last paragraph as is")
grok_scrolled = "\n".join([
    "  [Click here to Upgra… 32K / 256K \u2502 [Dashboard]", "", "    tmux 把終端工作留在可隨時接回的", "    背景 session 裡，關掉視窗不會中", "    斷裡面的程式。", "",
    "    Worked for 13s                              \u2588", "                                                \u2588", "",
    " Help improve Grok            [Opt out] [Opt in]", " Off by default. Opt-in to allow SpaceXAI to", " retain coding data, e.g., prompts, traces, &",
    " metrics, for training and debugging purposes.", " Change anytime via settings.", " Read Terms and Privacy Policy.",
    " \u256d" + "\u2500" * 45 + "\u256e", " \u2502 \u276f" + " " * 42 + "\u2502", " \u2570" + "\u2500" * 27 + " Grok 4.7 (high) \u2500\u256f", " Ctrl+x:shortcuts"])
collect.tmux = lambda *args: grok_scrolled
ok(collect.report_for({"kind": "grok", "pane": "%3"})["text"] == "tmux 把終端工作留在可隨時接回的背景 session 裡，關掉視窗不會中斷裡面的程式。",
   "screen report: grok scrolled past the prompt -> paragraph above Worked for")
cap_args = []
collect.tmux = lambda *args: cap_args.append(args) or "x\n"
collect.report_for({"kind": "agy", "pane": "%3"})
ok(cap_args and "-S" in cap_args[0] and "-J" in cap_args[0], "screen report: reads scrollback")
agy_thought = "\n".join(["> 問題", "", "▸ Thought for 6s", "  第一段的", "  文字。", "", "  第二段。", "", "─" * 20, ">", "─" * 20])
collect.tmux = lambda *args: agy_thought
ok(collect.report_for({"kind": "agy", "pane": "%3"})["text"] == "第一段的文字。\n\n第二段。",
   "screen report: thought line glued to the first paragraph keeps that paragraph")
collect.tmux = lambda *args: "ready\nhello\n\nparty-test-reply-42\n"
ok(collect.report_for({"kind": "agy", "pane": "%3"})["text"] == "party-test-reply-42", "screen report: fake agy screen (no prompt line, echo, blank, reply) -> the reply")
collect.tmux = lambda *args: "\n\n"
ok(collect.report_for({"kind": "grok", "pane": "%3"}) is None, "screen report: blank screen -> None")
collect.tmux = common_tmux
collect.PARTY_DIR = tempfile.mkdtemp()
screens = iter(["a", "a", "b", "b"])
collect.tmux = lambda *args: next(screens)
first, same = collect.screen_changed(["%9"], 100), collect.screen_changed(["%9"], 110)
moved, later = collect.screen_changed(["%9"], 120), collect.screen_changed(["%9"], 130)
ok(first == {"%9": False} and same == {"%9": False} and moved == {"%9": True} and later == {"%9": False},
   "Screen diff: first read and no change don't count, a change = busy, back to idle after 4+ s still")
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
for i, n in enumerate(art.PORTRAIT_FILES + art.CREST_FILES):
    open(os.path.join(art.ART_DIR, ("portrait-" if i < 8 else "crest-") + n + ".png"), "wb").write(b"PNG" + bytes([i]))
imgs = art.load_art()
ok(imgs and len(imgs) == 16 and imgs[art.PORTRAIT_ID + 2] == (b"PNG\x02", 6, 3) and imgs[art.CREST_ID + 7] == (b"PNG\x0f", 4, 2),
   "All 16 images present: portraits 6x3 cells, crests 4x2 cells")
ok(art.art_supported("", "xterm-ghostty") and art.art_supported("", "xterm-kitty") and not art.art_supported("", "xterm-256color")
   and not art.art_supported("", "wezterm") and art.art_supported("on", "xterm-256color") and not art.art_supported("off", "xterm-ghostty"),
   "Images: auto on for Ghostty / Kitty, text elsewhere; @party_art on / off forces it")
os.remove(os.path.join(art.ART_DIR, "crest-moon.png"))
ok(art.load_art() is None, "One image missing -> whole UI falls back to text")
ok(common.cw(strip(art.image_row(art.PORTRAIT_ID, 2, 6))) == 6 and art.image_row(art.PORTRAIT_ID, 2, 6).count("\U0010EEEE") == 6,
   "Placeholder row is 6 cells: diacritics (row, column) take no width")
row = art.image_row(0x7A0103, 1, 2)
ok(row.startswith("\x1b[38;2;122;1;3m") and "\U0010EEEE̍̅\U0010EEEE̍̍" in row,
   "Placeholders: foreground = image id, row-2 diacritic 030D, column diacritics 0305 / 030D")
os.environ["TMUX"] = "x"
seq = art.kitty_image(7, b"x" * 5000, 6, 3)
ok(seq.startswith("\x1bPtmux;\x1b\x1b_Ga=T,U=1,f=100,i=7,c=6,r=3,q=2,m=1;") and seq.count("\x1bPtmux;") == 2
   and seq.endswith("m=0;" + __import__("base64").b64encode(b"x" * 5000).decode()[4096:] + "\x1b\x1b\\\x1b\\"),
   "Image upload: base64 in 4096-char chunks, wrapped in tmux passthrough, last chunk m=0")
aw = strip(render.render(towns, 33, "%1", row_map=(arm := []), art=True)).splitlines()
w = lambda l: sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in l)
ok(all(w(l) == 33 for l in aw if l[:1] in "╭│╰"), "Art: every box line is 33 wide")
ok(re.search(r"Studio +!1 ⠋1 │\n│▌\U0010EEEE.{8}\U0010EEEE.{2} 2 members · 1 waiting +\U000F034E │", "\n".join(aw))
   and re.search(r"Server +zzz 1 │\n│ \U0010EEEE.{8}\U0010EEEE.{2} 1 member · 1 asleep +│", "\n".join(aw)),
   "Art: two rows per squad (crest + name + summary; row 2 N members, plus · N waiting or · N asleep)")
ok(strip(render.squad_summary([{"status": s} for s in ("sleep", "idle", "idle", "done")])[0]) == "✓1 ·2 zzz 1",
   "Squad summary counts idle members (·N) between done and asleep")
hr = render.render(towns, 33, "%4", art=True, here="Studio").splitlines()
tinted = [strip(l) for l in hr if common.bg("view") in l]
ok(len(tinted) == 2 and "Server" in tinted[0] and "member" in tinted[1] and all(t.startswith("│▌") for t in tinted)
   and any("Studio" in strip(l) for l in hr) and sum(render.PIN_ICON in strip(l) for l in hr) == 1
   and render.PIN_ICON in strip(hr[hr.index(next(l for l in hr if "Studio" in strip(l))) + 1]),
   "Viewed squad (select %4 -> Server): both rows warm-gold + gold bar; own squad Studio only gets the pin")
ok(sum(1 for t in arm if t == ("squad", 0)) == 2 and sum(1 for t in arm if t == ("squad", 1)) == 2,
   "Art: both squad rows map to that squad (mouse)")
fr = next(i for i, l in enumerate(aw) if "Frontend" in l)
ok(aw[fr].startswith("║❯") and re.search(f"{common.class_icon(next(a for a in agents if a['pane'] == '%1'))} Frontend +⠋ busy ║", aw[fr])
   and re.search(f"\U0010EEEE.{{2}} {render.HP_ICON}HP  176k/200k +{render.MODEL_ICON} Opus ║", aw[fr + 1])
   and re.search(f"SP +42/60m +{common.SUMMON_ICON}1 ║", aw[fr + 2])
   and aw[fr + 3].startswith("╚") and aw[fr - 1].startswith("╔═ claude"),
   "Art: card = 3-row portrait (class icon + name + status, HP + model, SP + subagent count), no detail lines")
ok(render.model_badge({"model": "Opus 5.5"}, 7) == render.MODEL_ICON + " Opus" and render.model_badge({"model": "Sonnet 5.5"}, 7) == "Sonnet"
   and render.model_badge({}, 7) == "", "Model: chip icon + space + base name; name only if it doesn't fit (icon would overlap); blank without data")
nar = {"hp": 100, "hp_left": 1_000_000, "hp_max": 1_000_000, "model": "Opus 5.5", "sp": None}
n31, n30 = (re.sub(r"\033\[[0-9;:]*m", "", render.stat_rows(nar, w)[0]) for w in (20, 19))
nar2 = dict(nar, hp_left=890_000, hp_max=1_200_000)
n30b = re.sub(r"\033\[[0-9;:]*m", "", render.stat_rows(nar2, 19)[0])
ok(n31.endswith(f"HP     1M/1M {render.MODEL_ICON} Opus") and n30.endswith(f"HP    1M/1M {render.MODEL_ICON} Opus") and common.cw(n30) == 19
   and n30b.endswith(f"HP     890k {render.MODEL_ICON} Opus"),
   "Narrow sidebar: value area yields to the model icon; 1.0M as 1M; shrink the bar first, drop the max (/1.2M) only if still too wide")
text = render.render(towns, 33, "%1", hints="sidebar") + render.render(towns, 33, "%1", art=True) + render.render(towns, 33, "%1", ["x"], "popup")
for nm in [t["name"] for t in towns] + [a["name"] for a in agents] + [s["desc"] for a in agents for s in a.get("summons", [])]:
    text = text.replace(nm, "")
ok(not re.search(r"[一-鿿＀-￯]", text), "UI text is all English (only session / member names may be CJK)")
def mu(raw, focus, state):
    ts = [{"agents": [{"pane": "%50", "status": raw, "focus": focus}]}]
    new_state = collect.mark_unseen(ts, state)
    return ts[0]["agents"][0]["status"], new_state
s0 = {"%50": {"status": "working", "unseen": False}}
st1, s1 = mu("idle", False, s0)
st2, s2 = mu("idle", False, s1)
st3, s3 = mu("idle", True, s2)
st4, _ = mu("idle", False, s3)
ok(st1 == st2 == "done" and st3 == "idle" and st4 == "idle", "Unseen done: busy -> idle while not watched becomes done and stays; back to idle once seen")
ok(mu("idle", True, s0)[0] == "idle" and mu("sleep", False, s1)[0] == "done" and mu("working", False, s1)[0] == "working",
   "Watched pane finishing goes straight to idle; asleep keeps done; busy again clears done")
ok(mu("idle", False, {})[0] == "idle", "Idle member that was never busy is not marked done")
low = {"hp": 8, "hp_left": 16000, "hp_max": 200000, "sp": None, "fresh": False}
red, dim = "\x1b[1;38;2;208;96;90m", "\x1b[1;38;2;138;143;168m"
render._tick = 0; on = render.stat_rows(low, 22)[0]
render._tick = 1; off = render.stat_rows(low, 22)[0]
render._tick = 0
mid = render.stat_rows(dict(low, hp=30, hp_left=60000), 22)[0]
ok(red in on and red not in off and dim in off and "\x1b[1;38;2;226;178;74m" in mid and red not in mid,
   "HP <= 10%: value and bar blink red / dim every second; 30% is yellow, no blink")
w22 = lambda s: len(strip(s)) == 22
ok(all(w22(r) for a in (low, {"hp": None, "sp": None}, {"hp": 100, "sp": None, "fresh": True}) for r in render.stat_rows(a, 22)),
   "HP / SP rows are exact width (with max, unknown, percent only)")
mr = render.meter_row("HP", "hp", "124k", "fg", "/200k", 50, "hp", 22)
ok(strip(mr) == "HP" + " " * 11 + "124k/200k" and mr.count(render.ul("hp")) == 11 and mr.count(render.ul("line")) == 11,
   "Value row: label left, value right; full-row underline, first 50% in bar color, rest dim")
ok(render.meter_row("SP", "sp", "--", "fg", "", None, "dim", 22).count(render.ul("line")) == 22, "Unknown value: whole underline is dim")
import tempfile as _tf, time as _t
from datetime import datetime as _dt, timezone as _tz
root = _tf.mkdtemp(); now_ = _t.time(); day = os.path.join(root, f"{_dt.now():%Y/%m/%d}"); os.makedirs(day)
def roll(name, cwd, age, ts=None):
    p = os.path.join(day, f"rollout-{name}.jsonl")
    meta = {"cwd": cwd, **({"timestamp": _dt.fromtimestamp(ts, _tz.utc).isoformat().replace("+00:00", "Z") if isinstance(ts, float) else ts} if ts is not None else {})}
    open(p, "w").write(json.dumps({"type": "session_meta", "payload": meta}) + "\n")
    os.utime(p, (now_ - age, now_ - age))
    return p
roll("old", "/w/a", 600); new_a = roll("new", "/w/a", 5); roll("other", "/w/b", 1)
ok(collect.newest_rollout("/w/a", now_ - 60, root) == new_a and collect.newest_rollout("/w/a", now_ - 3, root) is None
   and collect.newest_rollout("/w/c", now_ - 60, root) is None,
   "codex rollout: newest file written after codex started, same cwd; older files and other dirs don't count")
roll("bad-ts", "/w/e", 5, "not a time"); num_ts = roll("num-ts", "/w/e", 4, 12345); no_ts = roll("no-ts", "/w/e", 3)
first = collect.newest_rollout("/w/e", now_ - 60, root)
os.utime(no_ts, (now_ - 30, now_ - 30))
ok(first == no_ts and collect.newest_rollout("/w/e", now_ - 60, root) == num_ts
   and collect.paired_rollout("/w/e", now_ - 60, [now_ - 50], root) is None,
   "codex rollout: a broken or missing session_meta.timestamp still counts for the newest rollout, only pairing skips it")
ra = roll("pair-a", "/w/p", 20, now_ - 50.0); rb = roll("pair-b", "/w/p", 5, now_ - 40.0)
ok(collect.paired_rollout("/w/p", now_ - 110, [now_ - 60], root) == ra and collect.paired_rollout("/w/p", now_ - 60, [now_ - 110], root) == rb
   and collect.paired_rollout("/w/p", now_ - 110, [now_ - 60, now_ - 10], root) == ra
   and collect.paired_rollout("/w/p", now_ - 10, [now_ - 110, now_ - 60], root) is None,
   "codex rollout: same-cwd codex processes take rollouts one to one by start time; none is reused")
procs = {"10": ["codex"], "20": ["codex"]}; starts = {"10": now_ - 110, "20": now_ - 60}
real = (collect.proc_args, collect.proc_children, collect.proc_start, collect.rollouts_since, collect.glob.glob)
collect.proc_args, collect.proc_children = (lambda pid: procs.get(str(pid))), (lambda pid: [])
collect.proc_start, collect.rollouts_since = (lambda pid: starts.get(str(pid))), (lambda c, s, r=None: real[3](c, s, root))
collect.glob.glob = lambda pat, _g=real[4]: [] if pat.startswith("/proc/") else _g(pat)
both = [{"pane_pid": "10", "pane_current_path": "/w/p"}, {"pane_pid": "20", "pane_current_path": "/w/p"}]
got = [collect.codex_rollout(pp, "/w/p", both) for pp in ("10", "20")]
solo = collect.codex_rollout("10", "/w/p", both[:1])
ok(got == [ra, rb] and solo == rb, "codex_rollout: two same-cwd panes get their own rollouts; a lone codex still gets the newest")
cprocs = {"30": ["bash", "/tmp/codex-notes.sh"], "31": ["vim", "codex.md"], "32": ["/x/bin/codex"], "33": ["node", "/x/bin/codex.js"]}
procs.update(cprocs)
ok([bool(collect.is_codex_proc(cprocs[k])) for k in ("30", "31", "32", "33")] == [False, False, True, True]
   and collect.find_codex("30") is None and collect.find_codex("33") == "33",
   "codex process: matched by program name, not by an argument containing codex")
fields = {f: "" for f in collect.TMUX_FIELDS}
tpanes = [dict(fields, pane_id=f"%{i}", pane_pid=pp, pane_current_path="/w/p", pane_current_command="codex",
               session_name="s", session_attached="1", window_active="1", window_id="@1", window_panes="2")
          for i, pp in ((1, "10"), (2, "20"))]
real2 = (collect.read_tmux, collect.read_claude_sessions, collect.codex_rollout, collect.screen_changed)
seen = []
collect.read_tmux, collect.read_claude_sessions = (lambda: tpanes), (lambda: {})
collect.screen_changed = lambda ps, now: {}
collect.codex_rollout = lambda *a: seen.append(real2[2](*a)) or seen[-1]
collect.collect()
from_collect, seen[:] = list(seen), []
for i in (1, 2):
    collect.report_for({"kind": "codex", "pane": f"%{i}"})
collect.read_tmux, collect.read_claude_sessions, collect.codex_rollout, collect.screen_changed = real2
collect.proc_args, collect.proc_children, collect.proc_start, collect.rollouts_since, collect.glob.glob = real
ok(from_collect == [ra, rb] and seen == [ra, rb], "codex rollout: the collect path and the report path pair the same rollouts")
kids = {"50": ["51"], "51": ["52"]}
cpanes = [dict(fields, pane_id="%7", pane_pid="50", pane_current_command="sleep", session_name="s",
               session_attached="1", window_active="1", window_id="@1", window_panes="1")]
real3 = (collect.read_tmux, collect.read_claude_sessions, collect.proc_children, collect.screen_changed)
collect.read_tmux, collect.proc_children = (lambda: cpanes), (lambda pid: kids.get(str(pid), []))
collect.screen_changed = lambda ps, now: {}
kinds = []
for spid in ("52", "99"):
    collect.read_claude_sessions = lambda spid=spid: {"%7": {"pid": spid, "sid": "", "name": "", "status": "idle"}}
    kinds.append([a["kind"] for t in collect.collect()["towns"] for a in t["agents"]])
collect.read_tmux, collect.read_claude_sessions, collect.proc_children, collect.screen_changed = real3
ok(kinds == [["claude"], []], "claude session: only a pane whose process tree holds its pid")
nw = [{"pane": p, "status": s} for p, s in (("%1", "idle"), ("%2", "done"), ("%3", "waiting"), ("%4", "done"))]
ok(ui.next_waiting(nw, "%1") == "%3" and ui.next_waiting(nw, "%3") == "%3"
   and ui.next_waiting([dict(a, status="idle") if a["status"] == "waiting" else a for a in nw], "%2") == "%4",
   "n / prefix a: jump to waiting first, then cycle unseen done")
ag = lambda p, s, w="@1": {"pane": p, "status": s, "window": w}
vis = {"%1": {"visible": False}, "%2": {"visible": False}, "%9": {"visible": True}}
r0, b0 = collect.bell_panes(None, [ag("%1", "waiting")], vis)
r1, b1 = collect.bell_panes({"%1": "working", "%9": "working"}, [ag("%1", "done"), ag("%2", "idle"), ag("%9", "waiting")], vis)
r2, _ = collect.bell_panes(b1, [ag("%1", "done")], vis)
ok(r0 == [] and r1 == ["%1"] and r2 == [],
   "Bell: silent on start; once when a hidden member turns waiting / done; no repeats; members you can see don't ring")
lp = {"%1": {"window": "@1", "sidebar": True}, "%2": {"window": "@1", "sidebar": False},
      "%3": {"window": "@2", "sidebar": True}, "%4": {"window": "@3", "sidebar": False}}
ok(collect.lonely_sidebars(lp) == ["%3"], "Tidy: only a sidebar left alone in its window is closed")
dt = [dict(towns[1], agents=[dict(towns[1]["agents"][0], status="done")])]
dw = strip(render.render(dt, 33, None, art=True))
ok(render.squad_alert(dt[0]["agents"]) == "done" and re.search(r"1 member · 1 done", dw), "Squad with unseen done member: row 2 says · N done")
cr = art.crest_ids(["dotfiles", "homelab", "notes", "projects", "scratch"])
ok(len(set(cr.values())) == 5, "Crests: unique for up to 8 squads (real collisions: notes/projects, dotfiles/scratch)")
ok(len(set(art.crest_ids(f"s{i}" for i in range(8)).values())) == 8 and len(art.crest_ids(f"s{i}" for i in range(9))) == 9,
   "Crests: exactly 8 squads use all 8; repeats start at the 9th")
fe = next(a for a in agents if a["pane"] == "%1")
pid = art.portrait_id(fe)
ok(f"\x1b[38;2;{pid >> 16 & 255};{pid >> 8 & 255};{pid & 255}m" in render.render(towns, 33, "%1", art=True)
   and pid == art.PORTRAIT_ID + fe["cls"], "Portrait chosen by class")
ok(all(len({a["cls"] for a in t["agents"]}) == len(t["agents"]) for t in towns)
   and len(set(common.spread([f"sess-{i}" for i in range(6)], 8).values())) == 6, "Classes: unique within a squad (6 agents -> 6 classes)")
ok("\U0010EEEE" not in render.render(towns, 29, "%1", art=True), "Sidebar too narrow (< 30): falls back to text")
fake = {"7": [["node", "/home/u/.nvm/bin/codex"]], "8": [["node", "server.js"]]}
ak = lambda cmd, pid="": collect.agent_kind(cmd, pid, lambda p: fake.get(p, []))
ok(ak("claude") == "claude" and ak("agy") == "agy" and ak("grok") == "grok" and ak("node", "7") == "codex",
   "Recognizes claude / agy / grok, and codex running under node")
ok(ak("node", "8") is None and ak("bash") is None and ak("tmux") is None, "Plain node, shells, nested tmux are not members")
fake.update({"9": [["codex", "exec", "--json", "hi"]], "10": [["/usr/bin/python3.13", "/opt/agy"]], "11": [["nvim", "codex"]]})
ok(ak("python3", "9") == "codex" and ak("bash", "10") == "agy" and ak("bash", "11") is None,
   "Wrappers: an agent among any pane's child processes counts (xv runs codex under python3); a file named codex does not")
fake["12"] = [["/Library/Frameworks/Python.framework/Versions/3.13/Resources/Python.app/Contents/MacOS/Python", "/tmp/agy"]]
ok(ak("bash", "12") == "agy", "Wrappers: macOS framework Python shows up in ps as .../MacOS/Python and still counts")
# Without /proc (macOS): one `ps` call gives children, command lines and start times
ps_out = ("  100     1 Wed Nov  4 11:46:42 2026 -zsh\n"
          "  200   100 Wed Nov  4 11:50:00 2026 node /opt/homebrew/bin/codex --yolo\n"
          "  300   200 Wed Nov  4 11:50:01 2026 /opt/codex/codex-aarch64\n"
          "garbage line\n")
tbl = collect.parse_ps(ps_out)
import time as _t
ok(set(tbl) == {"100", "200", "300"} and tbl["200"][0] == "100" and tbl["200"][1][:2] == ["node", "/opt/homebrew/bin/codex"]
   and tbl["300"][2] == _t.mktime((2026, 11, 4, 11, 50, 1, 0, 0, -1)),
   "ps parsing: pid, parent, arguments and start time (lstart); bad lines skipped")
saved = collect.HAVE_PROC, list(collect._ps_memo)
collect.HAVE_PROC, collect._ps_memo[:] = False, [_t.time() + 3600, tbl]
ok(collect.agent_kind("node", "100") == "codex" and collect.proc_start("200") == tbl["200"][2] and collect.proc_start("999") is None
   and collect.proc_children("100") == ["200"],
   "Without /proc: codex under node is recognized and its start time read from ps")
collect.HAVE_PROC, collect._ps_memo[:] = saved[0], saved[1]
import os as _os
ok(collect.proc_alive(_os.getpid()) and not collect.proc_alive(2 ** 22 + 12345) and not collect.proc_alive("x"),
   "Process alive check works without /proc (os.kill(pid, 0))")
rm = []
lines = strip(render.render(towns, 33, "%1", row_map=rm)).splitlines()
ok(len(rm) <= len(lines), "Mouse row map is no longer than the screen")
ok(all(rm[i] == ("agent", "%2") for i, l in enumerate(lines) if "審查員" in l) and
   all(rm[i] == ("agent", "%1") for i, l in enumerate(lines) if "Frontend" in l) and
   all(rm[i] == ("squad", 1) for i, l in enumerate(lines) if "Server" in l), "Mouse rows -> member / squad")
many = [dict(towns[0], agents=[dict(agents[0], pane=f"%{i}", summons=[]) for i in range(100, 140)])]
short = strip(render.render(many, 33, "%130", None, "sidebar", 24, rm2 := [])).splitlines()
ok(len(short) <= 24 and len(rm2) <= len(short) and ("agent", "%130") in rm2, "Too many members: output fits the height, selected member stays visible")
up = next((l for l in short if "▲" in l), ""); down = next((l for l in short if "▼" in l), "")
shown = len({p for p in rm2 if p and p[0] == "agent"})
ok(re.fullmatch(r" *▲ \d+ more *", up) and re.fullmatch(r" *▼ \d+ more *", down)
   and int(up.split()[1]) + int(down.split()[1]) + shown == 40, "Cards don't fit: ▲ / ▼ N more above and below, summing to the hidden count")
ok(not any("more" in l for l in lines), "Everything fits: no ▲ / ▼ hints")
sq = strip(render.render(towns, 33, "%1", focus="squad", squad=1)).splitlines()
ok(any(l.startswith("│▌") and "Server" in l for l in sq) and not any(l.startswith("╔") for l in sq),
   "Squad focus (Server): gold bar on the squad row, no card gets the selected gold frame")
pi = ui.parse_input
ok(pi("\x1b[<0;5;7M\x1b[<0;5;7m") == [("click", 6)], "Left mouse press -> click row 7 (release ignored)")
ok(pi("\x1b[<35;5;3M") == [("hover", 2)], "Mouse move -> hover row 3")
ok(pi("\x1b[<64;1;1M\x1b[<65;1;1M") == [("key", "k"), ("key", "j")], "Wheel -> k / j")
ok(pi("\x1b[A\x1b[B") == [("key", "k"), ("key", "j")], "Arrow keys -> k / j")
ok(pi("\x1b") == [("key", "\x1b")] and pi("jv") == [("key", "j"), ("key", "v")], "Lone Esc and plain keys")
fe = next(a for a in agents if a["pane"] == "%1")
ok(common.class_icon(fe) in render.render(towns, 33) and collect.collect(sys.argv[2])["towns"][0]["agents"][1]["cls"] == fe["cls"],
   "Class icon fixed by session id (same after re-reading the snapshot)")
def hk(k, sel="%1", mode="popup", focus="party", squad=None, ts=None):
    st = {"focus": focus, "sel": sel, "squad": squad, "peek": False}
    return st, ui.handle_key(k, st, ts or towns, mode)
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
ok(hk("q")[1] == "close" and hk("P")[1] == "close" and hk("\x1b")[1] == "close", "Popup: q / P / Esc close")
common.CURSOR = sys.argv[2] + ".cursor"
a = {"focus": "squad", "sel": "%4", "squad": 1, "peek": True}
b = {"focus": "party", "sel": "%1", "squad": None, "peek": False}
common.save_cursor(a); common.load_cursor(b)
ok(b == {"focus": "squad", "sel": "%4", "squad": 1, "peek": False}, "Shared cursor: one sidebar writes, another reads the same cursor (peek not shared)")
ok(hk("q", mode="sidebar")[1] == "hide" and hk("\x1b", mode="sidebar")[1] == "back", "Sidebar: q hides, Esc returns to the previous pane")
many = [dict(towns[0], name=f"s{i}") for i in range(12)]
rm = []
tall = render.render(many, 33, "%1", height=24, hints="sidebar", row_map=rm, art=True)
ok(len(tall.split("\n")) == 24 and len(rm) == 23,
   "Squad list taller than the pane: the row map is cut with the frame, the hint row maps to nothing")
import fcntl, threading, time as _time
os.makedirs(collect.PARTY_DIR, exist_ok=True)
for f in ("snapshot.json",):
    if os.path.exists(os.path.join(collect.PARTY_DIR, f)):
        os.remove(os.path.join(collect.PARTY_DIR, f))
lock = os.open(os.path.join(collect.PARTY_DIR, "snapshot.lock"), os.O_CREAT | os.O_RDWR, 0o600)
fcntl.flock(lock, fcntl.LOCK_EX)
real_collect, collected, got = collect.collect, [], []
collect.collect = lambda *a: collected.append(1) or {"t": _time.time(), "towns": [], "panes": {}}
th = threading.Thread(target=lambda: got.append(collect.get_snapshot()))
th.start()
_time.sleep(0.3)
waited = not got
with open(os.path.join(collect.PARTY_DIR, "snapshot.json"), "w") as f:
    json.dump({"v": collect.SNAP_VERSION, "t": _time.time(), "towns": [], "panes": {}, "mark": 1}, f)
fcntl.flock(lock, fcntl.LOCK_UN)
th.join(5)
collect.collect = real_collect
ok(waited and got and got[0].get("mark") == 1 and not collected,
   "No snapshot and the lock is taken: wait for the collector and use its snapshot, do not collect again")
sep = collect.FIELD_SEP
good = sep.join(["a", "1", "w\\037x"] + ["0"] * (len(collect.TMUX_FIELDS) - 3))
rows = collect.parse_panes(good + "\n" + "a\\0371\\037bash\n")
ok(len(rows) == 1 and rows[0]["session_name"] == "a" and rows[0]["window_name"] == "w\\037x",
   "list-panes output: printable field separator; a line with the wrong field count is skipped, not a crash")
print("\n".join(fails), file=sys.stderr)
sys.exit(1 if fails else 0)
EOF
}
check "Popup and sidebar: peek, hint bar, highlight, key handling" ui_ok

# --report-text --wait: exit codes, the wait-for wake-up from the collector, the 2 s re-read, the timeout
report_text_ok() {
  python3 - "$party" "$tmp" <<'EOF'
import os, stat, subprocess, sys, time
sys.path.insert(0, os.path.dirname(sys.argv[1])); from party_hud import collect, common
import party
fails = []
def ok(cond, msg):
    if not cond: fails.append(msg)
calls, snaps = [], []
real_snapshot = collect.get_snapshot
agent = lambda s, summons=(), **kw: {"pane": "%5", "kind": "claude", "status": s, "summons": list(summons), **kw}
snap = lambda s, summons=(), **kw: {"towns": [{"agents": [agent(s, summons, **kw)]}]}
def run(rounds, *a, pane_rc=0, **kw):
    calls.clear()
    seq = list(rounds)
    snaps.clear()
    collect.get_snapshot = lambda: snaps.append(1) or seq.pop(0) if len(seq) > 1 else snaps.append(1) or seq[0]
    collect.tmux_run = lambda args, timeout=None: calls.append((tuple(args), timeout)) or (
        (pane_rc, "%5\n", "can't find pane\n") if args[0] == "display-message" else (None, "", ""))
    collect.report_for = lambda a: {"text": "all done"}
    return collect.report_text(*a, **kw)
waits = lambda: [c for c in calls if c[0][0] == "wait-for"]
ok(run([snap("waiting")], "%5") == (0, "all done\n", ""), "report-text: exit 0 prints the report")
ok(run([snap("working")], "%5")[0] == 0 and not waits(), "report-text without --wait: no waiting even while working")
ok(run([snap("waiting")], "5")[0] == 2 and not calls, "report-text: a name that is not a pane id -> 2, tmux not called")
rc, out, err = run([snap("waiting")], "%5", pane_rc=1)
ok(rc == 2 and out == "" and "can't find pane" in err, "report-text: pane does not exist -> 2 with the tmux error on stderr")
rc, out, err = run([{"towns": []}], "%5")
ok(rc == 4 and out == "" and "%5" in err, "report-text: pane exists but is no known agent -> 4")
gone = [0]
def gone_after_wait(args, timeout=None):
    if args[0] == "display-message":
        gone[0] += 1
        return (0, "%5\n", "") if gone[0] == 1 else (1, "", "can't find pane: %5\n")
    return None, "", ""
snaps2 = [snap("working"), {"towns": []}]
collect.get_snapshot = lambda: snaps2.pop(0)
collect.tmux_run = gone_after_wait
rc, out, err = collect.report_text("%5", True, 30)
ok(rc == 2 and out == "" and "can't find pane" in err, "report-text --wait: the pane disappears while waiting -> 2, not 4")
ok(run([snap("waiting")], "%5", True, float("nan"))[0] == 2 and not calls, "report-text: a non-finite --timeout -> 2")
rc, out, err = run([snap("working"), snap("working"), snap("done")], "%5", True, 30)
ok(rc == 0 and out == "all done\n" and len(snaps) == 3 and [c[0] for c in waits()] == [("wait-for", "party-5")] * 2
   and [c[1] for c in waits()] == [2.0, 2.0],
   "report-text --wait: each 2 s wait-for timeout is followed by another snapshot read, until the member stops working")
t0 = time.monotonic()
rc, out, err = run([snap("working")], "%5", True, 0.3)
ok(rc == 3 and out == "" and time.monotonic() - t0 < 1 and 0 < waits()[-1][1] <= 0.3 and len(snaps) >= 2,
   "report-text --wait --timeout: expires with 3, the last wait-for is capped at the time left")
rc, out, err = run([snap("idle", [{}]), snap("idle", [{}]), snap("idle")], "%5", True, 30)
ok(rc == 0 and len(snaps) == 3 and len(waits()) == 2,
   "report-text --wait: keeps waiting while subagents run (idle with summons), returns once they are gone")
tx = os.path.join(sys.argv[2], "main.jsonl")
sub = os.path.join(sys.argv[2], "main", "subagents"); os.makedirs(sub)
open(os.path.join(sub, "agent-x.meta.json"), "w").write('{"finished": true}')
open(os.path.join(sub, "agent-x.jsonl"), "w").close()
real_cr = collect.claude_report
collect.claude_report = lambda t, sidechain=False: {"text": "mid", "start": None, "end": 100}
os.utime(os.path.join(sub, "agent-x.jsonl"), (200, 200))
run([snap("idle", transcript=tx), snap("idle", transcript=tx)], "%5", True, 0.3)
ok(len(waits()) > 0, "report-text --wait: keeps waiting while subagents run (finished subagent log newer than the main report)")
os.utime(os.path.join(sub, "agent-x.jsonl"), (50, 50))
ok(run([snap("idle", transcript=tx)], "%5", True, 30)[0] == 0 and not waits(),
   "report-text --wait: returns when the finished subagent is older than the main report")
collect.claude_report = real_cr
A = 1000.0
def run_after(t, end, kind="claude"):
    calls.clear()
    collect.get_snapshot = lambda: {"t": t, "towns": [{"agents": [agent("waiting", kind=kind)]}]}
    collect.tmux_run = lambda args, timeout=None: calls.append((tuple(args), timeout)) or (
        (0, "%5\n", "") if args[0] == "display-message" else (None, "", ""))
    collect.report_for = lambda a: {"text": "answer", "end": end} if end is not False else None
    return collect.report_text("%5", True, 0.3, A)
rc, _, _ = run_after(A + 1, A + 5)
ok(rc == 3 and waits(), "report-text --wait --after: waits for a report newer than the ask (snapshot older than EPOCH + 2 s)")
rc, _, _ = run_after(A + 3, A - 5)
ok(rc == 3 and waits(), "report-text --wait --after: waits for a report newer than the ask (report ends before EPOCH)")
rc, _, _ = run_after(A + 3, False)
ok(rc == 3 and waits(), "report-text --wait --after: waits for a report newer than the ask (no report yet)")
ok(run_after(A + 3, A + 2) == (0, "answer\n", "") and not waits(),
   "report-text --wait --after: waits for a report newer than the ask, returns once it ends after EPOCH and the snapshot is fresh")
ok(run_after(A + 3, None, "agy") == (0, "answer\n", "") and not waits(),
   "report-text --wait --after: agy and grok reports carry no time, only the snapshot age counts")
ok(run_after(A + 1, None, "agy")[0] == 3, "report-text --wait --after: agy with a stale snapshot waits")
ok(run([snap("waiting")], "%5", False, 30, after=A)[0] == 2, "report-text --after without --wait -> 2")
ask_calls = []
party.get_snapshot = lambda: snap("waiting")
party.tmux_run = lambda args, timeout=None: ask_calls.append(("tmux", tuple(args))) or (
    (0, "%5\n", "") if args[0] == "display-message" else (0, "", ""))
real_run = party.subprocess.run
party.subprocess.run = lambda cmd, **kw: ask_calls.append((tuple(cmd), kw.get("input"))) or subprocess.CompletedProcess(cmd, 0, "", "")
t0 = time.time()
rc, out, err = party.ask("%5", "hello")
ok(rc == 0 and t0 <= float(out) <= time.time() and err == ""
   and ask_calls[1:] == [(("tmux", "load-buffer", "-b", "party-ask", "-"), "hello"),
                         ("tmux", ("paste-buffer", "-p", "-d", "-b", "party-ask", "-t", "%5")),
                         ("tmux", ("send-keys", "-t", "%5", "Enter"))],
   "ask: one line -> load-buffer from stdin, paste-buffer -p -d, then Enter; stdout is the send time")
ask_calls.clear()
party.ask("%5", "-Rxyz")
ok(ask_calls[1] == (("tmux", "load-buffer", "-b", "party-ask", "-"), "-Rxyz"), "ask: text starting with - goes in on stdin")
ask_calls.clear()
rc, out, err = party.ask("%5", "a\nb")
ok(rc == 0 and ask_calls[1:] == [(("tmux", "load-buffer", "-b", "party-ask", "-"), "a\nb"),
                                  ("tmux", ("paste-buffer", "-p", "-d", "-b", "party-ask", "-t", "%5")),
                                  ("tmux", ("send-keys", "-t", "%5", "Enter"))],
   "ask: several lines -> load-buffer from stdin, paste-buffer -p -d, then Enter")
party.subprocess.run = real_run
ok(party.ask("5", "x")[0] == 2, "ask: a name that is not a pane id -> 2")
party.get_snapshot = lambda: {"towns": []}
ok(party.ask("%5", "x")[0] == 4, "ask: pane exists but is no known agent -> 4")
party.tmux_run = lambda args, timeout=None: (1, "", "can't find pane\n")
ok(party.ask("%5", "x")[0] == 2, "ask: pane does not exist -> 2")
fake = os.path.join(sys.argv[2], "bin"); os.makedirs(fake)
with open(os.path.join(fake, "tmux"), "w") as f:
    f.write(f'#!/bin/sh\necho $$ >"{fake}/pid"\nexec sleep 30\n')
os.chmod(os.path.join(fake, "tmux"), 0o755)
os.environ["PATH"] = fake + os.pathsep + os.environ["PATH"]
t0 = time.monotonic()
rc = common.tmux_run(["wait-for", "x"], timeout=0.3)
pid = int(open(os.path.join(fake, "pid")).read())
try:
    os.kill(pid, 0); alive = True
except ProcessLookupError:
    alive = False
ok(rc == (None, "", "") and time.monotonic() - t0 < 5 and not alive, "tmux_run: the timeout ends the tmux child and returns rc None")
sent = []
collect.tmux = lambda *a: sent.append(a) or ""
def sig(status):
    sp = os.path.join(collect.PARTY_DIR, "snapshot.json")
    if os.path.exists(sp): os.remove(sp)
    collect.collect = lambda *a: {"t": time.time(), "towns": [{"agents": [{"pane": "%5", "status": status, "focus": True}]}],
                                  "panes": {"%5": {"window": "@1", "sidebar": False, "visible": True}}}
    sent.clear()
    real_snapshot()
    return [a for a in sent if a[0] == "wait-for"]
bp = os.path.join(collect.PARTY_DIR, "bells.json")
if os.path.exists(bp): os.remove(bp)
r1, r2, r3 = sig("working"), sig("waiting"), sig("waiting")
ok(r1 == [] and r2 == [("wait-for", "-S", "party-5")] and r3 == [],
   "collector: wait-for -S party-<pane> only when a member's status changed (not on the first round, not when unchanged)")
print("\n".join(fails), file=sys.stderr)
sys.exit(1 if fails else 0)
EOF
}
check "report-text --wait: exit codes, wait-for wake-up, 2 s re-read, timeout" report_text_ok

# --summon: tmux arguments, exit codes, readiness; @party_lead / @xv grouping and card widths
summon_ok() {
  python3 - "$party" "$tmp" <<'EOF2'
import os, re, sys, time
sys.path.insert(0, os.path.dirname(sys.argv[1])); from party_hud import collect, render, sidebars
fails = []
def ok(cond, msg):
    if not cond: fails.append(msg)
calls = []
shows = []
def fake_run(args, timeout=None):
    calls.append(tuple(args))
    if args[0] in ("split-window", "new-window"): return 0, "%9\n", ""
    if args[0] == "display-message": return 0, shows.pop(0) if len(shows) > 1 else shows[0], ""
    return 0, "", ""
sidebars.tmux_run = fake_run
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
ok(calls[0] == ("split-window", "-t", "%1", "-P", "-F", "#{pane_id}", "-c", tmp, "claude"), "summon: default splits the caller's window")
ok(("set-option", "-p", "-t", "%9", "@party_lead", "%1") in calls, "summon: the new pane gets @party_lead = caller pane")
calls.clear(); shows[:] = ready
sidebars.summon("codex", tmp, True, 5)
ok(calls[0] == ("new-window", "-P", "-F", "#{pane_id}", "-c", tmp, "codex"), "summon --window: new-window, --cwd passed to -c")
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
agent = lambda pane, kind="claude", window="@1": {"pane": pane, "kind": kind, "window": window, "status": "idle"}
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
print("\n".join(fails), file=sys.stderr)
sys.exit(1 if fails else 0)
EOF2
}
check "summon: tmux arguments, exit codes, timeout; @party_lead / @xv grouping" summon_ok

# transcript: time of the last usage entry; TTL from the latest usage that wrote cache (1h -> 3600)
cat >"$tmp/t.jsonl" <<'EOF'
{"type":"assistant","timestamp":"2026-11-03T04:00:00.000Z","message":{"usage":{"cache_creation":{"ephemeral_1h_input_tokens":500,"ephemeral_5m_input_tokens":0}}}}
{"type":"user","timestamp":"2026-11-03T04:05:00.000Z","message":{"content":"hi"}}
{"type":"assistant","timestamp":"2026-11-03T04:06:00.000Z","message":{"usage":{"input_tokens":10,"cache_read_input_tokens":40000,"cache_creation_input_tokens":90,"cache_creation":{"ephemeral_1h_input_tokens":0,"ephemeral_5m_input_tokens":0}}}}
{"type":"assistant","isSidechain":true,"timestamp":"2026-11-03T04:07:00.000Z","message":{"usage":{"input_tokens":999999}}}
EOF
ci=$(python3 -c 'import os,sys
sys.path.insert(0, os.path.dirname(sys.argv[1])); from party_hud import art, collect, common, render, sidebars, ui
from datetime import datetime
last, ttl, used = collect.cache_info(sys.argv[2])
print(int(last - datetime.fromisoformat("2026-11-03T04:06:00+00:00").timestamp()), ttl, used)' "$party" "$tmp/t.jsonl")
check "transcript: last usage 04:06, TTL 3600, context 40100 tokens (subagent usage excluded)" test "$ci" = "0 3600 40100"

# a resumed session: 300 KB of attachments after the last usage entry
pad=$(printf 'x%.0s' $(seq 1000))
for _ in $(seq 300); do echo "{\"type\":\"attachment\",\"content\":\"$pad\"}"; done >>"$tmp/t.jsonl"
ci=$(python3 -c 'import os,sys
sys.path.insert(0, os.path.dirname(sys.argv[1])); from party_hud import art, collect, common, render, sidebars, ui
print(collect.cache_info(sys.argv[2])[1:])' "$party" "$tmp/t.jsonl")
check "transcript: last usage found behind 300 KB of attachments, not taken for a new session" test "$ci" = "(3600, 40100)"

# statusline integration: Claude Code statusline JSON -> party-hud/<pane>.json; party.py reads HP max and model
sl="$root/integrations/claude-statusline.sh"
echo '{"session_id":"abc-1","context_window":{"used_percentage":12.4,"context_window_size":1000000},"transcript_path":"/p/abc-1.jsonl","model":{"display_name":"Opus 5.5 (1M context)"}}' |
  XDG_RUNTIME_DIR="$tmp/xdg" TMUX_PANE=%7 "$sl"
got=$(XDG_RUNTIME_DIR="$tmp/xdg" python3 -c 'import os,sys
sys.path.insert(0, os.path.dirname(sys.argv[1])); from party_hud import art, collect, common, render, sidebars, ui
d=collect.read_party("%7"); print(d["session_id"], d["ctx_left"], d["ctx_size"], d["transcript"], d["model"])' "$party")
check "statusline integration: writes session, 88% left, max 1M, transcript, model base name" test "$got" = "abc-1 88 1000000 /p/abc-1.jsonl Opus 5.5"
check "statusline integration: broken JSON or outside tmux -> no error, no output" \
  test -z "$(echo garbage | XDG_RUNTIME_DIR="$tmp/xdg" TMUX_PANE=%9 "$sl"; echo '{}' | TMUX_PANE='' "$sl")"

exit "$fail"
