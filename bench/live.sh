#!/usr/bin/env bash
# Live benchmark: CPU and memory of every long-running party.py process in your real tmux, over N seconds (default 60),
# then the offline table of bench/bench.py. Run it inside tmux with the sidebars open (prefix C-t).
# Linux and macOS (uses ps). Changes nothing.
#
#   bench/live.sh 300              # live numbers, then the offline table
#   bench/live.sh 300 --no-offline # live numbers only
#
# Samples every 5 s, because hidden sidebars stop and restart when you switch windows. Two groups:
# sidebars (--sidebar) and other screens (--select, --menu, --report, --watch, --report-text --wait).
# For each: running processes, CPU of all of them (100% = one core), average and peak total RSS.
# Also how many snapshots were collected (one process collects for all). Warns when party.py runs from
# more than one directory: copies do not share a snapshot, so collections come out too high.
set -euo pipefail
secs=60 offline=1
for a in "$@"; do
  case "$a" in
    --no-offline) offline=0 ;;
    *) secs=$a ;;
  esac
done
[ -n "${TMUX:-}" ] || { echo "run this inside tmux" >&2; exit 1; }
# PARTY_DIR overrides the state folder (e.g. a differently named copy of party.py)
snap="${PARTY_DIR:-${XDG_RUNTIME_DIR:-$HOME/.cache}/party-hud}/snapshot.json"
[ -f "$snap" ] || echo "warning: $snap not found; agent and snapshot counts will be missing (set PARTY_DIR)" >&2
seq_now() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("seq", 0))' "$snap" 2>/dev/null || echo 0; }
hz=$(getconf CLK_TCK 2>/dev/null || echo 100)
sample() { # "pid cpu_seconds rss_kb group party.py-path" for every long-running party.py process (the python process itself, not shell wrappers)
  local p f ut st args grp path cpu rss
  for p in $(pgrep -f '^[^ ]*[Pp]ython[0-9.]* [^ ]*party\.py (--sidebar|--select|--menu|--report( |$)|--watch)' || true) \
    $(pgrep -f '^[^ ]*[Pp]ython[0-9.]* [^ ]*party\.py --report-text .*--wait' || true); do
    args=$(ps -o args= -p "$p" 2>/dev/null) || continue
    path=$(awk '{ print $2 }' <<<"$args")
    case "$args" in *" --sidebar"*) grp=side ;; *) grp=other ;; esac
    rss=$(ps -o rss= -p "$p" 2>/dev/null | tr -d ' ') || continue
    if [ -r "/proc/$p/stat" ]; then # Linux: clock ticks (10 ms); ps time= only has whole seconds there
      f=$(cut -d')' -f2 "/proc/$p/stat" 2>/dev/null) || continue
      read -r _ _ _ _ _ _ _ _ _ _ _ ut st _ <<<"$f"
      cpu=$(awk -v t=$((ut + st)) -v hz="$hz" 'BEGIN { printf "%.2f", t / hz }')
    else # macOS: ps time= has hundredths (m:ss.cc)
      cpu=$(ps -o time= -p "$p" 2>/dev/null | tr -d ' ') || continue
    fi
    if [ -n "$cpu" ] && [ -n "$rss" ]; then echo "$p $cpu $rss $grp $path"; fi
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

groups = {g: {"first": {}, "last": {}, "rss": [], "count": []} for g in ("side", "other")}
paths, cur = set(), None

def close(cur):
    for g, d in groups.items():
        d["rss"].append(cur[g][0]); d["count"].append(cur[g][1])

for line in open(path):
    f = line.split()
    if f and f[0] == "T":
        if cur is not None:
            close(cur)
        cur = {"side": [0, 0], "other": [0, 0]}
        continue
    if len(f) == 5 and cur is not None:
        pid, t, rss, grp = f[0], cpu_seconds(f[1]), int(f[2]), f[3]
        d = groups[grp]
        d["first"].setdefault(pid, t)
        d["last"][pid] = t
        cur[grp][0] += rss; cur[grp][1] += 1
        paths.add(f[4])
if cur is not None:
    close(cur)
if len(paths) > 1:
    print(f"warning: party.py runs from {len(paths)} directories ({', '.join(sorted(paths))}); copies do not share a snapshot, so collections come out too high", file=sys.stderr)

def stats(d):
    # a process seen only once contributes nothing; its CPU before the first sample is not counted (small: it just started)
    cpu = sum(d["last"][p] - d["first"][p] for p in d["last"]) / secs * 100
    avg = sum(d["rss"]) / max(1, len(d["rss"])) / 1024
    return cpu, avg, max(d["rss"] or [0]) / 1024, sum(d["count"]) / max(1, len(d["count"])), max(d["count"] or [0])

cpu, avg, peak, cavg, cmax = stats(groups["side"])
print(f"sidebar panes         {panes}")
print(f"agents                {agents}")
print(f"running sidebars      avg {cavg:.1f}, max {cmax}")
print(f"sidebar CPU total     {cpu:.2f} %")
print(f"sidebar RSS total     avg {avg:.1f} MB, peak {peak:.1f} MB")
print(f"snapshots collected   {snaps} in {secs:.0f}s ({snaps / secs:.2f}/s)")
cpu, avg, peak, cavg, cmax = stats(groups["other"])
print(f"running other screens avg {cavg:.1f}, max {cmax}")
print(f"other screens CPU     {cpu:.2f} %")
print(f"other screens RSS     avg {avg:.1f} MB, peak {peak:.1f} MB")
EOF

if [ "$offline" = 1 ]; then
  echo
  echo "offline (bench/bench.py):"
  python3 "$(dirname "${BASH_SOURCE[0]}")/bench.py"
fi
