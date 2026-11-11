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
ok("? keys" in hint and "q close" in hint and not re.search(r"[一-鿿]", hint), "Popup key hints are in English")
ok("q hide" in strip(render.render(towns, 34, "%1", None, "sidebar")).splitlines()[-1], "Sidebar key hints are in English")
ok(any(common.bg("view") in l and "Server" in l for l in render.render(towns, 33, "%1", focus="squad", squad=1).splitlines()), "Selected squad row gets the warm-gold background")
tall = strip(render.render(towns, 33, "%1", [f"L{i}" for i in range(100)], "popup", 40)).splitlines()
ok(len(tall) == 40 and any("L99" in l for l in tall) and sum(l.startswith("│L") for l in tall) > 12, "v peek fills the remaining height")
ok(len(tall) == 40 and "q close" in tall[-1], "v peek: key hints stay on the last line; q still fits at width 33")
low = strip(render.render(towns, 33, "%1", None, "sidebar", 40)).splitlines()
ok(len(low) == 40 and "q hide" in low[-1], "Key hints pinned to the last line (blank gap when content is short)")
empty = towns + [dict(towns[1], name="Empty", agents=[])]
eq = strip(render.render(empty, 33, "%1", focus="squad", squad=2))
ok(re.search(r"Empty +\(empty\) │", eq) and "no agents ⏎ open session" in eq and "╭─ claude" not in eq,
   "Squad without agents: row says (empty), plus one info card: no agents, Enter opens the session")
import unicodedata
wd = lambda l: sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in l)
e3 = towns + [dict(towns[1], name=f"E{k}", agents=[]) for k in range(4)] + [towns[0]]
for art_on in (False, True):
    ec = strip(render.render(e3, 33, "%1", art=art_on)).splitlines()
    ecur = strip(render.render(e3, 33, "%1", focus="squad", squad=3, art=art_on)).splitlines()
    e1 = strip(render.render(e3[:3] + e3[-1:], 33, "%1", art=art_on)).splitlines()
    ev = strip(render.render(e3[2:5] + e3[:1], 33, "%zz", art=art_on))
    ok(sum("+4 empty" in l for l in ec) == 1 and not any("E0" in l or "(empty)" in l for l in ec) and all(wd(l) == 33 for l in ec if l[:1] in "╭│╰")
       and sum("+1 empty" in l for l in ecur) == 0 and sum("+" in l and "empty" in l for l in ecur) == 1 and "+2 empty" in "".join(ecur)
       and "".join(ecur).count("(empty)") == 2 and "E0" in "".join(ecur),
       f"2+ consecutive empty squads collapse into one dim +N empty row; the squad under the cursor stays and splits the run, a lone one stays as a (empty) row (art={art_on})")
    ok("+2 empty" in ev and "+3 empty" not in ev and "E0" in ev and "no agents" in ev,
       f"The viewed squad is not folded even with no cursor on it, so its info card has a visible row (art={art_on})")
    ok("E0" in "".join(e1) and "(empty)" in "".join(e1) and "+1 empty" not in "".join(e1),
       f"A single empty squad is never folded into +1 empty (art={art_on})")
noSP = [re.sub(r"\033\[[0-9;:]*m", "", l) for l in render.card({**agents[0], "sp": None, "fresh": False}, 33, True)]
ok(len(noSP) == 4 and not any("SP" in l for l in noSP) and any("HP" in l for l in noSP) and all(wd(l) == 33 for l in noSP),
   "No SP data: the card has no SP row (one row fewer), lines still exactly 33 wide")
noSPa = [re.sub(r"\033\[[0-9;:]*m", "", l) for l in render.card({**agents[0], "sp": None, "fresh": False}, 33, False, True)]
ok(len(noSPa) == render.PORTRAIT_CELLS[1] + 2 and not any("SP" in l for l in noSPa) and all(wd(l) == 33 for l in noSPa),
   "Art card without SP: blank row pads the text so the card is as tall as the portrait, lines exactly 33 wide")
rm3 = []
st3 = strip(render.render(towns, 33, "%1", row_map=rm3)).splitlines()
ok(all(rm3[i] == ("agent", "%2") for i, l in enumerate(st3) if "Thief" in l or "140k" in l), "Clicking a row of a member's status box selects that member")

done = dict(agents[0], status="done", hp_left=410000, hp_max=1000000)
rep = {"text": "## 結果\n完成了報告畫面\n" + "很長的一行中文" * 20, "start": 100, "end": 860}
frame = render.render_report(done, "Studio", rep, [], 60)
rf = strip(frame).splitlines()
ok("Quest complete" in rf[0] and f"{done['name']}  claude · Studio" in rf[1] and "q close" in rf[-1] and "scroll" not in rf[-1],
   "report: title, who and which squad, key hints on the last line (the report pane scrolls itself)")
ok("took 12m 40s" in rf[2] and "HP 410k/1M" in rf[2], "report: time from prompt to answer, HP left")
ok(all(common.cw(l) <= 60 for l in rf) and sum(common.cw(l) == 60 for l in rf) >= 1,
   "report: no row is wider than the width, CJK wraps by display width")
ok(common.fg("gold", True) + "結果" in frame and "## " not in strip(frame), "report: the text goes through render_markdown (heading in gold, marker dropped)")
long = dict(rep, text="\n".join(f"L{n}" for n in range(50)))
lf = strip(render.render_report(done, "Studio", long, [], 60)).splitlines()
ok(all(f"L{n}" in lf for n in range(50)), "report: a report taller than any pane is printed in full, every line (no paging)")
ar = render.render_report(done, "Studio", rep, [], 60, art=True).splitlines()
pid = art.portrait_id(done)
ok(all(ar[10 + r].startswith(art.image_row(pid, r, art.PORTRAIT_CELLS[0])) for r in range(3)) and chr(0x10EEEE) not in frame
   and all(common.cw(strip(l)) <= 60 for l in ar),
   "report: with art the portrait stands left of the first three rows below the banner; without art there are no placeholders")
bn = art.banner_id("done", True, False)
ok(ar[0] == art.image_row(bn, 0, 60) and ar[9] == art.image_row(bn, 9, 60) and ar[10].startswith(art.image_row(pid, 0, 6))
   and "Quest complete" not in strip("\n".join(ar)) and "Quest complete" in strip(frame)
   and [art.banner_id(s, r, m) - art.BANNER_ID for s, r, m in (("done", True, False), ("waiting", True, False), ("working", True, False), ("done", False, False), ("done", True, True), ("waiting", False, False), ("waiting", True, True))] == [0, 1, 2, 3, 2, 1, 1],
   "report: with art the banner opens the page and the title row is gone; state picks the banner; without art the title stays")
last = strip(render.render_report(dict(done, status="waiting"), "Studio", None, ["$ make", "ok", "", ""], 60))
ok("Last output" in last and "$ make" in last and "took" not in last, "report: no report -> the pane's last lines")
ok("no report yet" in strip(render.render_report(done, "Studio", None, [], 60)), "report: nothing at all -> says so")
lv = {"live": True, "text": "", "start": 1000, "end": None, "tool": "Bash: rg -n 很長的指令" * 6, "said": "第一行\n" + "很長的一行中文" * 20 + "\nlast words",
      "prev": {"text": "## 上輪\n舊報告", "start": 1, "end": 2}, "task": {"ask": "做事", "files": [], "cmds": 2, "agents": 0, "dir": "~/x", "branch": "main", "cwd": "/x"}}
lf = strip(render.render_report(dict(done, status="working"), "Studio", lv, [], 60, now=1000 + 723)).splitlines()
ok("Working · 12m 03s" in lf and "Now" in lf and "last words" in " ".join(lf) and "Previous report" in lf and "舊報告" in " ".join(lf),
   "live report: status row with the time so far, Now block, then the previous round's report")
ok(all(common.cw(l) <= 60 for l in lf), "live report: no row is wider than the width")
colored = "\x1b[31mred\x1b[0m plain"
ok(render.wrap_sgr(colored, 40) == ["\x1b[31mred\x1b[0m plain\x1b[0m"], "Last output: SGR escapes stay as they are")
ok(render.wrap_sgr("a\x1b[2Jb\x1b[1;1Hc\x1b]0;title\x07d\x1b[?25l\x1b[38;5;1me", 40) == ["abcd\x1b[38;5;1me\x1b[0m"],
   "Last output: non-SGR escapes (cursor, clear, OSC) are dropped")
wr = render.wrap_sgr("\x1b[1;32m" + "你好ab" * 5 + "\x1b[0m tail", 9)
ok(len(wr) > 2 and all(common.cw(strip(r)) <= 9 for r in wr) and all(r.endswith("\x1b[0m") for r in wr[:-1])
   and all(r.startswith("\x1b[1;32m") for r in wr[:3]) and wr[-1].endswith(" tail\x1b[0m"),
   "Last output: a long line wraps with the colour carried to every row, every row within the width (CJK = 2)")
sub = {"type": "executor", "desc": "Execute ticket 001", "text": "## 子結果\nsubagent said hi"}
busy = dict(done, summons=[{"type": "executor", "desc": "Branch 還在跑" * 8}])
bf = strip(render.render_report(busy, "Studio", dict(rep, subagents=[sub]), [], 60))
ok("Quest complete" not in bf and "1 subagent still running" in bf.splitlines()[0] and "running" in bf.split("\n\n", 1)[1]
   and all(common.cw(l) <= 60 for l in bf.splitlines()),
   "report: a branch task still running -> title says so instead of Quest complete, task listed as running, rows fit")
bart = render.render_report(busy, "Studio", rep, [], 60, art=True, banner=(40, 5)).splitlines()
ok(len(bart) > 5 and bart[0] == art.image_row(art.banner_id("done", True, True), 0, 40) and "1 subagent still running" in strip(bart[5])
   and all(common.cw(strip(l)) <= 60 for l in bart),
   "report: art plus a running branch task -> banner then the N subagents still running line, rows fit")
wide = render.render_report(done, "Studio", rep, [], 150, 2, 3, art=True, banner=(118, 15), portrait=(24, 14)).splitlines()
wl = [strip(l) for l in wide]
bot = next(i for i, l in enumerate(wl) if l.startswith("┗"))
ok(all(common.cw(l) <= 150 for l in wl) and all(l[0] in "┏┃┗" for l in wl[: bot + 1]) and all(l.startswith(" " * 30) for l in wl[bot + 1 :])
   and (lambda l: common.cw(l[: l.index("結果")]))(next(l for l in wl if "結果" in l)) == 32,
   "report: width >= 100 with art -> every row opens with the side frame or blank, the right column starts at column 32")
bodyw = dict(rep, text="很長的一行中文" * 30 + "\n```\n" + "x" * 150 + "\n```", subagents=[])
bwl = [strip(l) for l in render.render_report(done, "Studio", bodyw, [], 150, art=True, banner=(60, 8), portrait=(24, 14)).splitlines()]
prose = [l.rpartition("┃")[2][2:].rstrip() for l in bwl if "中文" in l]
ok(len(prose) > 3 and all(common.cw(l) <= 60 for l in prose) and max(common.cw(l) for l in prose) >= 58,
   "report: in the split page prose wraps at the banner width, not the whole right column")
ok(max(len(l.rpartition("┃")[2][2:].rstrip()) for l in bwl if "xxx" in l) == 118,
   "report: fenced code in the split page still fills the right column (118 wide)")
nar = [strip(l) for l in render.render_report(done, "Studio", bodyw, [], 99, art=True, banner=(40, 5)).splitlines()]
ok(max(common.cw(l) for l in nar if "中文" in l) >= 90, "report: narrow page (< 100) keeps the whole pane width for prose")
side = render.report_side_rows(done, "Studio", rep, 2, 3, (24, 14))
pid = art.portrait_id(done)
ok(all(common.cw(strip(r)) == 30 for r in side) and strip(side[-1]).startswith("┗") and art.image_row(art.big_portrait_id(done), 13, 24) in side[14]
   and any("TOOK" in r for r in side) and any("12m 40s" in r for r in side),
   "report: side column rows are exactly 30 wide, 14 portrait rows, TOOK shown, frame closes at the content")
task_l = {"ask": "q", "files": ["/w/a.py", "/w/b.py"], "cmds": 1, "agents": 0, "dir": "~/x", "branch": "main", "cwd": "/w"}
side_t = render.report_side_rows(done, "Studio", dict(rep, task=task_l), 1, 1, (24, 14), now=860 + 3725)
took_row = next(r for r in side if "TOOK" in strip(r))
ok(strip(took_row).strip("┃ ").startswith("TOOK") and strip(took_row).strip("┃ ").endswith("12m 40s") and common.cw(strip(took_row)) == 30,
   "report: side column puts the TOOK label left and its value right on one row")
ok(took_row.count(common.fg("code", True) + "TOOK") == 1 and common.fg("fg", True) + "12m 40s" in took_row and common.fg("gold", True) + "TOOK" not in took_row
   and all(common.fg(c, True) + n in "\n".join(side_t) for n, c in (("WAITED", "amber"), ("ASKED", "gold"), ("FILES", "green"), ("WHERE", "violet"))),
   "report: without label images the headings are bold text in their own colors (TOOK cyan, WAITED orange, ASKED gold, FILES green, WHERE violet), not all gold")
side_l = render.report_side_rows(done, "Studio", dict(rep, task=task_l), 1, 1, (24, 14), now=860 + 3725, labels=True)
lab_row = lambda r, n: next(x for x in side_l if art.image_row(art.label_id(n), 0, art.LABEL_COLS[n]) in x)
ok(all(common.cw(strip(lab_row(0, n))) == 30 and strip(lab_row(0, n)).count(chr(0x10EEEE)) == art.LABEL_COLS[n] for n in ("took", "waited", "asked", "files", "where"))
   and "TOOK" not in strip("\n".join(side_l)) and strip(lab_row(0, "took")).strip("┃ ").endswith("12m 40s")
   and not any(art.image_row(art.label_id(n), 0, art.LABEL_COLS[n]) in "\n".join(side_l) for n in ("work", "running")),
   "report: with label images each heading row is its label placeholder (30 wide) with the value at the right; only the headings of this page")
live_s = dict(rep, live=True, end=None, task=task_l)
run_l = render.report_side_rows(dict(done, status="working"), "Studio", live_s, 1, 1, (24, 14), now=100 + 723, labels=True)
run_t = [strip(r) for r in render.report_side_rows(dict(done, status="working"), "Studio", live_s, 1, 1, (24, 14), now=100 + 723)]
ok(any(art.image_row(art.label_id("running"), 0, 11) in r and strip(r).strip("┃ ").endswith("12m 03s") and common.cw(strip(r)) == 30 for r in run_l)
   and not any(art.image_row(art.label_id(n), 0, art.LABEL_COLS[n]) in r for r in run_l for n in ("took", "waited"))
   and any(r.strip("┃ ").startswith("RUNNING") and r.strip("┃ ").endswith("12m 03s") for r in run_t) and not any("TOOK" in r for r in run_t),
   "report: a working member's page has a RUNNING row with the time so far (label image or text) in place of TOOK")
