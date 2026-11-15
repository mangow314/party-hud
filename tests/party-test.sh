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
