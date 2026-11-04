#!/usr/bin/env bash
# Sidebar integration tests: runs a separate tmux server (-L party-test), leaving your running tmux alone.
# A real client is attached through `script` (util-linux or BSD/macOS), so "visible" means the same as for you.
# Needs a real tmux socket: won't run inside the Claude Code sandbox; run it in a normal terminal or via `!`.
# Takes about 50 seconds.
set -uo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
party="$root/party.py"
tmp=$(mktemp -d)
export XDG_RUNTIME_DIR="$tmp/xdg" TMUX_TMPDIR="$tmp" PYTHONDONTWRITEBYTECODE=1
mkdir -p "$XDG_RUNTIME_DIR"
t() { tmux -L party-test "$@"; }
trap 't kill-server 2>/dev/null; pkill -P $$ sleep 2>/dev/null; rm -rf "$tmp"' EXIT

fail=0
check() { # check <description> <command...>
  local desc=$1
  shift
  if "$@"; then echo "ok   $desc"; else echo "FAIL $desc"; fail=1; fi
}
sidebars() { t list-panes -a -F '#{@party_sidebar}' | grep -c '^1$'; }
running() { t list-panes -a -F '#{@party_sidebar} #{pane_dead}' | grep -c '^1 0$'; } # sidebars with a live process
windows() { t list-windows -a | wc -l; }
eq() { [ "$1" = "$2" ] || { echo "     expected [$2], actual [$1]" >&2; return 1; }; }
le() { [ "$1" -le "$2" ] || { echo "     expected <= $2, actual $1" >&2; return 1; }; }
ge() { [ "$1" -ge "$2" ] || { echo "     expected >= $2, actual $1" >&2; return 1; }; }
now_ms() { python3 -c "import time; print(int(time.time() * 1000))"; } # date +%s%N is not portable
seqno() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["seq"])' "$XDG_RUNTIME_DIR/party-hud/snapshot.json" 2>/dev/null || echo 0; }
alive_in() { t list-panes -t "$1" -F '#{@party_sidebar} #{pane_dead}' | grep -q '^1 0$'; }

t -f /dev/null new-session -d -s a -x 200 -y 50
t new-window -t a: # trailing colon = next free index in that session; plain a may resolve to a window and hit index in use
t new-session -d -s b -x 200 -y 50

# Attach one client to session a. `sleep | script` keeps the client's stdin open without needing your terminal.
attach="stty cols 200 rows 50; tmux -L party-test attach -t a"
if script --version >/dev/null 2>&1; then # util-linux (Linux)
  sleep 600 | env -u TMUX TERM=xterm-256color script -qfc "$attach" /dev/null >/dev/null 2>&1 &
else # BSD (macOS): script [-q] file command...
  sleep 600 | env -u TMUX TERM=xterm-256color script -q /dev/null sh -c "$attach" >/dev/null 2>&1 &
fi
for _ in $(seq 40); do [ -n "$(t list-clients -F x 2>/dev/null)" ] && break; sleep 0.25; done
check "A client is attached to session a" eq "$(t list-clients -F '#{session_name}')" "a" ||
  { echo "     cannot attach a test client (needs util-linux or BSD script); stopping" >&2; exit 1; }

t run-shell "$root/party.tmux"
check "party.tmux: binds 4 keys (popup, toggle, next, border drag)" eq "$(t list-keys | grep -c 'party.py')" "4"
check "party.tmux: enables allow-passthrough (images pass through tmux)" eq "$(t show -gv allow-passthrough)" "on"

t run-shell "python3 $party --toggle"
sleep 2
check "Toggle on: every window has a sidebar (3)" eq "$(sidebars)" "$(windows)"
check "Toggle on: new-window hook installed" eq "$(t show-hooks -g | grep -c 'new-window\[90\]')" "1"
check "Toggle on: session / window switch hooks installed (cursor follows you)" \
  eq "$(t show-hooks -g | grep -cE '(client-session|session-window)-changed\[90\]')" "2"
check "Toggle on: tidy and attach hooks installed" \
  eq "$(t show-hooks -g | grep -cE '(after-kill-pane|client-attached)\[90\]')" "2"

# Memory: sidebars you cannot see stop their process after 2 s; the pane stays (dead, keeps its last frame)
sleep 4
check "Memory: only the visible window's sidebar keeps running (1 of 3)" eq "$(running)" "1"
check "Memory: hidden sidebar panes stay in place" eq "$(sidebars)" "$(windows)"

# Switching to a window restarts its sidebar right away
t select-window -t a:0
start=$(now_ms)
for _ in $(seq 40); do alive_in a:0 && break; sleep 0.05; done
ms=$(($(now_ms) - start))
echo "     sidebar restarted ${ms} ms after switching window"
check "Switch window: that window's sidebar is running again within 1 s" le "$ms" 1000
sleep 4
check "Switch window: the window you left stops its sidebar after 2 s" eq "$(running)" "1"