wait_l = render.report_side_rows(dict(done, status="waiting"), "Studio", rep, 1, 1, (24, 14), now=860 + 3725, labels=True)
w_row = next(r for r in wait_l if art.image_row(art.label_id("waited"), 0, 10) in r)
ok(strip(w_row).startswith("┃ !") and common.cw(strip(w_row)) == 30 and "48;2;" in w_row and not any("48;2;" in r for r in wait_l if r != w_row)
   and not strip(next(r for r in side_l if art.image_row(art.label_id("waited"), 0, 10) in r)).startswith("┃ !"),
   "report: a waiting member's WAITED row gets an orange band and a ! in front; a finished one does not")
frames = {s_: render.report_side_rows(dict(done, status=s_), "Studio", rep, 1, 1, (24, 14))[0] for s_ in ("done", "waiting", "working", "idle")}
ok([common.fg(c, True) in frames[s_] for s_, c in (("done", "gold"), ("waiting", "warn"), ("working", "sp"), ("idle", "blue"))] == [True] * 4
   and common.fg("line") not in "".join(frames.values()),
   "report: the side frame is gold when done, orange when waiting, blue-violet while working, blue for other reports")
hv = render.report_side_rows(done, "Studio", rep, 1, 1, (24, 14))
hb = common.fg("gold", True)
ok(hv[0] == hb + "┏" + "━" * 28 + "┓" + common.RESET and hv[-1] == hb + "┗" + "━" * 28 + "┛" + common.RESET
   and all(r.startswith(hb + "┃" + common.RESET) and r.endswith(hb + "┃" + common.RESET) for r in hv[1:-1]),
   "report: the side frame is thick lines (┏━┓┃┗┛) in bold")
ok(not any(c in "".join(render.card(agents[0], 33, False)) for c in "┏━┓┃┗┛") and not any(c in "".join(render.card(agents[0], 33, True)) for c in "┏━┓┃┗┛"),
   "report: member cards keep their own frames, no thick lines")
tag_done = next(r for r in side if "Complete" in strip(r))
tag_wait = next(r for r in render.report_side_rows(dict(done, status="waiting"), "Studio", rep, 1, 1, (24, 14)) if "Waiting" in strip(r))
ok("✓ Complete" in strip(tag_done) and common.fg("green") in tag_done and "! Waiting" in strip(tag_wait) and common.fg("warn") in tag_wait,
   "report: side column shows a status tag in the status colour")
hint_rows = [i for i, l in enumerate(wl) if "⏎ go" in l]
ok(hint_rows == [bot - 1] and wl[bot - 1].startswith("┃") and "⏎ go" in wl[bot - 1][:30],
   "report: split page puts the key hints on the frame's last row, and not in the right column")
ok(wl[0].rstrip() == "┏" + "━" * 28 + "┓" and wide[1].endswith(art.image_row(art.banner_id("done", True, False), 0, 118)),
   "report: the banner opens the right column on the row of the portrait top, one under the frame top")
thin = dict(rep, text="一行")
sw = [strip(l) for l in render.render_report(dict(done, hp=None, hp_left=None), "Studio", dict(thin, start=None), [], 150, art=True, banner=(118, 15), portrait=(24, 14)).splitlines()]
lw = [strip(l) for l in render.render_report(done, "Studio", dict(rep, text="\n".join(f"L{n}" for n in range(60))), [], 150, art=True, banner=(118, 15), portrait=(24, 14)).splitlines()]
ok("TOOK" not in "\n".join(sw) and "HP" not in "\n".join(sw)
   and all(l.startswith(("┏", "┃", "┗", " " * 30)) for l in sw) and any("⏎ go" in l for l in sw) and sum(l.startswith("┗") for l in sw) == 1
   and sum(l.startswith("┗") for l in lw) == 1 and lw[-1].startswith("┗") and "L59" in lw[-3],
   "report: split page with no time or HP prints neither; a short and a long report both keep one closed frame")
task = {"ask": "請幫我把報告頁左欄改成任務資訊\n" + "很長的提問" * 20, "files": ["/w/a.py", "/w/b.py", "/w/c.py", "/w/d.py", "/w/e.py"], "cmds": 12, "agents": 2, "dir": "~/projects/party-hud", "branch": "sdlc/game-feel", "cwd": "/w"}
ti = [strip(r) for r in render.report_side_rows(dict(done, sp=(1800.0, 3600), fresh=False), "Studio", dict(rep, task=task), 1, 1, (24, 14), now=860 + 3725)]
ti_text = "\n".join(ti)
ok(not any(k in ti_text for k in ("HP", "SP", "410k", "60m")) and "ASKED" in ti_text and "請幫我把報告頁" in ti_text
   and sum("很長的提問" in r for r in ti) == 1 and sum("…" in r for r in ti) == 1
   and "12 cmds · 2 agents" in ti_text and "FILES" in ti_text and "a.py" in ti_text and "e.py" in ti_text and "~/projects/party-hud" in ti_text and " sdlc/game-feel" in ti_text and "⎇" not in ti_text
   and any(r.strip("┃ ").startswith("WAITED") and r.strip("┃ ").endswith("1h 02m") for r in ti)
   and all(common.cw(r) == 30 for r in ti),
   "report: side column has no HP or SP; shows the prompt cut to 3 rows, work counts, directory, branch and the wait; all rows 30 wide")
ti = [strip(r) for r in render.report_side_rows(dict(done, hp=None, hp_left=None), "Studio", dict(rep, task={"ask": None, "files": [], "cmds": 3, "agents": 0, "dir": None, "branch": None}), 1, 1, (24, 14))]
bare = [strip(r) for r in render.report_side_rows(done, "Studio", dict(rep, task={"ask": None, "files": [], "cmds": 0, "agents": 0, "dir": None, "branch": None}), 1, 1, (24, 14))]
ok(any("3 cmds" in r for r in ti) and not any("FILES" in r or "agents" in r for r in ti)
   and not any(k in "\n".join(bare) for k in ("ASKED", "WORK", "WHERE", "WAITED")) and all(common.cw(r) == 30 for r in ti + bare)
   and len(bare) == len([strip(r) for r in render.report_side_rows(done, "Studio", rep, 1, 1, (24, 14))]),
   "report: side column omits what it could not get (zero counts, no prompt, no directory, no wait) and stays 30 wide")
os.environ["HOME"] = "/home/me"
ok([collect.home_path(p) for p in ("/home/me", "/home/me/projects/party-hud/", "/home/mex/a", "/srv/x")] == ["~", "~/projects/party-hud", "/home/mex/a", "/srv/x"],
   "report: the home directory is written ~ in the WHERE path; other paths and look-alike prefixes stay")
two = render.where_rows("~/projects/party-hud/subs", 24)
ok(render.where_rows("~/projects/party-hud", 24) == ["~/projects/party-hud"] and two == ["~/projects/party-hud", "/subs"],
   "report: WHERE path stays on one row when it fits, else breaks at a / into a second row")
cut = render.where_rows("~/work/clients/acme/services/billing/api/internal/handlers", 24)
ok(len(cut) == 2 and cut[0].startswith("…/") and cut[1].endswith("/handlers") and "~" not in cut[0] and all(common.cw(r) <= 24 for r in cut),
   "report: WHERE path too long for two rows is cut from the left, starts with …/ and keeps the last segments")
wr = [strip(r) for r in render.report_side_rows(done, "Studio", dict(rep, task={"ask": None, "files": [], "cmds": 0, "agents": 0, "dir": "~/work/clients/acme/services/billing/api/internal/handlers\x1b[31m", "branch": "x" * 40, "cwd": "/w"}), 1, 1, (24, 14))]
ok(all(common.cw(r) == 30 for r in wr) and not any(re.search(r"[\x00-\x1f\x7f]", r) for r in wr),
   "report: WHERE rows (two path rows and a branch row) are exactly 30 wide, control characters dropped")
many = {"ask": "q", "files": [f"/w/party_hud/f{n}.py" for n in range(8)] + ["/w/party_hud/" + "x" * 40 + ".py"], "cmds": 0, "agents": 3, "cwd": "/w"}
fl = [strip(r).strip("┃ ") for r in render.report_side_rows(done, "Studio", dict(rep, task=many), 1, 1, (24, 14))]
fa = [strip(r) for r in render.report_side_rows(done, "Studio", dict(rep, task=dict(many, files=["/w/party_hud/ui.py", "/other/" + "d/" * 20 + "ui.py"], agents=0, cmds=14)), 1, 1, (24, 14))]
ok(fl.count("+4 more") == 1 and "• party_hud/f0.py" in fl and "• party_hud/f4.py" in fl and "party_hud/f5.py" not in "".join(fl) and "3 agents" in fl and not any("/w/" in r for r in fl)
   and any(r.startswith("• …/") and r.endswith("ui.py") for r in (x.strip("┃ ") for x in fa)) and any("14 cmds" in r for r in fa)
   and all(common.cw(r) == 30 for r in fa),
   "report: side column lists files relative to cwd in first-edit order, 6 rows with +N more, long paths cut from the left; all rows 30 wide")
fb = [r for r in render.report_side_rows(done, "Studio", dict(rep, task=many), 1, 1, (24, 14)) if "party_hud/f" in strip(r)]
ok(len(fb) == 5 and all(r.count(common.fg("green", True) + "•") == 1 for r in fb)
   and not any("•" in strip(r) for r in render.report_side_rows(done, "Studio", dict(rep, task=many), 1, 1, (24, 14)) if "more" in strip(r) or "agents" in strip(r)),
   "report: every listed file has a green • bullet; +N more and the counts row do not")
ctl = [strip(r) for r in render.report_side_rows(done, "Studio", dict(rep, task=dict(many, files=["/w/a\x1b[31m\nb\tc\x07.py"], agents=0)), 1, 1, (24, 14))]
ok(any("a[31mbc.py" in r for r in ctl) and not any(re.search(r"[\x00-\x1f\x7f]", r) for r in ctl) and all(common.cw(r) == 30 for r in ctl),
   "report: control characters in an edited file's path never reach the side column; rows stay 30 wide")
short = [strip(l) for l in render.render_report(done, "Studio", dict(rep, text="一行"), [], 150, art=True, banner=(88, 10), portrait=(24, 14), height=60).splitlines()]
long_ = [strip(l) for l in render.render_report(done, "Studio", dict(rep, text="\n".join(f"L{n}" for n in range(60))), [], 150, art=True, banner=(88, 10), portrait=(24, 14), height=20).splitlines()]
ok(len(short) == 59 and short[-1].startswith("┗") and any("⏎ go" in l for l in short) and sum(l.startswith("┗") for l in short) == 1
   and long_[-1].startswith("┗") and len(long_) > 20 and all(common.cw(l) <= 150 for l in short + long_),
   "report: split frame closes on the last row; a short report is padded to the pane height - 1")
busy_w = render.render_report(busy, "Studio", rep, [], 150, art=True, banner=(118, 15), portrait=(24, 14)).splitlines()
ok("1 subagent still running" in strip(busy_w[16]) and strip(busy_w[17]).endswith("┃  "),
   "report: split page puts the N subagents still running line right under the banner")
wide99 = render.render_report(done, "Studio", rep, [], 99, art=True).splitlines()
ok(wide99 == render.render_report(done, "Studio", rep, [], 99, art=True, banner=(80, 10), portrait=(24, 3)).splitlines()
   and not any(strip(l).startswith("┏") for l in wide99)
   and not any(strip(l).startswith("┏") for l in render.render_report(done, "Studio", rep, [], 150).splitlines()),
   "report: below 100 columns, or without art, the old layout stays")
sf = strip(render.render_report(done, "Studio", dict(rep, subagents=[sub]), [], 60))
ok("Quest complete" in sf.splitlines()[0] and sf.index("Execute ticket 001") > sf.index("完成了報告畫面") and "subagent said hi" in sf
   and "## " not in sf and "running" not in sf,
   "report: finished subagent listed below the main report with its own report (Markdown), no running")
nr = strip(render.render_no_report(40, 10)).splitlines()
ok(len(nr) == 10 and "No party members." in nr[1] and all(common.cw(l) == 40 for l in nr[:3]) and "q close" in nr[-1],
   "report popup with no party members: says so and waits (a popup that exits at once only flashes)")
ok(render.wrap("一二三四五", 4) == ["一二", "三四", "五"] and render.wrap("a\tb\x1b[31m", 9) == ["a   b[31m"],
   "report: wrap by display width; tabs expanded, control characters dropped")
md = render.render_markdown
B, I, R, fgc = "\033[1m", "\033[3m", common.RESET, common.fg
ok(md("# T\n###### s", 20) == [fgc("gold", True) + "T" + R, fgc("gold", True) + "s" + R], "markdown: # to ###### headings in gold bold, marker dropped")
ok(md("a **b** c", 20) == ["a " + B + "b" + R + " c"], "markdown: **bold**")
ok(md("*x* _y_ snake_case_name", 30) == [I + "x" + R + " " + I + "y" + R + " snake_case_name"], "markdown: *italic* and _italic_, not the underscores inside a word")
ok(md("a `**x**` b", 20) == ["a " + fgc("code") + "**x**" + R + " b"], "markdown: `inline code` is literal, in the cool code color")
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
mdt = "# T\n\n- a **b** `c`\n\n| h | i |\n|---|---|\n| 1 | 2 |\n\n```\ncode line that is long\n```\nlast line of text"
mdcases = {
    "done": {"live": False, "start": 1, "end": 2, "text": mdt},
    "live": {"live": True, "start": 1, "tool": "Bash", "said": "hi", "prev": {"text": mdt}},
    "subagents": {"live": False, "start": 1, "end": 2, "text": mdt, "subagents": [{"desc": "d", "type": "t", "text": mdt + " 2"}]},
}
for name, rep in mdcases.items():
    render.clear_markdown_cache()
    cold1 = render.report_rows(rep, [], [], 30, 40, 10.0)
    warm = render.report_rows(rep, [], [], 30, 40, 10.0)
    render.clear_markdown_cache()
    ok(cold1 == warm == render.report_rows(rep, [], [], 30, 40, 10.0), f"markdown cache: {name} report gives the same rows reused and recomputed")
render.clear_markdown_cache()
a1 = md(mdt, 30, 40)
ok(md(mdt + "x", 30, 40) != a1 and md(mdt, 12, 40) != a1 and md(mdt, 30, 20) != a1 and md(mdt, 30, 40) == a1, "markdown cache: another text, width or code_width never gets the earlier rows")
ok(md(mdt, 30) == md(mdt, 30, 30), "markdown cache: no code_width means width")
a1.append("junk"); a1[0] = "junk"
ok(md(mdt, 30, 40) == [r for r in md(mdt, 30, 40)] and "junk" not in md(mdt, 30, 40), "markdown cache: editing the returned rows leaves the next call unchanged")
render.clear_markdown_cache()
md(mdt, 30, 40); h0 = render._markdown_rows.cache_info().hits; md(mdt, 30, 40)
ok(render._markdown_rows.cache_info().hits == h0 + 1, "markdown cache: the same input a second time is a hit, not laid out again")
raw = ["  - **x**", "  - nested", "| a | b |", "![img](u.png)", "<b>x</b>"]
ok(md("\n".join(raw), 30) == raw, "markdown: nested lists, tables, images and HTML are shown as written")
tb = "| 名稱 | `k` |\n|:--|--:|\n| 一二 | **x** |\n| ab | yy |"
tr = md(tb, 20)
ok([strip(r) for r in tr] == ["名稱 │ k", "─────┼───", "一二 │ x", "ab   │ yy"] and tr[1] == fgc("dim") + "─────┼───" + R and "│" in tr[0] and tr[0].startswith(B + "名稱"),
   "markdown: a table that fits is aligned columns (CJK = 2), bold header, rule under it, no |---| row")
