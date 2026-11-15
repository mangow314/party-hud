#!/usr/bin/env bash
# party.py unit tests not yet moved to pytest (no tmux needed): transcript TTL, statusline script, art PNG sizes,
# cw, imports per sub-command, leaving without teardown; the fixture is tests/fixtures/sidebar.json
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
