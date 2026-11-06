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
import json, tempfile
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
from datetime import datetime as _dt
root = _tf.mkdtemp(); now_ = _t.time(); day = os.path.join(root, f"{_dt.now():%Y/%m/%d}"); os.makedirs(day)
def roll(name, cwd, age):
    p = os.path.join(day, f"rollout-{name}.jsonl")
    open(p, "w").write(json.dumps({"type": "session_meta", "payload": {"cwd": cwd}}) + "\n")
    os.utime(p, (now_ - age, now_ - age))
    return p
roll("old", "/w/a", 600); new_a = roll("new", "/w/a", 5); roll("other", "/w/b", 1)
ok(collect.newest_rollout("/w/a", now_ - 60, root) == new_a and collect.newest_rollout("/w/a", now_ - 3, root) is None
   and collect.newest_rollout("/w/c", now_ - 60, root) is None,
   "codex rollout: newest file written after codex started, same cwd; older files and other dirs don't count")
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