tn = md(tb, 8)
ok([strip(r) for r in tn] == ["名稱：一", "  二", "k：x", "", "名稱：ab", "k：yy"] and tn[0].startswith(fgc("dim") + "名稱："),
   "markdown: a table too wide becomes name: value groups, a blank row between rows")
ok([strip(r) for r in md("| 名稱 | v |\n|--|--|\n| 一二三四五六 | `ab cd` |", 12)] == ["名稱：一二三", "  四五六", "v：ab cd"]
   and all(common.cw(strip(r)) <= w for w in (1, 2, 3, 5, 12) for r in md(tb, w)),
   "markdown: long table cells wrap with an indent and no table row is wider than width")
ok([strip(r) for r in md("| a | b |\n|--|--|\n| 1 |", 20)] == ["a │ b", "──┼──", "1 │ "],
   "markdown: a short table row is padded with empty cells")
ok(md("| a | b |\nplain", 30) == ["| a | b |", "plain"], "markdown: a | line without a separator row is plain text")
ok([strip(r) for r in md("Haven't seen the report yet", 12)] == ["Haven't seen", "the report", "yet"], "markdown: English wraps at the last space that fits, words stay whole")
ok([strip(r) for r in md("ab abcdefghij", 6)] == ["ab", "abcdef", "ghij"], "markdown: a word wider than the row is cut hard")
ok([strip(r) for r in md("一二三，四五。六", 6)] == ["一二", "三，四", "五。六"] and all(common.cw(strip(r)) <= 6 for r in md("一二三，四五。六", 6)),
   "markdown: closing punctuation never starts a row, the previous character comes along")
qr = md("> a **b**\n> > c", 20)
ok([strip(r) for r in qr] == ["▎ a b", "▎▎ c"] and all(r.startswith(fgc("dim") + "▎") for r in qr) and md("> x", 20)[0].endswith(fgc("dim") + "x" + R),
   "markdown: a quote line gets a dim ▎ edge (one per level) and dim text")
ok([strip(r) for r in md("> aaa bbb ccc", 7)] == ["▎ aaa", "▎ bbb", "▎ ccc"], "markdown: every wrapped row of a quote keeps the ▎ edge")
wide_cases = [("a。。。", 5), ("a" + "，" * 9 + "。", 21), ("- 一" + "）" * 8 + "。", 20), ("> > > > > x", 4), ("> abc", 1)]
ok(all(common.cw(strip(r)) <= w and "".join(strip(x) for x in md(t, w)).replace("▎", "").replace("•", "").replace(" ", "") == t.replace("> ", "").replace("- ", "").replace(" ", "")
       for t, w in wide_cases for r in md(t, w)), "markdown: no row is wider than width and no text is lost, even when punctuation carrying has no room")
ok([strip(r) for r in md("see README.md 」", 14)] == ["see README.md", "」"] and [strip(r) for r in md("abcd   ef", 4)] == ["abcd", "ef"] and [strip(r) for r in md("word 。。。", 6)] == ["word", "。。。"] and [strip(r) for r in md("   abcdef", 3)] == ["abc", "def"],
   "markdown: wrapping never leaves a leading space or an empty row")
ok([strip(r) for r in md("aa bcd，", 6)] == ["aa", "bcd，"] and [strip(r) for r in md("- aa bcd，", 8)] == ["• aa", "  bcd，"],
   "markdown: closing punctuation carries the whole English word to the next row, in lists too")
ok([strip(r) for r in md("see README.md」", 14)] == ["see", "README.md」"] and [strip(r) for r in md("> see README.md」", 16)] == ["▎ see", "▎ README.md」"],
   "markdown: the carried word keeps its own trailing punctuation, in quotes too")
ok("".join(strip(r) for r in md("> 中文", 3)) == "中文" and all(common.cw(strip(r)) <= 3 for r in md("> 中文", 3)),
   "markdown: a quote too narrow for the edge drops the edge, not the text")
mk = lambda pane, status: {"pane": pane, "status": status}
qt = [{"name": "A", "agents": [mk("%1", "done"), mk("%2", "working"), mk("%3", "waiting")]},
      {"name": "B", "agents": [mk("%4", "done")]}]
ok(ui.banner_cells(170, 0.452) == (106, 6, 8) and ui.banner_cells(150, 0.452) == (106, 6, 8) and ui.banner_cells(120, 0.2) == (88, 4, 4) and ui.banner_cells(105, 0.452) == (73, 6, 5),
   "report banner: split fills the right column (at most 6 rows) with the 4:1..8:1 image closest to cols x ratio / rows")
ok(ui.banner_cells(400, 0.5) == (96, 6, 8),
   "report banner: flatter than 8:1 narrows the cols to the 8:1 width (rows x 8 / ratio)")
ok(ui.banner_cells(99, 0.452) == (53, 6, 4) and ui.banner_cells(60, 0.452) == (53, 6, 4) and ui.banner_cells(40, 0.452) == (40, 5, 4) and ui.banner_cells(400, 0.5)[2] == 8,
   "report banner: narrow stays 4:1 with at most 6 rows, a capped height sets the width (rows x 4 / ratio)")
ok(art.image_row(art.banner_id("done", True, False, 8), 0, 106) in render.render_report(done, "Studio", rep, [], 150, art=True, banner=(106, 6, 8), portrait=(14, 7)).splitlines()[1],
   "report: the banner row carries the image id of its k:1 ratio")
fake_art = {art.banner_id("done", True, False): (b"B",), art.portrait_id(done): (b"P", 6, 3), art.big_portrait_id(done): (b"G",)}
bid_, pid_, big_ = art.banner_id("done", True, False), art.portrait_id(done), art.big_portrait_id(done)
sp = ui.report_images(done, True, fake_art, 150, (118, 15), (20, 11))
nr = ui.report_images(done, True, fake_art, 90, (80, 10), (20, 11))
ok(sp.index(f"a=d,d=I,i={bid_}") < sp.index(f"a=T,U=1,f=100,i={bid_},c=118,r=15")
   < sp.index(f"a=d,d=I,i={big_}") < sp.index(f"a=T,U=1,f=100,i={big_},c=20,r=11") and big_ != pid_ and f"i={pid_}," not in sp
   and f"a=d,d=I,i={pid_}," not in nr and f"a=d,d=I,i={big_}," not in nr and f"a=T,U=1,f=100,i={pid_},c=6,r=3" in nr and f"i={big_}," not in nr,
   "report images: split deletes then sends the banner and the big portrait (own id); narrow never deletes the sidebar portrait and sends its id")
fake_art.update({art.label_id("took"): (b"L",), art.label_id("where"): (b"M",)})
lb = ui.report_images(done, True, fake_art, 150, (118, 15), (20, 11), None, ["took", "where"])
lb_n = ui.report_images(done, True, fake_art, 90, (80, 10), (20, 11), None, ["took"])
tid, wid = art.label_id("took"), art.label_id("where")
ok(f"i={tid},c=8,r=1,q=2,m=0;TA==" in lb and f"i={wid},c=9,r=1" in lb and f"i={art.label_id('files')}," not in lb and f"i={tid}," not in lb_n
   and ui.report_images(done, True, fake_art, 150, (118, 15), (20, 11), {bid_: (118, 15), big_: (20, 11), tid: (8, 1), wid: (9, 1)}, ["took", "where"]) == ""
   and f"i={wid},c=9,r=1" in ui.report_images(done, True, fake_art, 150, (118, 15), (20, 11), {bid_: (118, 15), big_: (20, 11), tid: (8, 1)}, ["took", "where"]),
   "report images: split also sends the labels this page shows (1 row, their own cols); a redraw skips unchanged ones and sends a new one; narrow sends none")
rd_same = ui.report_images(done, True, fake_art, 150, (118, 15), (20, 11), {bid_: (118, 15), big_: (20, 11)})
rd_big = ui.report_images(done, True, fake_art, 150, (118, 15), (24, 12), {bid_: (118, 15), big_: (20, 11)})
rd_new = ui.report_images(done, True, fake_art, 90, (80, 10), (20, 11), {bid_: (118, 15), big_: (20, 11)})
ok(rd_same == "" and "a=d" not in rd_big and f"i={big_},c=24,r=12" in rd_big and f"i={bid_}," not in rd_big
   and "a=d" not in rd_new and f"i={bid_},c=80,r=10" in rd_new and f"i={pid_},c=6,r=3" in rd_new,
   "report images: a redraw at the same cells sends nothing, a resized image is resent without a delete, unchanged ones are skipped")
pg_same = ui.report_images(done, True, fake_art, 150, (118, 15), (20, 11), None, (), {bid_: (118, 15), big_: (20, 11)})
pg_big = ui.report_images(done, True, fake_art, 150, (118, 15), (24, 12), None, (), {bid_: (118, 15), big_: (20, 11)})
pg_new = ui.report_images(done, True, fake_art, 150, (118, 15), (20, 11), None, (), {bid_: (118, 15)})
ok(pg_same == "", "report images: a new page sends nothing for an id this pane already sent at the same cells")
ok("a=d" not in pg_big and f"i={big_},c=24,r=12" in pg_big and f"i={bid_}," not in pg_big,
   "report images: a new page resends an id sent at other cells under the same id, without a delete")
ok(pg_new.index(f"a=d,d=I,i={big_}") < pg_new.index(f"a=T,U=1,f=100,i={big_},c=20,r=11") and f"i={bid_}," not in pg_new,
   "report images: a new page deletes an id this pane never sent before its image")
fd_sp = ui.report_first_deletes(done, True, fake_art, 150, (118, 15), (20, 11), {bid_: (118, 15)})
fd_nr = ui.report_first_deletes(done, True, fake_art, 90, (80, 10), (20, 11), {})
ok(fd_sp == art.kitty_delete(big_) and "a=T" not in fd_sp and f"a=d,d=I,i={bid_}," in fd_nr and f"i={pid_}," not in fd_nr,
   "report first frame: deletes only the ids this pane never sent, never the sidebar portrait")
ok(f"i={big_},c=20,r=11,q=2,m=0;Rw==" in sp and "UA==" not in sp and "UA==" in nr and "Rw==" not in nr,
   "report images: split sends the big portrait PNG bytes, narrow sends the small portrait bytes")
pc_, pr_ = ui.portrait_cells(0.452)
raw_wide = render.render_report(done, "Studio", rep, [], 150, art=True, banner=(96, 6), portrait=(pc_, pr_)).splitlines()
ok(pc_ == art.SPLIT_BIG_PORTRAIT_COLS == 14 and pr_ == 7 and strip(raw_wide[1]).startswith("┃" + " " * 7 + chr(0x10EEEE))
   and art.image_row(art.big_portrait_id(done), 0, 14) in raw_wide[1] and art.image_row(art.banner_id("done", True, False), 0, 96) in raw_wide[1],
   "report: split portrait is SPLIT_BIG_PORTRAIT_COLS wide, centered in the frame, and its top row shares a row with the banner top")
ok(ui.select_banner(80, 40, 0.5)[1] == 10 and ui.select_banner(150, 60, 0.452)[1] == 10 and ui.banner_cells(143, 0.5)[1] == 6,
   "select banner: still at most 10 rows, not capped by the report banner limit")
ok([a["pane"] for _, a in ui.report_queue(qt)] == ["%3", "%1", "%4", "%2"], "report queue: waiting first, then done, then the rest")
ok([a["pane"] for _, a in ui.report_queue(qt, "%2")] == ["%2", "%3", "%1", "%4"] and ui.report_queue(qt, "%2")[0][0] == "A",
   "report queue: the pane asked for comes first, whatever its status")
ok(abs(ui.report_resize_wait(5.0, 5.0) - ui.RESIZE_INTERVAL) < 1e-9 and ui.RESIZE_INTERVAL > 0 and abs(ui.report_resize_wait(5.0, 5.02) - (ui.RESIZE_INTERVAL - 0.02)) < 1e-9
   and ui.report_resize_wait(5.0, 5.0 + ui.RESIZE_INTERVAL) == 0 and ui.report_resize_wait(5.0, 9.0) == 0,
   "report resize: redraws are at least RESIZE_INTERVAL apart, a redraw after a pause is not delayed")
ok(ui.ART_SETTLE > ui.report_art_wait(None) == ui.REPORT_ART_SETTLE > 0 and ui.report_art_wait({1: (10, 5)}) == 0 and ui.report_art_wait({}) == 0,
   "report art wait: a fresh page (first open, n) waits REPORT_ART_SETTLE (shorter than the sidebar's ART_SETTLE), a resize redraw sends images at once")
pk, grabs = {}, []
ok(ui.report_peek(pk, "%1", None, None, lambda p: grabs.append(p) or ["x"]) == ["x"] and ui.report_peek(pk, "%1", None, None, lambda p: grabs.append(p) or ["y"]) == ["x"]
   and grabs == ["%1"] and ui.report_peek(pk, "%2", {}, None, grabs.append) == [] and grabs == ["%1"],
   "report peek: a redraw reuses the captured peek instead of grabbing the pane again")
qs = [{"name": "A", "agents": [dict(mk("%1", "working"), summons=[{}]), mk("%2", "working"), mk("%3", "done"), dict(mk("%4", "working"), summons=[])]},
      {"name": "B", "agents": [mk("%5", "waiting"), dict(mk("%6", "working"), summons=[{}])]}]
ok([a["pane"] for _, a in ui.report_queue(qs)][:4] == ["%5", "%3", "%1", "%6"],
   "report queue: working member with running subagents comes after waiting and done")
qi = [{"name": "A", "agents": [dict(mk("%1", "idle"), window="@1"), dict(mk("%2", "idle"), window="@2"), dict(mk("%3", "working"), window="@2")]}]
ok([a["pane"] for _, a in ui.report_queue(qi)] == ["%1", "%2", "%3"], "report queue: with nobody waiting or done, idle and working members are still queued")
qw = [{"name": "A", "agents": [dict(mk("%1", "idle"), window="@1"), dict(mk("%2", "waiting"), window="@2"), dict(mk("%3", "idle"), window="@1")]}]
ok([a["pane"] for _, a in ui.report_queue(qw, None, "@1")] == ["%2", "%1", "%3"], "report queue: a member waiting for you stays first, the current window's members follow")
ok([a["pane"] for _, a in ui.report_queue(qi, None, "@2")] == ["%2", "%3", "%1"], "report queue: members of the current window come before the other idle or working ones")
qm = [{"name": "A", "agents": [dict(mk("%1", "idle"), window="@1")]}, {"name": "B", "agents": [dict(mk("%2", "idle"), window="@2")]}]
ok([a["pane"] for _, a in ui.report_queue(qm, None, "@2")] == ["%2", "%1"], "report queue: the caller's window orders the queue, whichever session it is in")
ok([a["pane"] for _, a in ui.report_queue(qi, "%3", "@2")] == ["%3", "%2", "%1"], "report queue: the pane asked for stays first with a current window")
ok(ui.report_queue([]) == [] and ui.report_queue([{"name": "A", "agents": []}], "%1", "@1") == [], "report queue: no members, empty queue")
ok(ui.handle_key("r", {"focus": "party", "sel": "%1", "squad": None, "peek": False}, towns, "sidebar") == "report"
   and ui.handle_key("r", {"focus": "party", "sel": "%1", "squad": None, "peek": False}, towns, "popup") is None,
   "r in the sidebar opens the report pane (not inside the P popup)")
