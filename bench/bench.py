"""Offline benchmark: how long party.py spends building and drawing one frame, with fake data.

No tmux needed. For each team size it times `collect` (turn raw pane data into squads) and
`render` (draw the sidebar, image version), and reports the median of many runs.
Real runs also pay for `tmux list-panes` and reading files; measure those with bench/live.sh.

  python3 bench/bench.py            # table for 1, 5, 10, 20, 50 agents
  python3 bench/bench.py --json     # same data as JSON
"""

import json
import os
import resource
import statistics
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PARTY = os.path.join(HERE, "..", "party.py")
sys.path.insert(0, os.path.join(HERE, ".."))
from party_hud.collect import collect
from party_hud.render import render


def fixture(n):
    """n Claude agents spread over squads of 4, with HP, cache and statusline data like a real session."""
    panes, sessions, party, cache = [], {}, {}, {}
    for i in range(n):
        pid = f"%{i + 1}"
        panes.append(
            {
                "session_name": f"squad{i // 4}",
                "window_index": str(i % 4),
                "window_name": f"task-{i}",
                "window_active": "1" if i % 4 == 0 else "0",
                "session_attached": "1" if i < 4 else "0",
                "pane_id": pid,
                "pane_active": "1",
                "pane_current_command": "claude",
                "pane_current_path": f"/work/{i}",
                "@workmux_pane_status": "",
                "window_id": f"@{i}",
            }
        )
        sessions[pid] = {"sid": f"s{i}", "name": f"agent {i}", "status": "busy" if i % 3 == 0 else "idle"}
        party[pid] = {
            "session_id": f"s{i}",
            "ctx_left": 100 - i % 90,
            "ctx_size": 1_000_000,
            "transcript": f"/t/{i}",
            "model": "Opus 5.5",
        }
        cache[f"/t/{i}"] = [9000 - i * 30, 3600, 100_000 + i * 1000]
    return {"panes": panes, "now": 10000, "sessions": sessions, "party": party, "cache": cache}


def timed(fn, runs):
    out = []
    for _ in range(runs):
        t = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t) * 1000)
    return statistics.median(out)


def startup_ms(path, runs=10):
    """Wall time of a fresh `party.py --fixture ... --width 33` process (Python start + import + one frame)."""
    out = []
    for _ in range(runs):
        t = time.perf_counter()
        subprocess.run(
            [sys.executable, PARTY, "--fixture", path, "--width", "33"], stdout=subprocess.DEVNULL, check=True
        )
        out.append((time.perf_counter() - t) * 1000)
    return statistics.median(out)


def main():
    rows = []
    for n in (1, 5, 10, 20, 50):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(fixture(n), f)
        snap = collect(f.name)
        rows.append(
            {
                "agents": n,
                "collect_ms": round(timed(lambda: collect(f.name), 200), 3),
                "render_ms": round(
                    timed(lambda snap=snap: render(snap["towns"], 33, "%1", height=60, art=True, tick=1), 200), 3
                ),
                "startup_ms": round(startup_ms(f.name), 1),
            }
        )
        os.unlink(f.name)
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (
        1024 * 1024 if sys.platform == "darwin" else 1024
    )  # macOS: bytes
    info = {"python": sys.version.split()[0], "platform": sys.platform, "peak_rss_mb": round(rss_mb, 1), "rows": rows}
    if "--json" in sys.argv:
        print(json.dumps(info, indent=1))
        return
    print(f"Python {info['python']} on {info['platform']}, peak RSS of this process {info['peak_rss_mb']} MB")
    print("| agents | collect (ms) | render (ms) | new process (ms) |")
    print("|---:|---:|---:|---:|")
    for r in rows:
        print(f"| {r['agents']} | {r['collect_ms']} | {r['render_ms']} | {r['startup_ms']} |")


if __name__ == "__main__":
    main()
