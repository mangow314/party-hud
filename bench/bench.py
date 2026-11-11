"""Offline benchmark: how long party.py spends building and drawing one frame, with fake data.

No tmux needed. For each team size it times `collect` (turn raw pane data into squads) and one frame of each
screen, and reports the median of 200 runs (20 for select and report, which cost far more):
  render  the sidebar (33 x 60, image version)
  select  the select screen (`render_select`, 179 x 47, cursor on the first member, no images, 70-line report)
  report  the report page (`report_parts`, 179 x 47, split layout with art, fixed frame, same report)
select and report draw the same report again and again, so the Markdown layout is reused: that is a redraw of
unchanged content, the usual frame. select_cold and report_cold clear the layout cache before every frame: that is
the frame where the report text or the width has just changed.
Real runs also pay for `tmux list-panes` and reading files; measure those with bench/live.sh.

  python3 bench/bench.py            # table for 1, 5, 10, 20, 50 agents
  python3 bench/bench.py --json     # same data as JSON, plus the "use" object
  python3 bench/bench.py --no-use   # skip the in-use run below

After the table, "in use" plays a fixed 30 s key script on the select screen and report page in a pty (bench/use.py,
3 runs, median) and reports CPU as a share of one core, per step. The target is under 1 %.
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
from party_hud.render import clear_markdown_cache, render, render_select, report_parts, select_roster


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


REPORT = {
    "start": 9000,
    "end": 9600,
    "live": False,
    "text": "\n".join(
        ["## Summary", "", "Fake report text for the benchmark.", ""]
        + [f"- step {i}: changed `module_{i}.py` and ran the tests, all green" for i in range(30)]
        + ["", "## Details", ""]
        + [
            f"Paragraph {i}: a longer line of **bold** and `code` text that has to be wrapped to fit the width."
            for i in range(20)
        ]
        + ["", "```", *[f"code line {i}" for i in range(10)], "```"]
    ),
}
W, H = 179, 47
NOW = 10000
SLOW_RUNS = 20  # a select or report frame costs ~10 ms; 200 runs would slow CI


def cold(fn):
    def run():
        clear_markdown_cache()
        fn()

    return run


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
        towns = snap["towns"]
        roster = select_roster(towns)
        squad, agent = towns[0]["name"], towns[0]["agents"][0]

        def select(r=roster, t=towns):
            render_select(r, t, r[0][1]["pane"], W, H, REPORT, NOW, None, False)

        def report(a=agent, s=squad):
            report_parts(a, s, REPORT, [], W, 1, 1, True, height=H, now=NOW, fixed=True)

        rows.append(
            {
                "agents": n,
                "collect_ms": round(timed(lambda: collect(f.name), 200), 3),
                "render_ms": round(
                    timed(lambda snap=snap: render(snap["towns"], 33, "%1", height=60, art=True, tick=1), 200), 3
                ),
                "select_ms": round(timed(select, SLOW_RUNS), 3),
                "report_ms": round(timed(report, SLOW_RUNS), 3),
                "select_cold_ms": round(timed(cold(select), SLOW_RUNS), 3),
                "report_cold_ms": round(timed(cold(report), SLOW_RUNS), 3),
                "startup_ms": round(startup_ms(f.name), 1),
            }
        )
        os.unlink(f.name)
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (
        1024 * 1024 if sys.platform == "darwin" else 1024
    )  # macOS: bytes
    info = {"python": sys.version.split()[0], "platform": sys.platform, "peak_rss_mb": round(rss_mb, 1), "rows": rows}
    if "--no-use" not in sys.argv:
        import use

        info["use"] = use.measure(fixture)
    if "--json" in sys.argv:
        print(json.dumps(info, indent=1))
        return
    print(f"Python {info['python']} on {info['platform']}, peak RSS of this process {info['peak_rss_mb']} MB")
    print(
        "| agents | collect (ms) | render (ms) | select (ms) | report (ms) | select cold (ms) | report cold (ms) | new process (ms) |"
    )
    print("|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        print(
            f"| {r['agents']} | {r['collect_ms']} | {r['render_ms']} | {r['select_ms']} | {r['report_ms']} | "
            f"{r['select_cold_ms']} | {r['report_cold_ms']} | {r['startup_ms']} |"
        )
    if "use" in info:
        u = info["use"]
        print(
            f"\nin use: {u['cpu_pct']} % of one core over {u['seconds']} s (median of {u['runs']} runs: "
            f"{', '.join(str(p) for p in u['run_cpu_pct'])}), peak RSS {u['peak_rss_mb']} MB"
        )
        print("| step | CPU (ms) | written (KB) |")
        print("|---|---:|---:|")
        for st in u["steps"]:
            print(f"| {st['name']} | {st['cpu_ms']} | {st['out_kb']} |")


if __name__ == "__main__":
    main()