mm = lambda pane, name, status, lead=None: dict(mk(pane, status), name=name, **({"lead": lead} if lead else {}))
mt = [{"name": "Studio", "agents": [mm("%1", "a", "idle"), mm("%2", "b", "working"), mm("%3", "c", "waiting"), mm("%4", "d", "done")]},
      {"name": "Empty", "agents": []}, {"name": "Lab", "agents": [mm("%5", "lead", "working"), mm("%6", "w1", "idle", "%5"), mm("%7", "w2", "waiting", "%5"), mm("%8", "e", "waiting")]}]
sk = ["%1", "%2", "%3"]
ok(ui.select_key("j", sk, "%1") == ("%2", None) and ui.select_key("k", sk, "%3") == ("%2", None)
   and ui.select_key("k", sk, "%1") == ("%1", None) and ui.select_key("j", sk, "%3") == ("%3", None),
   "select keys: j and k move one row and stop at the first and last row")
ok(ui.select_key("1", sk, "%3") == ("%1", "open") and ui.select_key("3", sk, "%1") == ("%3", "open")
   and ui.select_key("4", sk, "%2") == ("%2", None) and ui.select_key("9", sk, "%2") == ("%2", None) and ui.select_key("0", sk, "%2") == ("%2", None),
   "select keys: a digit opens that row's member, a digit past the last row or 0 does nothing")
ok(ui.select_key("\r", sk, "%2") == ("%2", "open") and ui.select_key("\n", sk, "%2") == ("%2", "open") and ui.select_key("l", sk, "%2") == ("%2", "open")
   and ui.select_key("q", sk, "%2") == ("%2", "close") and ui.select_key("\x1b", sk, "%2") == ("%2", "close"),
   "select keys: Enter and l open, q and Esc close")
ok(all(ui.select_key(k, sk, "%2") == ("%2", None) for k in ("h", "x", "J", "PgUp", " ", "n", "g"))
   and ui.select_key("j", [], None) == (None, None) and ui.select_key("\r", [], None) == (None, None) and ui.select_key("q", [], None) == (None, "close"),
   "select keys: g, h and other keys do nothing; an empty roster only closes")
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
sq = lambda ags: {"name": "S", "agents": ags}
st = [sq([mm("%1", "idle1", "idle"), mm("%2", "work1", "working"), mm("%3", "done1", "done"), mm("%4", "wait1", "waiting"), mm("%5", "sleep1", "sleep"),
          mm("%6", "c1", "waiting", "%9"), mm("%7", "c2", "done", "%2"), mm("%8", "cc", "waiting", "%6")]),
      {"name": "T", "agents": [mm("%9", "far", "idle"), mm("%10", "c3", "waiting", "%9"), mm("%11", "c4", "waiting", "%9"), mm("%12", "c5", "waiting", "%2")]}]
rs = render.select_roster(st)
ok([(a["pane"], c) for _, a, c in rs] == [("%2", False), ("%12", True), ("%4", False), ("%9", False), ("%6", True), ("%10", True), ("%11", True),
                                          ("%3", False), ("%1", False), ("%5", False)],
   "select roster: leads waiting > done > working > idle > sleep; a lead with waiting crew ranks as waiting; crew only when waiting, right after its lead (also across squads), in snapshot order")
ok("%7" not in [a["pane"] for _, a, _ in rs] and "%8" not in [a["pane"] for _, a, _ in rs],
   "select roster: a done crew and a crew pointing at another crew are not listed")
sm = lambda pane, name, status, lead=None: {**dict(done, pane=pane, name=name, status=status, round=1, summons=[], focus=False), **({"lead": lead} if lead else {})}
sst = [{"name": "S", "agents": [sm("%1", "idle1", "idle"), sm("%2", "work1", "working"), sm("%3", "done1", "done"), sm("%4", "wait1", "waiting"), sm("%5", "sleep1", "sleep"),
                               sm("%6", "c1", "waiting", "%9"), sm("%7", "c2", "done", "%2"), sm("%8", "cc", "waiting", "%6")]},
       {"name": "T", "agents": [sm("%9", "far", "idle"), sm("%10", "c3", "waiting", "%9"), sm("%11", "c4", "waiting", "%9"), sm("%12", "c5", "waiting", "%2")]}]
srs = render.select_roster(sst)
srep = {"text": "## Layout\n\nThe list fills the pane.\n\n" + "\n".join(f"- point {i}" for i in range(80)), "start": 100.0, "end": 400.0, "live": False,
        "task": {"ask": "fix the menu size", "files": [], "cmds": 0, "agents": 0, "dir": "~/work/app", "branch": None, "cwd": "/w"}}
PH = chr(0x10EEEE)
srows_of = lambda w, h, sel, rep=srep, art=False, ro=srs, tw=sst: render.render_select(ro, tw, sel, w, h, rep, 4000.0, None, art)
seen_all = True
for w, h in [(180, 47), (100, 30), (78, 20), (77, 20), (36, 12), (35, 12), (34, 8), (30, 6), (80, 5), (80, 4), (80, 3), (80, 2), (80, 1), (30, 1), (80, 60)]:
    for art_ in (False, True):
        for rep_ in (srep, None):
            out = srows_of(w, h, "%9", rep_, art_)
            seen_all = seen_all and len(out) == h and all(common.cw(strip(r)) == w for r in out)
ok(seen_all, "select screen: exactly height rows of exactly width cells, wide and narrow panes, tiny heights, with and without art and report")
wide_r, wider_r = srows_of(100, 40, "%2"), srows_of(180, 40, "%2")
rule_w = lambda out: len(strip(out[next(i for i, r in enumerate(out) if "not marked read" in strip(r)) + 1])[38:].rstrip())
ok(rule_w(wide_r) == 100 - 36 - 2 and rule_w(wider_r) == 180 - 36 - 2,
   "select screen: the preview column is the pane width minus the list and the gap, so it grows with the pane")
ok("not marked read" in "".join(strip(r) for r in srows_of(78, 40, "%2")) and "not marked read" not in "".join(strip(r) for r in srows_of(77, 40, "%2"))
   and all(strip(r).startswith(" ") and common.cw(strip(r)) == 77 for r in srows_of(77, 40, "%2")) and strip(srows_of(77, 40, "%2")[2])[3] in "╭╔",
   "select screen: a pane too narrow for the preview draws only the list, flush left")
cur = srows_of(180, 40, "%4")
ok(sum("❯" in r for r in cur) == 1 and sum("╔" in r for r in cur) == 1 and sum("╭" in r for r in cur) >= 2 and "❯" not in "".join(srows_of(180, 40, "%12")),
   "select screen: the member under the cursor is the selected card (gold double frame, ❯), the others plain; on a crew row no card is selected")
lines = [strip(r) for r in srows_of(180, 40, "%2")]
top_ = next(i for i, l in enumerate(lines) if "work1" in l)
ok(lines[top_ - 1][3] in "╭╔" and lines[top_ + 3][3] in "╰╚" and lines[top_ + 3][3] != lines[top_ - 1][3], "select screen: the lead's card is five rows, its name on the second")
cr = next(i for i, l in enumerate(lines) if "c5" in l and render.CREW_MARK in l)
ok(("╰" in lines[cr - 1] or "╚" in lines[cr - 1]) and "work1" in lines[cr - 4] and lines[cr].startswith(" 2 ") and render.CREW_MARK in lines[cr],
   "select screen: a waiting crew is one row right under its lead's card, with its key and connector, not a card")
art_out = srows_of(180, 47, "%2", srep, True)
ok("".join(art_out).count(PH) == 18 * sum(1 for r in art_out if "╭" in strip(r) or "╔" in strip(r))
   and not any(w in strip(r)[40:] for r in srows_of(180, 47, "%2") for w in ("HP ", "SP ", "work1", "Thief", "Cleric")),
   "select screen: the right column has no portrait, name, class or HP/SP (one small portrait per card only)")
mo = [strip(r) for r in srows_of(100, 20, "%2")]
last = max(i for i, l in enumerate(mo) if "to read" in l)
rule_i = next(i for i, l in enumerate(mo) if "─" * 10 in l)
ok("more lines" in mo[last] and mo[last].split("…")[1].split()[0] == str(len(render.report_rows(srep, [], [], 100 - 36 - 2, 100 - 36 - 2, 4000.0)) - (last - rule_i - 1)) and last == len(mo) - 2,
   "select screen: a report that does not fit ends in a '… N more lines · ⏎ to read' row with N the rows left out")
short = {"text": "short report", "start": 1.0, "end": 2.0, "task": {}}
ok(not any("more line" in l for l in map(strip, srows_of(180, 40, "%2", short))) and any("no report yet" in strip(r) for r in srows_of(180, 40, "%2", None)),
   "select screen: a report that fits has no more-lines row; no report shows no report yet")
cxst = [{"name": "S", "agents": [{**sm(f"%{i}", f"m{i}", st_), **({"kind": "codex", "sp": None} if i % 2 else {})} for i, st_ in enumerate(["waiting", "done", "working", "idle", "waiting", "idle", "done", "sleep"], 20)]}]
cxro = render.select_roster(cxst)
ok({len(render.card(a, render.SELECT_CARD, False, False)) for _, a, _ in cxro} == {4, 5}, "select screen: fixture has both 4-row (codex) and 5-row (claude) cards without art")
cx_ok = True
for w, h in [(179, 47), (100, 30), (100, 20), (100, 14), (179, 12)]:
    for _, a, _ in cxro:
        out = [strip(r) for r in srows_of(w, h, a["pane"], srep, False, cxro, cxst)]
        cx_ok = cx_ok and len(out) == h and all(common.cw(r) == w for r in out) and "more lines" in out[-2]
ok(cx_ok, "select screen: with 4-row and 5-row cards mixed the screen is exactly height rows of width cells and the preview still ends in the more-lines row, for every cursor position")
pk_rows = lambda rep, pk_: [strip(r) for r in render.render_select(srs, sst, "%2", 120, 30, rep, 4000.0, None, False, pk_)]
ok(any("$ make test" in r for r in pk_rows(None, ["$ make test", "ok"])) and not any("no report yet" in r for r in pk_rows(None, ["$ make test"]))
   and any("no report yet" in r for r in pk_rows(None, [])) and not any("$ make test" in r for r in pk_rows(srep, ["$ make test"])),
   "select screen: with no report the preview shows the pane's last lines, and no report yet only when there are none either")
live_r = {"live": True, "start": 3700.0, "end": None, "text": "", "tool": "Bash make", "said": "building", "prev": None, "task": {}}
st_of = lambda status, rep, pk_=(): next((strip(r)[38:] for r in render.render_select(srs, sst, {"done": "%3", "waiting": "%4", "idle": "%1", "working": "%2"}[status], 120, 30, rep, 4000.0, None, False, pk_) if "preview · not marked read" in strip(r)), "")
fin = dict(srep, live=False)
ok(st_of("done", fin).startswith("Quest complete") and st_of("waiting", fin).startswith("Waiting for you") and st_of("idle", fin).startswith("Report")
   and st_of("working", live_r).startswith("Working") and st_of("working", None, ["x"]).startswith("Last output"),
   "select screen: the preview title row opens with the state word the report page uses")
wk = [strip(r) for r in render.render_select(srs, sst, "%2", 120, 30, live_r, 4000.0, None, False)]
ok(sum("Working" in r for r in wk) == 1 and any("RUNNING" in r and "5m 00s" in r for r in wk), "select screen: a working preview names the state once (title row) and keeps the time")
many = [("S", sm(f"%{i}", f"m{i}", "idle"), False) for i in range(12)] + [("S", sm("%30", "crew-a", "waiting", "%11"), True)]
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
ok(vis, "select screen: a list taller than the pane scrolls by whole cards so the cursor's card or crew row is always fully shown, never half a card")
ok(any("far" in strip(r) for r in srows_of(100, 6, "%9")) and not any("╭" in r or "╔" in r for r in srows_of(100, 6, "%9")) and any("╔" in r for r in srows_of(100, 9, "%9")),
   "select screen: with less room than one card every item is one row")
emp = render.render_select([], [], None, 40, 12)
ok(len(emp) == 12 and all(common.cw(strip(r)) == 40 for r in emp) and sum("no party members" in r for r in emp) == 1 and "PARTY SELECT" in strip(emp[0]),
   "select screen: an empty roster shows one centered no party members row")
ok("PARTY SELECT" in strip(render.render_select(srs, sst, "%4", 80, 20)[0]) and strip(render.render_select(srs, sst, "%4", 80, 20, None, None, ["ban", "ner"])[1]).strip() == "ner"
   and "j/k" in strip(render.render_select(srs, sst, "%4", 80, 20)[-1]),
   "select screen: default title, a given title replaces it, the hint is the last row")
ok(strip(render.select_summary(rs, st, 60)).split() == ["6", "leads", "6", "need", "you", "4", "crew", "waiting"]
   and strip(render.select_summary([("S", mm("%1", "a", "idle"), False)], [sq([mm("%1", "a", "idle")])], 30)).split() == ["1", "lead"],
   "select summary: lead, need-you (waiting or done leads plus waiting crew) and waiting-crew counts; zero counts are left out")
ok("c3 waiting" in strip(render.select_crew_line(st[1]["agents"][0], st, 40)) and "c4 waiting" in strip(render.select_crew_line(st[1]["agents"][0], st, 60))
   and "c2 done" in strip(render.select_crew_line(st[0]["agents"][1], st, 40))
   and render.select_crew_line(st[0]["agents"][0], st, 40) is None and common.cw(strip(render.select_crew_line(st[1]["agents"][0], st, 12))) == 12,
   "select crew line: all crew of the lead with their status, None without crew, exact width")
ok(not any("crew " in strip(r)[38:] for r in srows_of(180, 40, "%1")) and any(strip(r)[38:].startswith("crew") for r in srows_of(180, 40, "%2")),
   "select screen: no crew line in the preview of a member without crew, one for a lead with crew")
ok(ui.select_image_plan([sst[1]["agents"][0]], {art.portrait_id(sst[1]["agents"][0]): (b"x", 6, 3)}) == [(art.portrait_id(sst[1]["agents"][0]), 6, 3)]
   and ui.select_image_plan([sst[1]["agents"][0]], None) == []
   and art.kitty_delete(7) not in ui.select_images_out([(7, 6, 3)], {7: (b"x", 6, 3)}, {}, {7}) and art.kitty_delete(8) in ui.select_images_out([(8, 6, 3)], {8: (b"x", 6, 3)}, {}, {7}),
   "select images: the plan is the small portrait of each card on screen; an id the sidebars share is not deleted before the send")