t new-window -t a:
sleep 2
check "New window gets a sidebar automatically" eq "$(sidebars)" "$(windows)"
check "Sidebar width is the default 34" eq "$(t list-panes -a -F '#{@party_sidebar} #{pane_width}' | grep '^1 ' | cut -d' ' -f2 | sort -u)" "34"

t resize-window -t a:1 -x 150
sleep 4
check "After a window resize the width returns to 34" eq "$(t list-panes -t a:1 -F '#{@party_sidebar} #{pane_width}' | grep '^1 ' | cut -d' ' -f2)" "34"

# Manually widened sidebar: kept, not reset to 34; later new windows use the new width too
side0=$(t list-panes -t a:0 -F '#{pane_id} #{@party_sidebar}' | grep ' 1$' | cut -d' ' -f1)
t resize-pane -t "$side0" -x 40
t run-shell "python3 $party --remember-width" # same as finishing a mouse border drag (MouseDragEnd1Border)
sleep 2
check "Sidebar dragged wider -> stays 40" eq "$(t display -p -t "$side0" '#{pane_width}')" "40"
check "Sidebar dragged wider -> remembered as the global width" eq "$(t show -gqv @party_sidebar_width)" "40"
t new-window -d -t b:
sleep 2
check "Windows opened later also get a 40-wide sidebar" eq "$(t list-panes -t b:1 -F '#{@party_sidebar} #{pane_width}' | grep '^1 ' | cut -d' ' -f2)" "40"
# Dragged narrower than the minimum (30): bounces back to 30, and 30 becomes the remembered width
t resize-pane -t "$side0" -x 25
t run-shell "python3 $party --remember-width"
sleep 2
check "Dragged to 25 -> bounces back to the minimum 30" eq "$(t display -p -t "$side0" '#{pane_width}')" "30"
check "Dragged to 25 -> remembered width is 30" eq "$(t show -gqv @party_sidebar_width)" "30"

# Bell: a member in a window you cannot see starts waiting -> that window is flagged, with no sidebar running there
bmain=$(t list-panes -t b:0 -F '#{pane_id} #{@party_sidebar}' | grep -v ' 1$' | cut -d' ' -f1)
t set-option -p -t "$bmain" @workmux_pane_status "💬"
sleep 5
check "Bell: hidden window b:0 gets the bell flag when its member starts waiting" eq "$(t display -p -t b:0 '#{window_bell_flag}')" "1"

# Closing the main pane of a hidden window (its sidebar is not running) still closes the window
before=$(windows)
main=$(t list-panes -t a:1 -F '#{pane_id} #{@party_sidebar}' | grep -v ' 1$' | cut -d' ' -f1)
t kill-pane -t "$main"
sleep 3
check "Closing the main pane also closes a window left with only the sidebar" eq "$(windows)" "$((before - 1))"
# The main pane's program exits by itself in a hidden window (no kill-pane, so no hook): the collector closes it
before=$(windows)
bmain1=$(t list-panes -t b:1 -F '#{pane_id} #{@party_sidebar}' | grep -v ' 1$' | cut -d' ' -f1)
t send-keys -t "$bmain1" "exit" Enter
sleep 5
check "Hidden window whose main program exits on its own is closed too" eq "$(windows)" "$((before - 1))"

# Performance: open 20 more windows; still about one collection per 2 s, and only visible sidebars run
t new-session -d -s c -x 200 -y 50
for _ in $(seq 19); do t new-window -d -t c:; done
sleep 4
seq1=$(seqno)
sleep 10
seq2=$(seqno)
echo "     $(sidebars) sidebars, $(running) running, $((seq2 - seq1)) collections in 10 s"
check "Performance: 3 to 6 collections in 10 s (about one per 2 s)" test "$(ge $((seq2 - seq1)) 3 && le $((seq2 - seq1)) 6 && echo y)" = y
check "Memory: with $(sidebars) sidebars, at most 2 processes run" le "$(running)" 2

# Pressing q in a sidebar hides all sidebars (including itself)
t send-keys -t "$(t list-panes -a -F '#{pane_id} #{@party_sidebar} #{pane_dead}' | grep ' 1 0$' | head -1 | cut -d' ' -f1)" q
sleep 3
check "q in a sidebar: all sidebars closed" eq "$(sidebars)" "0"
check "Toggle off: hooks removed" \
  eq "$(t show-hooks -g | grep -cE '(new-window|client-session-changed|session-window-changed|after-kill-pane|client-attached)\[90\]')" "0"
check "Toggle off: all sessions still exist" eq "$(t list-sessions | wc -l)" "3"

exit "$fail"
