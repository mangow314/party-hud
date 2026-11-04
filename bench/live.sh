#!/usr/bin/env bash
# Live benchmark: CPU and memory of the sidebars in your real tmux, over N seconds (default 60).
# Run it inside tmux with the sidebars open (prefix C-t). Linux and macOS (uses ps). Changes nothing.
#
#   bench/live.sh 300
#
# Samples every 5 s, because hidden sidebars stop and restart when you switch windows. Reports:
# sidebar panes vs running sidebar processes, CPU of all sidebar processes (100% = one core),
# average and peak total RSS, and how many snapshots were collected (one process collects for all).
set -euo pipefail
secs=${1:-60}
[ -n "${TMUX:-}" ] || { echo "run this inside tmux" >&2; exit 1; }
# PARTY_DIR overrides the state folder (e.g. a differently named copy of party.py)
snap="${PARTY_DIR:-${XDG_RUNTIME_DIR:-$HOME/.cache}/party-hud}/snapshot.json"
[ -f "$snap" ] || echo "warning: $snap not found; agent and snapshot counts will be missing (set PARTY_DIR)" >&2
seq_now() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("seq", 0))' "$snap" 2>/dev/null || echo 0; }
hz=$(getconf CLK_TCK 2>/dev/null || echo 100)
sample() { # "pid cpu_seconds rss_kb" for every running sidebar process (the python process itself, not shell wrappers)
  local p f ut st
  for p in $(pgrep -f '^[^ ]*[Pp]ython[0-9.]* [^ ]*party\.py --sidebar' || true); do
    if [ -r "/proc/$p/stat" ]; then # Linux: clock ticks (10 ms); ps time= only has whole seconds there
      f=$(cut -d')' -f2 "/proc/$p/stat" 2>/dev/null) || continue
      read -r _ _ _ _ _ _ _ _ _ _ _ ut st _ <<<"$f"
      echo "$p $(awk -v t=$((ut + st)) -v hz="$hz" 'BEGIN { printf "%.2f", t / hz }') $(ps -o rss= -p "$p" | tr -d ' ')"
    else # macOS: ps time= has hundredths (m:ss.cc)
      ps -o pid=,time=,rss= -p "$p" 2>/dev/null || true
    fi
  done
}

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
q0=$(seq_now)
end=$(($(date +%s) + secs))
echo "measuring for ${secs}s (sampling every 5 s) ..."
while [ "$(date +%s)" -lt "$end" ]; do
  { echo "T $(date +%s)"; sample; } >>"$tmp"
  sleep 5
done
q1=$(seq_now)
panes=$(tmux list-panes -a -F '#{@party_sidebar}' | grep -c '^1$' || true)
agents=$(python3 -c 'import json,sys; print(sum(len(t["agents"]) for t in json.load(open(sys.argv[1]))["towns"]))' "$snap" 2>/dev/null || echo "?")

python3 - "$tmp" "$secs" "$panes" "$agents" "$((q1 - q0))" <<'EOF'
import sys
path, secs, panes, agents, snaps = sys.argv[1], float(sys.argv[2]), sys.argv[3], sys.argv[4], int(sys.argv[5])

def cpu_seconds(s):  # ps time: [[dd-]hh:]mm:ss[.cc]
    days, _, s = s.rpartition("-")
    parts = [float(x) for x in s.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    return (int(days) if days else 0) * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]

first, last, rss_totals, counts, cur = {}, {}, [], [], None
for line in open(path):
    f = line.split()
    if f and f[0] == "T":
        if cur is not None:
            rss_totals.append(cur[0]); counts.append(cur[1])
        cur = [0, 0]
        continue
    if len(f) == 3:
        pid, t, rss = f[0], cpu_seconds(f[1]), int(f[2])
        first.setdefault(pid, t)
        last[pid] = t
        cur[0] += rss; cur[1] += 1
if cur is not None:
    rss_totals.append(cur[0]); counts.append(cur[1])
# a process seen only once contributes nothing; its CPU before the first sample is not counted (small: it just started)
cpu = sum(last[p] - first[p] for p in last) / secs * 100
avg = sum(rss_totals) / max(1, len(rss_totals)) / 1024
print(f"sidebar panes         {panes}")
print(f"agents                {agents}")
print(f"running sidebars      avg {sum(counts) / max(1, len(counts)):.1f}, max {max(counts or [0])}")
print(f"sidebar CPU total     {cpu:.2f} %")
print(f"sidebar RSS total     avg {avg:.1f} MB, peak {max(rss_totals or [0]) / 1024:.1f} MB")
print(f"snapshots collected   {snaps} in {secs:.0f}s ({snaps / secs:.2f}/s)")
EOF