cw_row = lambda name, w, sel="%9": render.select_row(2, sm("%20", name, "waiting", "%9"), True, sel, w)
cw_ok = all(common.cw(strip(cw_row(n, w))) == w for n in ("c1", "建置-worker-with-a-very-long-name", "你好世界") for w in range(12, 60))
wr = strip(cw_row("c1", 40))
ok(cw_ok and wr.rstrip().endswith("waiting for you") and render.CREW_MARK in wr and "c1" in wr and strip(cw_row("c1", 40, "%20")).rstrip().endswith("waiting for you")
   and "\033[1;" in cw_row("c1", 40) and common.fg("warn", True) in cw_row("c1", 40) and common.bg("sel") in cw_row("c1", 40, "%20")
   and "waiting for you" in strip(cw_row("a-long-crew-name-here", 40)) and "…" in strip(cw_row("a-long-crew-name-here", 40)),
   "select row: a waiting crew row is bold in the waiting color with 'waiting for you' at the right, exactly width cells, name shortened first, selected style visible")
ok("waiting for you" not in strip(cw_row("c1", 14)) and "c1" in strip(cw_row("c1", 14)) and "waiting for you" not in strip(render.select_row(2, sm("%21", "idle1", "idle"), False, "%1", 40)),
   "select row: too narrow for the text it is left out; a lead row has none")
cache0 = (("%2", 1), None, [], 100.0)
ok(not ui.select_reread(cache0, sm("%2", "w", "idle"), 200.0) and not ui.select_reread(cache0, sm("%2", "w", "done"), 200.0)
   and ui.select_reread(cache0, sm("%3", "w", "idle"), 100.0) and ui.select_reread(cache0, dict(sm("%2", "w", "idle"), round=2), 100.0)
   and ui.select_reread(cache0, sm("%2", "w", "working"), 100.0 + ui.LIVE_REFRESH) and not ui.select_reread(cache0, sm("%2", "w", "working"), 100.0 + ui.LIVE_REFRESH - 0.1),
   "select preview: a working member is re-read every LIVE_REFRESH seconds; any other is re-read only when the member or its round changes")
tw_ = lambda now, anchors: ui.tick_wait(now, anchors) - ui.TICK_MARGIN
sec_ = lambda a: (a, 1.0)
ok(abs(tw_(105.0, [sec_(100.3)]) - 0.3) < 1e-6 and abs(tw_(105.3, [sec_(100.3)]) - 1.0) < 1e-6 and abs(tw_(105.0, [sec_(100.3), sec_(100.8)]) - 0.3) < 1e-6
   and abs(tw_(105.5, [sec_(100.3), sec_(100.8)]) - 0.3) < 1e-6 and abs(tw_(105.0, [ui.SECOND, sec_(100.3)]) - 0.3) < 1e-6 and ui.tick_wait(105.0, []) == float('inf')
   and abs(tw_(130.0, [(100.0, 60.0)]) - 30.0) < 1e-6 and abs(tw_(130.0, [(100.0, 60.0), ui.SECOND]) - 1.0) < 1e-6,
   "time ticks: the wait is up to the next anchor + n * period (a whole period when exactly on it, the earliest of several anchors), never without anchors")
ok(ui.time_anchor(100.0, 3599.4 + 100.0) == (100.5, 1.0) and ui.time_anchor(100.0, 3599.6 + 100.0) == (99.5, 60.0) and ui.time_anchor(100.0, 100.0) == (100.5, 1.0),
   "time anchor: below 3600 shown seconds turn at timestamp + n + 0.5 every second; from 3600 shown on only the minute turns, at timestamp + 60 n - 0.5")
ok(abs(ui.select_wait(10.0, 10.2, 10.9, 10.4) - 0.5) < 1e-9 and ui.select_wait(10.0, 10.2, 10.3, 10.4) == 0.0
   and abs(ui.select_wait(10.0, 10.2, 40.0, 10.4) - 0.8) < 1e-9 and abs(ui.select_wait(10.0, 10.2, float('inf'), 10.4) - 0.8) < 1e-9,
   "select screen: the wait ends at the tick when that is within SNAP_MAX of the last snapshot read, else a second after the read; a second after the read without ticks")
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
        wakes, reads = sel_sched(lambda t: anchors_of(t, fr), 5000.0)
        worst = max(worst, (len(wakes) - 1) / 60)
        gap = max(gap, max(b - a for a, b in zip(reads, reads[1:])))
    return worst, gap
rates = {name: sel_rates(f) for name, f in {
    "none": lambda t, fr: [],
    "done_cursor_hp": lambda t, fr: [ui.SECOND],
    "waiting": lambda t, fr: [ui.time_anchor(4900.0 + fr, t)],
    "working_live": lambda t, fr: [ui.SECOND, ui.time_anchor(4900.0 + fr, t)],
    "waiting_hour": lambda t, fr: [ui.time_anchor(1000.0 + fr, t)]}.items()}
ok(rates["none"][0] <= 1 and rates["done_cursor_hp"][0] <= 1 and rates["waiting"][0] <= 1 and rates["working_live"][0] <= 2 and rates["waiting_hour"][0] <= 1 and rates["working_live"][0] > 1.5,
   "select screen: at most 1 recompute a second with no ticking time, the spinner or a waiting member's WAITED alone, at most 2 for a live working member (two phases)")
ok(all(gap <= 2.0 for _, gap in rates.values()), "select screen: the snapshot is read at least every 2 seconds in every state, also with ticks 60 s apart or none")
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
sel_ok = True
for fr in (0.0, 0.3, 0.7):
    st, ch = select_changes(fr)
    sel_ok = sel_ok and len(ch) >= 25 and all(0.5 <= (c - st) % 1 < 0.55 for c in ch[1:])
ok(sel_ok, "select screen: with a fake clock the shown RUNNING time (fmt_took) changes at the moment fmt_took rounds up (timestamp + n + 0.5), also when the snapshot read falls in between")
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
hour_ok = True
for fr in (0.0, 0.3, 0.77):
    st, ch, wk = hour_changes(fr)
    hour_ok = hour_ok and wk <= 75 and all(0.0 <= (c - st + 0.5) % 60 < 0.3 for c in ch if c - st > 3599) and len([c for c in ch if c - st > 3599]) == 62
ok(hour_ok, "time ticks: from 3600 s on the shown value (fmt_took, minutes only) is redrawn within 0.3 s after it turns and the wake comes once a minute, not once a second")
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
def sel_open(win_w, select=True):
    calls.clear()
    sidebars.tmux = lambda *a: calls.append(a) or (win_w if a[0] == "display-message" else "%1 1 s r\n" if a[0] == "list-panes" else "%9\n" if a[0] == "new-pane" else "")
    sidebars.open_report_pane("@1", "", select)
    sidebars.tmux = real_tmux
    return open_cmd()
c = sel_open("200")
ok(c[c.index("-x" + str(sidebars.SELECT_PANE_COLS)) + 1] == "-y80%" and f"-X{(200 - sidebars.SELECT_PANE_COLS) // 2}" in c and "-Y10%" in c,
   "select pane: in a 200-column window it is SELECT_PANE_COLS wide, centred, 80% high from 10%")
c = sel_open("60")
ok("-x60" in c and "-X0" in c, "select pane: in a 60-column window it is no wider than the window")
c = sel_open("", select=False)
ok(c[1:5] == ("-x80%", "-y80%", "-X10%", "-Y10%"), "report pane: an unreadable window width keeps -x80% -y80% -X10% -Y10%")
c = sel_open("400", select=False)
ok(c[1:5] == (f"-x{sidebars.REPORT_PANE_COLS}", "-y80%", f"-X{(400 - sidebars.REPORT_PANE_COLS) // 2}", "-Y10%"),
   "report pane: in a 400-column window it is REPORT_PANE_COLS wide, centred, 80% high from 10%")
c = sel_open("100", select=False)
ok(c[1:5] == ("-x80", "-y80%", "-X10", "-Y10%"), "report pane: in a 100-column window it is 80% of the window, centred")
c = sel_open("n/a")
ok("-x80%" in c and "-X10%" in c, "select pane: an unreadable window width keeps the 80% / 10% size")
def fit(flag, select, new=True, win_w=200):
    calls.clear()
    sidebars._new_pane = new
    sidebars.tmux = lambda *a: calls.append(a) or (f"{flag} {win_w} 50" if a[0] == "display-message" else "")
    sidebars.fit_report_pane("%9", select)
    sidebars.tmux = real_tmux
    return [c for c in calls if c[0] != "display-message"]
ok(fit("1", True) == [("resize-pane", "-t", "%9", "-x", str(sidebars.SELECT_PANE_COLS), "-y", "40", ";", "move-pane", "-t", "%9", "-X", str((200 - sidebars.SELECT_PANE_COLS) // 2), "-Y", "5")],
   "fit pane: a floating pane is resized and moved to the select screen's size and place")
ok(fit("1", False, win_w=100) == [("resize-pane", "-t", "%9", "-x", "80", "-y", "40", ";", "move-pane", "-t", "%9", "-X", "10", "-Y", "5")],
   "fit pane: in a 100-column window the report page's pane is 80% wide, centred, 80% high from 10%")
ok(sidebars.report_span(400) == (sidebars.REPORT_PANE_COLS, (400 - sidebars.REPORT_PANE_COLS) // 2) and sidebars.report_span(100) == (80, 10),
   "report span: REPORT_PANE_COLS wide and centred in a wide window, 80% of a narrow one")
ok(fit("1", False, win_w=400) == [("resize-pane", "-t", "%9", "-x", str(sidebars.REPORT_PANE_COLS), "-y", "40", ";", "move-pane", "-t", "%9", "-X", str((400 - sidebars.REPORT_PANE_COLS) // 2), "-Y", "5")],
   "fit pane: in a 400-column window the report page's pane is REPORT_PANE_COLS wide, centred")
right = sidebars.REPORT_PANE_COLS - 1 - ui.SPLIT_SIDE_COLS - ui.SPLIT_GAP
ok(abs(ui.banner_cells(sidebars.REPORT_PANE_COLS - 1, 0.5)[0] - right) <= 1,
   "report pane: at REPORT_PANE_COLS and cell ratio 0.5 the banner is as wide as the right column")
ok(fit("0", True) == [] and fit("1", True, new=False) == [], "fit pane: a pane that is not floating, or tmux without new-pane, is left alone")
sidebars._new_pane = None
fit_calls = []
real_fit, real_rs, real_rr = ui.fit_report_pane, ui.run_select, ui.run_report
ui.fit_report_pane = lambda p, s: fit_calls.append(("fit", p, s))
ui.run_select = lambda p=None, f=None: fit_calls.append(("select", p)) or ("%1" if p is None else None)
ui.run_report = lambda p, f=None, back=False: fit_calls.append(("report", p)) or "%1"
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
from party_hud import collect, ui
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
        time.sleep(hold)
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
ui.run_select = lambda sel=None, fixture=None: print("TRACE_SELECT", sel, flush=True) or _rs(sel, fixture)
ui.run_report = lambda pane=None, fixture=None, back=False: print("TRACE_REPORT", pane, back, flush=True) or _rr(pane, fixture, back)
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
an = report_session([b"n", b"q"], rows=16, lines=12, src=anim_src)
ok("report 2/3" in an and an.count("\x1b[H") == 4 and "EXITED" in an, "report pane: n during the animation changes page at once, and the new page starts its own animation")
art_inject = """ui.report_queue = lambda towns, pane=None, window=None: [("A", {"pane": "%%1", "round": 0})]
ui.art_supported = lambda *a: True
ui.load_art = lambda: {"k": 1}
ui.REPORT_ART_SETTLE = 0
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
ui.REPORT_ART_SETTLE = 0
ui.report_images = lambda *a: ""
ui.report_image_plan = lambda *a: [(7, 10, 5)]
ui.portrait_id = lambda a: -1
ui.report_parts = lambda a, sq, rep, peek, width, *r: ([], [("L" + str(n)).ljust(width) for n in range(80)])
ui.run_report"""
fp = report_session([b"n", b"q"], src=child.replace("ui.run_report", first_inject, 1))
ok(fp.count("a=d,d=I,i=7") == 2 and fp.index("a=d,d=I,i=7") < fp.index("\x1b[H") < fp.rindex("a=d,d=I,i=7"),
   "report pane: the first frame is written with a delete of the unsent image id, and n does not delete it again")
live_inject = first_inject.replace("ui.report_image_plan = lambda *a: [(7, 10, 5)]", "ui.report_image_plan = lambda a, final, *r: [(7 if final else 8, 10, 5)]").replace(
    "ui.run_report", "ui.LIVE_REFRESH = 0.2\nui.report_for = lambda a: {'live': True, 'text': 'x', 'start': None, 'end': 2}\nui.refresh_live = lambda q, i: {'text': 'done', 'start': 1, 'end': 3}\nui.run_report", 1)
lv = report_session([b"q"], draws=[2], src=child.replace("ui.run_report", live_inject, 1))
ok("a=d,d=I,i=7" in lv and lv.index("a=d,d=I,i=7") > lv.index("\x1b[H") and lv.index("a=d,d=I,i=7") < lv.rindex("\x1b[H"),
   "report pane: when the in-progress page turns into the final report, the new banner id is deleted with the next frame, as for a new page")
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
ok("a=d,d=I,i=7" in ex[ex.index("\x1b[H"):] and ex.rindex("a=d,d=I,i=7") < ex.rindex("\x1b[?1049l") and "a=d,d=I,i=-1" not in ex[ex.index("\x1b[H"):],
   "report pane: on exit the images it sent are deleted before leaving the alternate screen, the sidebar portrait is not")
scr = report_session([b"G", b"q"])
ok("L59" in scr[scr.index("\x1b[H", scr.index("\x1b[J")):] and "L59" not in once, "report pane: G redraws the bottom rows in place")
fit = report_session([b"j", b"q"], rows=40, lines=3, draws=[1, 1])
ok(fit.count("\x1b[H") == 1, "report pane: a report that fits the pane does not redraw on j")
ok("EXITED" in twice, "report pane: q ends the program, which closes the pane")
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
ok(new["%21"]["hp"] is None and not new["%21"]["fresh"] and re.search(r"agy.*\n.*· idle.*\n.*HP +-- +│\n╰", nl) and "SP --" not in nl,
   "Other agents with unreadable context: HP stays --, no SP row")
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
with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
    um = lambda tid, t: json.dumps({"type": "event_msg", "payload": {"type": "item_completed", "turn_id": tid, "item": {"type": "UserMessage", "content": [{"type": "text", "text": t}]}}}) + "\n"
    ce = lambda tid: json.dumps({"type": "event_msg", "payload": {"type": "item_completed", "turn_id": tid, "item": {"type": "CommandExecution"}}}) + "\n"
    ts = lambda tid: json.dumps({"type": "event_msg", "payload": {"type": "task_started", "turn_id": tid}}) + "\n"
    f.write(ts("t1") + um("t1", "old ask") + ce("t1") + ts("t2") + um("t2", " new ask ") + ce("t2") + ce("t2"))
    f.write('{"type":"event_msg","payload":{"type":"task_complete","turn_id":"t2","last_agent_message":"x","started_at":1,"completed_at":2}}\n')
ok(collect.codex_task(f.name) == {"ask": "new ask", "files": 0, "cmds": 2, "agents": 0} and collect.codex_task("/nope") is None,
   "codex task: the finished turn's UserMessage text and its CommandExecution count (item_completed events)")
with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
    f.write(ts("t9") + um("t9", "long turn") + ce("t9") + ("x" * 1000 + "\n") * 300 + ce("t9") + ce("t9"))
    f.write('{"type":"event_msg","payload":{"type":"task_complete","turn_id":"t9","last_agent_message":"x","started_at":1,"completed_at":2}}\n')
ok(collect.codex_task(f.name) is None, "codex task: turn started before the tail that is read -> None, not a short count")

with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
    fc = lambda tid, name, inp: json.dumps({"type": "response_item", "payload": {"type": "custom_tool_call", "name": name, "input": inp}}) + "\n"
    am = lambda tid, t: json.dumps({"type": "event_msg", "payload": {"type": "item_completed", "turn_id": tid, "item": {"type": "AgentMessage", "content": [{"type": "Text", "text": t}]}}}) + "\n"
    f.write(ts("t1") + um("t1", "old ask") + '{"type":"event_msg","payload":{"type":"task_complete","turn_id":"t1","last_agent_message":"earlier answer","started_at":10,"completed_at":20}}\n')
    f.write('{"type":"event_msg","payload":{"type":"task_started","turn_id":"t2","started_at":500}}\n')
    f.write(um("t2", "now ask") + fc("t2", "exec", "\nrg -n foo src\nmore") + ce("t2") + am("t2", "a\nb\nc") + fc("t2", "exec", "ls -la"))
cl = collect.codex_live(f.name)
ok(cl == {"live": True, "task": {"ask": "now ask", "files": 0, "cmds": 1, "agents": 0}, "start": 500, "end": None,
          "tool": "exec: ls -la", "said": "a\nb\nc", "prev": {"text": "earlier answer", "start": 10, "end": 20}},
   "codex live: turn without task_complete -> ask, start, newest tool row, newest message, previous turn's report")
ok(collect.codex_live(g.name) is None and collect.codex_live("/nope") is None, "codex live: newest turn event is task_complete (or no file) -> None")

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
edit = lambda t, name, **inp: rec("assistant", t, [{"type": "tool_use", "id": f"u{t}", "name": name, "input": inp}])
task_log = transcript(rec("user", 0, "old"), rec("assistant", 1, [text("ok")]),
    rec("user", 2, [text("  fix\nthe thing  ")]), edit(3, "Edit", file_path="/a.py"), edit(3, "Write", file_path="/a.py"),
    edit(4, "MultiEdit", file_path="/b.py"), edit(4, "Bash", command="ls"), edit(5, "Bash", command="pwd"), edit(5, "Task", prompt="x"),
    rec("user", 5, [{"type": "tool_result", "tool_use_id": "x"}]), edit(6, "Agent", prompt="y"),
    edit(6, "Edit", file_path="/side.py", ), rec("assistant", 7, [text("done")]),
    rec("user", 8, "<bash-input>ls</bash-input>"))
task_log2 = transcript(*[({**r_, "isSidechain": True} if r_["message"]["content"][0].get("input", {}).get("file_path") == "/side.py" else r_) if isinstance(r_["message"]["content"], list) else r_ for r_ in map(json.loads, open(task_log))])
ok(collect.claude_task(task_log2) == {"ask": "fix\nthe thing", "files": ["/a.py", "/b.py"], "cmds": 2, "agents": 2}
   and collect.claude_task("/nope")["ask"] is None,
   "claude task: prompt of the answered turn, distinct edited files, Bash, Agent and Task counts (sidechain and older turns skipped)")
inj = lambda t, text_, **kw: rec("user", t, text_, **kw)
noisy = transcript(rec("user", 0, "real ask"), edit(1, "Edit", file_path="/a.py"), rec("assistant", 2, [text("ok")]),
    inj(3, "<task-notification>\n<task-id>x</task-id>", origin={"kind": "task-notification"}),
    edit(4, "Bash", command="ls"), edit(4, "Edit", file_path="/b.py"),
    inj(5, "<system-reminder>\nnote\n</system-reminder>"), inj(5, "<local-command-stdout>x</local-command-stdout>"),
    inj(5, "<task-notification>y"), inj(5, "peer msg", origin={"kind": "peer"}),
    rec("assistant", 6, [text("done")]))
ok(collect.claude_task(noisy) == {"ask": "real ask", "files": ["/a.py", "/b.py"], "cmds": 1, "agents": 0},
   "claude task: injected user records (origin not human, task-notification, local-command, system-reminder only) are not the prompt; their tool calls still count")
slash = transcript(rec("user", 0, "before"), rec("assistant", 1, [text("a")]),
    rec("user", 2, "<command-message>sdlc-run</command-message>\n<command-name>/sdlc-run</command-name>\n<command-args>game-feel 025</command-args>", origin={"kind": "human"}),
    rec("user", 2, "Base directory for this skill: /x\n" + "skill text\n" * 50, isMeta=True),
    rec("user", 3, "<system-reminder>\ninjected\n</system-reminder>\n/real typed words"),
    edit(4, "Edit", file_path="/c.py"), rec("assistant", 5, [text("done")]))
slash2 = transcript(*list(map(json.loads, open(slash)))[:-3], rec("assistant", 5, [text("done")]))
ok(collect.claude_task(slash)["ask"] == "/real typed words" and collect.claude_task(slash2)["ask"] == "/sdlc-run game-feel 025"
   and collect.claude_typed({}, "<system-reminder>only</system-reminder>") is None,
   "claude task: a slash command shows as /name args (no skill text); system-reminder blocks are cut and an empty remainder is skipped")
pb = lambda body, i="cd54": f'<pasted_content id="{i}">\n{body}\n</pasted_content id="{i}">'
ok(collect.claude_typed({}, "[Image #1] it broke\n\n\n" + pb("❯❯ bash x\nok")) == "[Image #1] it broke"
   and collect.claude_typed({}, "\n\n" + pb("❯❯ printf\n57") + "\n\n\nnew window is fine") == "new window is fine",
   "claude typed: text typed outside a pasted_content block is the ask; the block is dropped")
ok(collect.claude_typed({}, pb("❯❯ printf\n57")) == "❯❯ printf\n57",
   "claude typed: only a paste -> the pasted text without the pasted_content markers")
ok(collect.claude_typed({}, pb("one", "a") + "\nmiddle\n" + pb("two", "b")) == "middle",
   "claude typed: two pastes with typed words between -> only the words")
ok(collect.claude_typed({}, 'hi\n<pasted_content id="z">\nbody') == "hi\nbody"
   and "pasted_content" not in collect.claude_typed({}, '<pasted_content id="z">\nbody'),
   "claude typed: an unclosed pasted_content block loses only its opening marker")
ok(collect.claude_typed({}, pb('see </pasted_content id="q"> inside') + "\ntyped") == "typed"
   and collect.claude_typed({}, pb('a </pasted_content id="q"> b')) == 'a </pasted_content id="q"> b'
   and "pasted_content" not in collect.claude_typed({}, pb("x") + '\ntyped\n<pasted_content id="z">\nrest'),
   "claude typed: a closing-marker lookalike inside a paste does not end it; a stray opening marker beside a full block is dropped")
edit_ = lambda t, name, **inp: rec("assistant", t, [{"type": "tool_use", "id": "z", "name": name, "input": inp}])
liveq = transcript(rec("user", 0, "before"), rec("assistant", 1, [text("previous answer")]),
    rec("user", 2, "fix the thing"), rec("assistant", 3, [text("working on it\nline2")]),
    edit_(4, "Edit", file_path="/a.py"), rec("user", 5, [{"type": "tool_result", "tool_use_id": "z"}]),
    edit_(6, "Bash", command="rg -n foo\nsecond line", description="search"))
cl = collect.claude_live(liveq)
ok(cl == {"live": True, "task": {"ask": "fix the thing", "files": ["/a.py"], "cmds": 1, "agents": 0},
          "start": t0 + 120, "end": None, "tool": "Bash: rg -n foo", "said": "working on it\nline2",
          "prev": {"text": "previous answer", "start": t0, "end": t0 + 60}},
   "claude live: turn without a final answer -> ask, start, newest tool row, newest text, previous turn's report")
def bulk(t, mb):
    use = {"type": "tool_use", "id": "z", "name": "Bash", "input": {"command": "ls"}}
    res = {"type": "tool_result", "tool_use_id": "z", "content": "o" * 100000}
    return [r_ for _ in range(int(mb * 1024 * 1024 / 100000) + 1) for r_ in (rec("assistant", t, [use]), rec("user", t, [res]))]
def append(path, *recs):
    with open(path, "a") as f:
        for r_ in recs:
            f.write(json.dumps(r_) + "\n")
searches = []
search_orig = collect._search_long_turn
collect._search_long_turn = lambda f, lo: (searches.append(lo), search_orig(f, lo))[1]
longlog = transcript(rec("user", 0, "before"), rec("assistant", 1, [text("previous answer")]),
    rec("user", 2, "long ask"), *bulk(3, 1.3))
ll = collect.claude_live(longlog)
ok(ll["start"] == t0 + 120 and ll["task"]["ask"] == "long ask" and ll["task"]["files"] == [] and ll["tool"] == "Bash: ls"
   and ll["prev"] == {"text": "previous answer", "start": t0, "end": t0 + 60},
   "claude live: a turn that began before LIVE_TAIL still has ask, start and prev (files, cmds and agents count the tail only)")
append(longlog, rec("assistant", 20, [text("more")]), *bulk(21, 0.1))
ll2 = collect.claude_live(longlog)
ok(len(searches) == 1 and (ll2["start"], ll2["task"]["ask"], ll2["prev"]) == (ll["start"], ll["task"]["ask"], ll["prev"]) and ll2["said"] == "more",
   "claude live: the same log read again as the same turn is not searched again")
append(longlog, rec("user", 30, "second ask"), rec("assistant", 31, [text("on it")]))
ll3 = collect.claude_live(longlog)
n_ = len(searches)
append(longlog, rec("user", 40, "third ask"), *bulk(41, 1.3))
ll4 = collect.claude_live(longlog)
ok(ll3["start"] == t0 + 1800 and ll3["task"]["ask"] == "second ask" and n_ == 1 and len(searches) == 2
   and ll4["start"] == t0 + 2400 and ll4["task"]["ask"] == "third ask" and ll4["prev"]["text"] == "on it",
   "claude live: a new prompt in the tail replaces the remembered turn; a new turn longer than the tail since the last read is searched again")
other = transcript(rec("user", 0, "other ask"), *bulk(1, 1.3))
os.replace(other, longlog)
ok(collect.claude_live(longlog)["task"]["ask"] == "other ask",
   "claude live: a log replaced by another file is not read as the remembered turn")
n_ = len(searches)
with open(longlog, "w") as f:
    for r_ in [rec("user", 0, "rewritten ask"), *bulk(1, 1.4)]:
        f.write(json.dumps(r_) + "\n")
ok(collect.claude_live(longlog)["task"]["ask"] == "rewritten ask" and len(searches) == n_ + 1,
   "claude live: a log rewritten in place (same inode, other content) is searched again")
cut = transcript(rec("user", 0, "cut ask"), *bulk(1, 1.3))
collect.claude_live(cut)
with open(cut, "r+") as f:
    f.truncate(os.path.getsize(cut) - 100000)
n_ = len(searches)
ok(collect.claude_live(cut)["task"]["ask"] == "cut ask" and len(searches) == n_ + 1,
   "claude live: a log cut shorter is searched again")
edge = []
for d in (-1, 0, 1):
    el = transcript(rec("user", 0, "OLD"), *bulk(1, 1.3))
    collect.claude_live(el)
    prompt = json.dumps(rec("user", 50, "EDGE new")) + "\n"
    pad = lambda n: json.dumps(rec("user", 51, [{"type": "tool_result", "tool_use_id": "z", "content": "o" * n}])) + "\n"
    room = collect.LIVE_TAIL + d - len(prompt) - len(pad(0))
    with open(el, "a") as f:
        f.write(prompt + pad(room))
    edge.append(collect.claude_live(el)["task"].get("ask"))
    for _ in range(2):
        append(el, *bulk(52, 0.1))
        edge.append(collect.claude_live(el)["task"].get("ask"))
ok(edge == ["EDGE new"] * 9,
   f"claude live: a new prompt first in what the file grew by LIVE_TAIL - 1, LIVE_TAIL and LIVE_TAIL + 1 bytes is the turn, not the remembered one, also on later reads ({edge})")
mid = transcript(rec("user", 0, "earlier"), rec("assistant", 1, [text("a")]),
    rec("user", 2, "ask with a lookalike", meta={"type": "tool_result"}), *bulk(3, 1.3))
ok(collect.claude_live(mid)["task"]["ask"] == "ask with a lookalike",
   "claude live: a prompt record that has a tool_result lookalike in another field is still the prompt")
lookback = collect.LONG_TURN_LOOKBACK
collect.LONG_TURN_LOOKBACK = 64 * 1024
far = transcript(rec("user", 0, "far ask"), *bulk(1, 1.3))
fl = collect.claude_live(far)
collect.LONG_TURN_LOOKBACK = lookback
ok(fl["start"] is None and fl["task"] == {} and fl["prev"] is None and fl["tool"] == "Bash: ls",
   "claude live: a prompt further back than LONG_TURN_LOOKBACK is not found, the result is the tail-only one")
n_ = len(searches)
ok(collect.claude_live(liveq) == cl and len(searches) == n_,
   "claude live: a turn that begins inside the tail gives the same result and never searches")
collect._search_long_turn = search_orig
ok(collect.report_for({"kind": "claude", "transcript": liveq, "status": "working"})["live"] is True
   and collect.report_for({"kind": "claude", "transcript": liveq}) is None
   and collect.report_for({"kind": "claude", "transcript": transcript(*turn), "status": "idle"})["text"].startswith("## 結果"),
   "report_for: working -> live page; any other status keeps the finished-report path")
repo = tempfile.mkdtemp()
os.makedirs(os.path.join(repo, ".git", "refs"))
os.makedirs(os.path.join(repo, "src", "deep"))
with open(os.path.join(repo, ".git", "HEAD"), "w") as f:
    f.write("ref: refs/heads/feat/x\n")
wt = tempfile.mkdtemp()
os.makedirs(os.path.join(repo, ".git", "worktrees", "wt1"))
with open(os.path.join(repo, ".git", "worktrees", "wt1", "HEAD"), "w") as f:
    f.write("ref: refs/heads/wt-branch\n")
with open(os.path.join(wt, ".git"), "w") as f:
    f.write("gitdir: " + os.path.join(repo, ".git", "worktrees", "wt1") + "\n")
det = tempfile.mkdtemp()
bad = tempfile.mkdtemp()
os.makedirs(os.path.join(bad, ".git"))
os.makedirs(os.path.join(det, ".git"))
with open(os.path.join(det, ".git", "HEAD"), "w") as f:
    f.write("0123456789abcdef0123456789abcdef01234567\n")
with open(os.path.join(bad, ".git", "HEAD"), "w") as f:
    f.write("ref: refs/heads/a\tb\x1b]52;c;ZXZpbA==\x07\n")
tags = tempfile.mkdtemp()
os.makedirs(os.path.join(tags, ".git"))
with open(os.path.join(tags, ".git", "HEAD"), "w") as f:
    f.write("ref: refs/remotes/o/x\n")
ok(collect.git_branch(bad) == "ab]52;c;ZXZpbA==" and collect.git_branch(tags) is None,
   "git branch: control characters are dropped from the name; a ref outside refs/heads -> None")
ok(collect.git_branch(os.path.join(repo, "src", "deep")) == "feat/x" and collect.git_branch(wt) == "wt-branch"
   and collect.git_branch(det) == "0123456" and collect.git_branch("/nope/none") is None,
   "git branch: read from .git/HEAD (repo, parent directory), from a worktree's gitdir file, short sha when detached, None outside a repo")
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
ok(collect.report_for({"kind": "claude", "transcript": sess})["subagents"] == [s for s in fin if s["desc"] == "No log text"]
   and collect.report_for({"kind": "claude", "transcript": sess})["text"].startswith("## 結果")
   and collect.report_for({"kind": "claude", "transcript": transcript(*turn)})["subagents"] == [],
   "report_for: main report carries the subagents finished in its turn; no subagents/ directory -> empty list, same report")
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
os.utime(os.path.join(sdir, "agent-d.jsonl"), (t0, t0))
ok([s["desc"] for s in collect.finished_subagents(sess, t0 + 120)] == ["Handback"]
   and [s["desc"] for s in collect.report_for({"kind": "claude", "transcript": sess})["subagents"]] == ["Handback"],
   "subagents: only those that ended in the report's turn (report end, else log mtime, at or after the prompt)")
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
agy_menu = open(os.path.join(os.path.dirname(sys.argv[1]), "tests", "fixtures", "agy-permission.txt"), encoding="utf-8").read()
agy_done = agy_menu[:agy_menu.index("Command\n")]
menu_panes = [dict({f: "" for f in collect.TMUX_FIELDS}, pane_id=f"%{i}", pane_pid=str(i), pane_current_command=cmd, session_name="s", session_attached="1",
                   window_active="1", window_id="@1", window_panes="2") for i, cmd in ((1, "agy"), (2, "grok"))]
real4 = (collect.read_tmux, collect.read_claude_sessions, collect.tmux)
collect.read_tmux, collect.read_claude_sessions = (lambda: menu_panes), (lambda: {})
status_of = {}
for label, screen in (("menu", agy_menu), ("no menu", agy_done)):
    collect.tmux, collect.PARTY_DIR = (lambda *args, s=screen: s), tempfile.mkdtemp()
    status_of[label] = {a["kind"]: a["status"] for t in collect.collect()["towns"] for a in t["agents"]}
collect.read_tmux, collect.read_claude_sessions, collect.tmux = real4
ok(status_of["menu"]["agy"] == "waiting", "agy permission menu on screen -> waiting")
ok(status_of["no menu"]["agy"] == "idle", "agy screen without the permission menu -> not waiting")
ok(status_of["menu"]["grok"] == "idle", "grok pane showing the agy permission menu -> unaffected")
busy_panes = [dict({f: "" for f in collect.TMUX_FIELDS}, pane_id=f"%{i}", pane_pid=str(i), pane_current_command=cmd, session_name="s", session_attached="1",
                   window_active="1", window_id="@1", window_panes="3") for i, cmd in ((1, "agy"), (2, "grok"), (3, "codex"))]
collect.read_tmux, collect.read_claude_sessions = (lambda: busy_panes), (lambda: {})
collect.PARTY_DIR = tempfile.mkdtemp()
for n in (100, 101):
    collect.tmux = lambda *args, n=n: agy_menu + f"tick {n}"
    busy = {a["kind"]: a["status"] for t in collect.collect(now=n)["towns"] for a in t["agents"]}
collect.read_tmux, collect.read_claude_sessions, collect.tmux = real4
ok(busy == {"agy": "waiting", "grok": "working", "codex": "working"}, "changing screen with the menu text: agy waiting, others still working")
def rollout(*events):
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as rf:
        rf.writelines('{"type":"event_msg","payload":{"type":"%s"}}\n' % e for e in events)
    return rf.name
done_f, started_f, empty_f = rollout("task_started", "task_complete"), rollout("task_complete", "task_started"), rollout("token_count")
ok(collect.codex_turn_done(done_f) and not collect.codex_turn_done(started_f) and not collect.codex_turn_done(empty_f)
   and not collect.codex_turn_done("/nope"), "codex turn done: only when the newest turn event is task_complete")
cx_panes = [dict({f: "" for f in collect.TMUX_FIELDS}, pane_id="%1", pane_pid="1", pane_current_command="codex", session_name="s",
                 session_attached="1", window_active="1", window_id="@1", window_panes="1")]
real5 = (collect.read_tmux, collect.read_claude_sessions, collect.codex_rollout, collect.screen_changed)
collect.read_tmux, collect.read_claude_sessions = (lambda: cx_panes), (lambda: {})
def cx_status(path, changed=True):
    collect.codex_rollout, collect.screen_changed = (lambda *a: path), (lambda ps, now: {p: changed for p in ps})
    return [a for t in collect.collect()["towns"] for a in t["agents"]][0]["status"]
cx = (cx_status(done_f), cx_status(started_f), cx_status(None), cx_status(empty_f), cx_status(done_f, False))
ok(cx[0] != "working", "codex: newest event task_complete and screen changed -> not working")
ok(cx[1] == "working", "codex: newest event task_started and screen changed -> working")
ok(cx[2] == "working" and cx[3] == "working", "codex: no rollout or no turn event in the tail, screen changed -> working")
ok(cx[4] == "idle", "codex: task_complete and screen unchanged -> idle")
towns_cx = []
for changed in (True, False):
    cx_status(done_f, changed)
    towns_cx.append([{"agents": [dict(a, focus=False) for t in collect.collect()["towns"] for a in t["agents"]]}])
collect.read_tmux, collect.read_claude_sessions, collect.codex_rollout, collect.screen_changed = real5
st_cx = {"%1": {"status": "idle", "unseen": False, "round": 2}}
for ts in towns_cx:
    st_cx = collect.mark_unseen(ts, st_cx)
ok(st_cx["%1"]["round"] == 2 and towns_cx[1][0]["agents"][0]["status"] == "idle",
   "codex: redraw after task_complete (changed, then unchanged) does not start a new round")
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
ok(imgs and len(imgs) == 56 and imgs[art.select_banner_id(7)] == (b"PNG" + bytes([51 + 3]),) and imgs[art.label_id("running")] == (b"PNG" + bytes([50]),) and imgs[art.banner_id("waiting", True, False, 7)] == (b"PNG" + bytes([28 + 2 * 4 + 1]),) and imgs[art.BIG_PORTRAIT_ID + 3] == (b"PNG\x17",) and imgs[art.PORTRAIT_ID + 2] == (b"PNG\x02", 6, 3) and imgs[art.CREST_ID + 7] == (b"PNG\x0f", 4, 2)
   and imgs[art.BANNER_ID + 2] == (b"PNG\x12",),
   "All 56 images present: portraits 6x3 cells, crests 4x2 cells, 4 banners and the select banner in 5 ratios, 8 big portraits and 7 heading labels (no cell size stored)")
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
   and n30b.endswith("HP 890k/1.2M  Opus"),
   "Narrow sidebar: the HP value (left/max) stays whole and the model badge yields; 1.0M as 1M; the max is dropped only if the row is still too narrow")
n17, n13 = (re.sub(r"\033\[[0-9;:]*m", "", render.stat_rows(nar2, w)[0]) for w in (17, 11))
ok(n17.rstrip().endswith("HP 890k/1.2M") and "Op" not in n17 and common.cw(n17) == 17 and n13.endswith("890k") and "/" not in n13 and common.cw(n13) == 11,
   "Narrow sidebar: badge dropped (no stub) before the value is cut; max dropped only when the row cannot hold it")
long_a = dict(nar2, name="party-hud-long-name", cls=0, kind="claude", status="working", sp=(600.0, 3600))
nc = [re.sub(r"\033\[[0-9;:]*m", "", l) for l in render.card(long_a, 28, True, True)]
ok(all(w(l) == 28 for l in nc) and "890k/1.2M" in nc[2] and "…" in nc[1] and "party-hud-long-name" not in nc[1],
   "Narrow art card: name truncated with … while the HP value stays whole; every line exactly 28 wide")
text = render.render(towns, 33, "%1", hints="sidebar") + render.render(towns, 33, "%1", art=True) + render.render(towns, 33, "%1", ["x"], "popup")
en_lv = {"live": True, "text": "", "start": 1000, "end": None, "tool": "Bash: ls", "said": "thinking",
         "prev": {"text": "## Earlier\nold report", "start": 1, "end": 2}, "task": {"ask": "do it", "files": [], "cmds": 2, "agents": 0, "dir": "~/x", "branch": "main", "cwd": "/x"}}
en_rep = {"text": "## Result\nall done", "start": 100, "end": 860}
en_sub = {"type": "executor", "desc": "Execute ticket 001", "text": "## Result\nsub said hi"}
en_busy = dict(done, summons=[{"type": "executor", "desc": "Branch"}, {"type": "executor", "desc": "Branch 2"}])
en_pages = [render.render_report(dict(done, status="working"), "Studio", en_lv, [], 60, now=1723),
            render.render_report(dict(done, status="working", summons=[{"type": "executor", "desc": "Branch"}]), "Studio", en_lv, [], 60, now=1723),
            render.render_report(en_busy, "Studio", dict(en_rep, subagents=[en_sub]), [], 60),
            render.render_report(en_busy, "Studio", en_rep, [], 60, art=True, banner=(40, 5)),
            render.render_report(dict(done, status="working", summons=[{"type": "executor", "desc": "Branch"}]), "Studio", en_lv, [], 150, art=True, banner=(118, 15), portrait=(24, 14), now=1723),
            render.render_report(en_busy, "Studio", en_rep, [], 150, art=True, banner=(118, 15), portrait=(24, 14))]
text += "".join(en_pages)
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
ts = [{"agents": [{"pane": "%60", "status": "idle", "focus": True}, {"pane": "%61", "status": "idle", "focus": False, "lead": "%60"},
                  {"pane": "%62", "status": "idle", "focus": False}]}]
collect.mark_unseen(ts, {"%61": {"status": "working", "unseen": False}, "%62": {"status": "working", "unseen": False}})
ok([a["pane"] for a in ts[0]["agents"]] == ["%62", "%60", "%61"] and ts[0]["agents"][2]["status"] == "done",
   "Unseen done: a summoned member that finishes stays right under its lead; other done members move up")
def mr(raw, state, seen=None, focus=False):
    ts = [{"agents": [{"pane": "%50", "status": raw, "focus": focus}]}]
    new_state = collect.mark_unseen(ts, state, seen)
    return ts[0]["agents"][0], new_state
a1, r1 = mr("idle", {"%50": {"status": "working", "unseen": False, "round": 4}})
a2, r2 = mr("idle", r1)
a3, r3 = mr("working", r2)
a4, r4 = mr("sleep", r3)
ok(mr("idle", {})[0]["round"] == 0 and a1["round"] == 5 and a2["round"] == 5 and a3["round"] == 5 and a4["round"] == 6 and r4["%50"]["round"] == 6,
   "Round: first seen is 0, +1 each time a member goes working -> idle/sleep, unchanged while idle or working")
ok(mr("idle", {"%50": {"status": "working", "unseen": False}})[0]["status"] == "done" and mr("idle", {"%50": {"status": "working", "unseen": False}})[0]["round"] == 1,
   "Round: an unseen.json written before rounds existed reads as round 0")
wk = {"%50": {"status": "working", "unseen": False, "round": 2}}
ok(mr("idle", wk, {"%50": 2})[0]["status"] == "done" and mr("idle", wk, {"%50": 3})[0]["status"] == "idle"
   and mr("idle", wk, {"%50": 9})[0]["status"] == "idle" and mr("idle", wk, {"%51": 9})[0]["status"] == "done",
   "Seen: a round read (seen >= round) is not done; a newer round (seen < round) or another member's seen is")
ok(mr("idle", {"%50": {"status": "idle", "unseen": True, "round": 3}}, {"%50": 3})[0]["status"] == "idle",
   "Seen: reading the report of a round already done clears the done on the next collection")
import shutil, tempfile
collect.PARTY_DIR = sidebars.PARTY_DIR = sd = tempfile.mkdtemp()
ok(collect.read_seen() == {}, "Seen: no seen.json reads as empty")
sidebars.mark_seen("%50", 5)
sidebars.mark_seen("%50", 3)
sidebars.mark_seen("%51", 1)
ok(collect.read_seen() == {"%50": 5, "%51": 1}, "Seen: mark_seen never lowers a value and keeps the other members")
with open(os.path.join(sd, "seen.json"), "w") as f:
    f.write("{broken")
ok(collect.read_seen() == {}, "Seen: a broken seen.json reads as empty")
shutil.rmtree(sd)
gt = [{"agents": [{"pane": "%51", "status": "working", "focus": False}]}]
g1 = collect.mark_unseen(gt, {"%50": {"status": "idle", "unseen": False, "round": 5}}, {"%50": 5})
ok(g1["%50"]["round"] == 5 and not g1["%50"]["unseen"], "Round: a pane missing from a collection keeps its round in the state")
g2 = mr("working", g1, {"%50": 5})[1]
g3 = mr("idle", g2, {"%50": 5})[0]
ok(g3["round"] == 6 and g3["status"] == "done", "Round: a pane that comes back as an agent goes on from its old round, so its next finished round is done")
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
vis2 = {"%2": {"visible": False}, "%3": {"visible": False}, "%4": {"visible": False}}
ring_crew, _ = collect.bell_panes({"%2": "working", "%3": "working", "%4": "working"}, [crew_done, solo_done, crew_wait], vis2)
ok(sorted(ring_crew) == ["%3", "%4"], "crew done: no bell; a plain done member and a waiting crew still ring")
ok(collect.unread_count({"%2": "done", "%3": "done", "%4": "waiting"}, {"%2", "%4"}) == 2
   and collect.unread_count({"%2": "done"}, set()) == 1,
   "crew done: not counted in @party_reports; a waiting crew and a plain done member are")
ok(render.squad_alert([lead_idle, crew_done]) is None and render.squad_alert([lead_idle, crew_done, crew_wait]) == "waiting"
   and render.squad_alert([lead_idle, crew_done, solo_done]) == "done",
   "crew done: squad stays dark; a waiting crew or a plain done member still lights it")
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
crowd = [dict(towns[0], name=f"Sq{k}", agents=[dict(agents[0], pane=f"%{200 + 2 * k + j}", summons=[], focus=False) for j in range(2)]) for k in range(12)]
for use_art in (True, False):
    for k, pane in ((0, "%200"), (11, "%222")):
        cm = []
        cl = strip(render.render(crowd, 33, pane, None, "sidebar", 24, cm, art=use_art)).splitlines()
        ok(len(cl) == 24 and cl[-1].lstrip().startswith("⏎") and sum(l.startswith("╔") for l in cl) == 1 and any(l.startswith("║❯") for l in cl)
           and any(l.startswith("╚") for l in cl) and ("agent", pane) in cm and ("squad", k) in cm,
           f"12 squads at 33x24 (art={use_art}, squad {k}): selected card fully visible with ❯, viewed squad listed, hint row last")
cm = []
cl = strip(render.render(crowd, 33, "%222", None, "sidebar", 24, cm, art=True)).splitlines()
box_end = next(i for i, l in enumerate(cl) if l.startswith("╰"))
shown = {p[1] for p in cm if p and p[0] == "squad"}
ok(re.fullmatch(r"│ *▲ \d+ more *│", cl[1]) and int(cl[1].strip("│ ").split()[1]) == 12 - len(shown) and 11 in shown and 0 not in shown
   and not any("▼" in l for l in cl[:box_end]), "Squads don't fit, last squad viewed: ▲ N more in the frame, N = hidden squads, no ▼")
cm = []
cl = strip(render.render(crowd, 33, "%200", None, "sidebar", 24, cm, art=True)).splitlines()
ok(cm[0] is None and cm[1] == ("squad", 0) and cm[box_end - 1] is None and cm[box_end] is None and "▼" in cl[box_end - 1]
   and all(cm[i] == ("squad", (i - 1) // 2) for i in range(1, box_end - 1)) and int(cl[box_end - 1].strip("│ ").split()[1]) == 12 - len({p[1] for p in cm if p and p[0] == "squad"}),
   "Squads don't fit: the ▼ more row maps to None, squad rows map to their own index")
cm = []
cl = strip(render.render(crowd[:3], 33, "%200", None, "sidebar", 24, cm, art=True)).splitlines()
ok(not any("more" in l for l in cl) and cl[0].startswith("╭─ Squads 3") and cl[7].startswith("╰") and cm[:8] == [None, *[("squad", k // 2) for k in range(6)], None],
   "Squads all fit: no more rows, frame holds every squad row")
sq = strip(render.render(towns, 33, "%1", focus="squad", squad=1)).splitlines()
ok(any(l.startswith("│▌") and "Server" in l for l in sq) and not any(l.startswith("╔") for l in sq),
   "Squad focus (Server): gold bar on the squad row, no card gets the selected gold frame")
pi = ui.parse_input
ok(pi("\x1b[<0;5;7M\x1b[<0;5;7m") == [("click", 6)], "Left mouse press -> click row 7 (release ignored)")
ok(pi("\x1b[<35;5;3M") == [("hover", 2)], "Mouse move -> hover row 3")
ok(pi("\x1b[<64;1;1M\x1b[<65;1;1M") == [("key", "k"), ("key", "j")], "Wheel -> k / j")
ok(pi("\x1b[A\x1b[B") == [("key", "k"), ("key", "j")], "Arrow keys -> k / j")
ok(pi("\x1b") == [("key", "\x1b")] and pi("jv") == [("key", "j"), ("key", "v")], "Lone Esc and plain keys")
ok(pi("\x1b[5~\x1b[6~j") == [("key", "PgUp"), ("key", "PgDn"), ("key", "j")], "PgUp / PgDn -> own keys, no stray ~")
ok(ui.handle_key("PgUp", {"focus": "party", "sel": "%1", "squad": None, "peek": False}, towns, "sidebar") is None,
   "Sidebar ignores PgUp")
ok([ui.report_scroll(k, 5, 20, 10) for k in ["k", "j", "PgUp", "PgDn", "g", "G", "b", " ", "x"]] == [4, 6, 0, 14, 0, 20, 5, 5, 5],
   "Report scroll keys -> offset: k / j one row, PgUp / PgDn a page (height - 1), g / G top / bottom; other keys keep it")
sel_ros, sel_towns = [("Studio", done, False)], [{"name": "Studio", "agents": [done]}]
other_ = dict(done, cls=(done["cls"] + 1) % 4)
sel_art = {art.portrait_id(done): (b"G", 6, 3), art.portrait_id(other_): (b"H", 6, 3)}
plan_a = ui.select_image_plan([done, other_], sel_art)
ok(plan_a == [(art.portrait_id(done), 6, 3), (art.portrait_id(other_), 6, 3)] and ui.select_image_plan([done], None) == [],
   "select images: the plan holds the small portrait of each card on screen with its cells; no art -> empty")
ok(ui.select_images_due(plan_a, {i: (c, r) for i, c, r in plan_a}) == [] and ui.select_images_due(plan_a, {plan_a[0][0]: (7, 3)})[0] == plan_a[0]
   and ui.select_images_due(plan_a, {}) == plan_a,
   "select images: same id at the same cells is not sent again, other cells are, an id never sent is")
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
ok(ui.banner_cells(120, 0.5) == (88, 6, 7) and ui.banner_cells(80, 0.5) == (48, 6, 4),
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
    "popup": "j k J K 1-9 n v ⏎ q Esc P ?",
}
ok(all(set(need[m].split()) <= {t for k, _ in render.HELP[m] for t in k.replace(" / ", " ").split()} for m in need)
   and all(k != "r" for k, _ in render.HELP["popup"]),
   "Key help lists every key of its mode (r only in the sidebar's)")
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
ok(all(t.startswith("next") for m in ("sidebar", "popup") for k, t in render.HELP[m] if k in ("j k", "J K")),
   "Key help: j / J are listed as next and k / K as prev, the way handle_key moves")
ok(all("? keys" in strip(render.hint_line(m, w)) for m, w in (("sidebar", 28), ("popup", 28), ("report", 24)))
   and "q close" in strip(render.hint_line("report", 60)) and "? keys" in strip(render.render(towns, 28, "%1", None, "sidebar")).splitlines()[-1],
   "Key hints keep ? keys at the narrowest widths (sidebar / popup 28, report left column 24)")
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
import party, tempfile, json
fails = []
def ok(cond, msg):
    if not cond: fails.append(msg)
calls, snaps = [], []
real_snapshot = collect.get_snapshot
real_report = collect.report_for
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
prevlog = tempfile.mktemp(suffix=".jsonl")
with open(prevlog, "w") as pf:
    for r_ in [("user", "q1"), ("assistant", [{"type": "text", "text": "answer one"}]), ("user", "q2"),
               ("assistant", [{"type": "tool_use", "id": "x", "name": "Bash", "input": {"command": "ls"}}])]:
        pf.write(json.dumps({"type": r_[0], "timestamp": "2026-11-07T10:00:00Z", "message": {"content": r_[1]}}) + "\n")
run([snap("working", transcript=prevlog)], "%5")
collect.report_for = real_report
ok(collect.report_text("%5") == (0, "answer one\n", ""), "report-text without --wait: a working member -> the previous round's answer, as before the live page")
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
rd = {}
seq_r = [{"towns": [{"agents": [dict(agent("idle"), round=3)]}]}, {"towns": [{"agents": [dict(agent("idle"), round=4)]}]}]
run(seq_r, "%5", read=rd)
ok(rd == {"round": 3}, "report-text: the round handed out is that of the member data the report was read from, not of a later snapshot")
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
    collect.get_snapshot = lambda: {"t": t, "towns": [{"agents": [agent("idle", kind=kind)]}]}
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
screen = "".join(f"line {i}\n\n" for i in range(30))
def run_waiting(t, end, kind="codex"):
    calls.clear()
    collect.get_snapshot = lambda: {"t": t, "towns": [{"agents": [agent("waiting", kind=kind)]}]}
    collect.tmux_run = lambda args, timeout=None: calls.append((tuple(args), timeout)) or (
        (0, "%5\n", "") if args[0] == "display-message" else (0, screen, "") if args[0] == "capture-pane" else (None, "", ""))
    collect.report_for = lambda a: {"text": "old answer", "end": end}
    return collect.report_text("%5", True, 0.3, A)
rc, out, err = run_waiting(A + 3, A - 5)
ok(rc == 7 and out == "".join(f"line {i}\n" for i in range(10, 30)) and "%5 is waiting for input" in err and not waits()
   and (("capture-pane", "-p", "-t", "%5"), None) in calls,
   "report-text --wait --after: a waiting member with no report newer than EPOCH -> 7 at once, stdout the last 20 non-empty screen lines, no wait-for")
ok(run_waiting(A + 1, A - 5)[0] == 3 and waits(), "report-text --wait --after: a waiting member in a snapshot older than EPOCH + 2 s is not reported as waiting yet")
ok(run_waiting(A + 3, A + 2) == (0, "old answer\n", "") and not waits(),
   "report-text --wait --after: a waiting member with a report newer than EPOCH -> 0 as before")
rc, out, err = run_waiting(A + 3, False, "agy")
ok(rc == 7 and out == "".join(f"line {i}\n" for i in range(10, 30)) and "waiting for input" in err and not waits(),
   "report-text --wait --after: a waiting agy (no report time) in a fresh snapshot -> 7 with the screen tail, no wait-for")
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
   and ask_calls[1:] == [(("tmux", "load-buffer", "-b", "party-ask-5", "-"), "hello"),
                         ("tmux", ("paste-buffer", "-p", "-d", "-b", "party-ask-5", "-t", "%5")),
                         ("tmux", ("send-keys", "-t", "%5", "Enter"))],
   "ask: one line -> load-buffer from stdin, paste-buffer -p -d, then Enter; stdout is the send time")
ask_calls.clear()
party.ask("%5", "-Rxyz")
ok(ask_calls[1] == (("tmux", "load-buffer", "-b", "party-ask-5", "-"), "-Rxyz"), "ask: text starting with - goes in on stdin")
ask_calls.clear()
rc, out, err = party.ask("%5", "a\nb")
ok(rc == 0 and ask_calls[1:] == [(("tmux", "load-buffer", "-b", "party-ask-5", "-"), "a\nb"),
                                  ("tmux", ("paste-buffer", "-p", "-d", "-b", "party-ask-5", "-t", "%5")),
                                  ("tmux", ("send-keys", "-t", "%5", "Enter"))],
   "ask: several lines -> load-buffer from stdin, paste-buffer -p -d, then Enter")
ask_calls.clear()
party.tmux_run = lambda args, timeout=None: ask_calls.append(("tmux", tuple(args))) or (
    (0, "%12\n", "") if args[0] == "display-message" else (0, "", ""))
party.get_snapshot = lambda: {"towns": [{"agents": [{**agent("waiting"), "pane": "%12"}]}]}
party.ask("%12", "hi")
ok(ask_calls[1] == (("tmux", "load-buffer", "-b", "party-ask-12", "-"), "hi")
   and ask_calls[2] == ("tmux", ("paste-buffer", "-p", "-d", "-b", "party-ask-12", "-t", "%12")),
   "ask: each target pane gets its own tmux buffer, party-ask-<pane number>")
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
def reports(*agents):
    sp = os.path.join(collect.PARTY_DIR, "snapshot.json")
    if os.path.exists(sp): os.remove(sp)
    collect.collect = lambda *a: {"t": time.time(), "towns": [{"agents": list(agents)}],
                                  "panes": {a["pane"]: {"window": "@1", "sidebar": False, "visible": True} for a in agents}}
    sent.clear()
    real_snapshot()
    return [a[3] for a in sent if a[:3] == ("set-option", "-g", "@party_reports")]
if os.path.exists(bp): os.remove(bp)
lead_p = {"pane": "%1", "status": "idle", "focus": True}
crew_w = {"pane": "%2", "status": "working", "lead": "%1"}
crew_d = {**crew_w, "status": "done"}
s1, s2 = reports(lead_p, crew_w), reports(lead_p, crew_d)
s3, s4 = reports(dict(crew_d, lead="")), reports(dict(crew_d, lead=""))
s5, s6 = reports(lead_p, crew_d), reports(lead_p, crew_d)
ok([s1, s2, s3, s4, s5, s6] == [["0"], [], ["1"], [], ["0"], []],
   "collector: @party_reports ignores a done crew, counts it again once its lead is gone, drops it when a lead returns, and is set only when the number changes")
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
opened = lambda: next(c for c in calls if c[0] in ("split-window", "new-window", "new-session"))
has_crew = [False]
crew_lead = [""]
lead_alive = [True]
FS = collect.FIELD_SEP
def fake_run(args, timeout=None):
    calls.append(tuple(args))
    if args[0] == "display-message" and args[-1] == "#{@party_lead}": return 0, crew_lead[0] + "\n", ""
    if args[0] == "display-message" and args[-1] == "#{pane_id}": return (0, args[3] + "\n", "") if lead_alive[0] else (1, "", "can't find pane\n")
    if args[0] in ("split-window", "new-window", "new-session"): return 0, "%9\n", ""
    if args[0] == "has-session": return (0 if has_crew[0] else 1), "", ""
    if args[0] == "display-message" and args[-1] == FS.join(["#{window_width}", "#{window_height}"]): return 0, f"132{FS}41\n", ""
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
ok(opened() == ("new-window", "-P", "-F", "#{pane_id}", "-c", tmp, "codex"), "summon --window: new-window, --cwd passed to -c")
hashed = os.path.join(tmp, "a#(b)#{c}")
os.makedirs(hashed, exist_ok=True)
calls.clear(); shows[:] = ready
sidebars.summon("codex", hashed, True, 5)
ok(opened()[opened().index("-c") + 1] == os.path.join(tmp, "a##(b)##{c}"), "summon: every # in --cwd is doubled for tmux's format expansion")
calls.clear(); shows[:] = ready
sidebars.summon("codex", tmp, False, 5, True, True)
ok(opened() == ("split-window", "-t", "%1", "-P", "-F", "#{pane_id}", "-c", tmp, "codex -s read-only"), "summon --read-only: codex starts with -s read-only")
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
sys.path.insert(0, os.path.dirname(sys.argv[1])); from party_hud import collect, sidebars
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
    if args[0] == "display-message": return (0, lead[0] + "\n", "") if exists[0] else (1, "", "can't find pane\n")
    return 0, "", ""
sidebars.tmux_run = fake_run
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
ok(rc == 2 and not killed(), "dismiss: pane does not exist -> 2, no kill-pane")
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
sys.path.insert(0, os.path.dirname(sys.argv[1])); from party_hud import sidebars
import party
fails = []
def ok(cond, msg):
    if not cond: fails.append(msg)
state = os.path.join(sys.argv[2], "crewstate")
os.environ["XDG_STATE_HOME"] = state
root = os.path.join(state, "party-hud", "crew")
read = lambda *p: open(os.path.join(root, *p), encoding="utf-8").read()
party.get_snapshot = lambda: {"towns": [{"agents": [{"pane": "%5", "kind": "codex", "round": 4}]}]}
party.tmux_run = lambda args, timeout=None: (0, "%5" + party.FIELD_SEP + "/work/dir\n", "")
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

exit "$fail"
