# Performance

Two scripts measure the cost. Numbers below are copied from their output; rerun them on your machine.

## Offline: one frame, fake data (`bench/bench.py`)

Median of 200 runs. `collect` turns raw pane data into squads, `render` draws the image-version sidebar
(33 columns, 60 rows). "New process" is a fresh `party.py --fixture … --width 33`: Python start-up, import and one
frame; that is the cost of `prefix a` (`--next`), the tmux hooks and restarting a hidden sidebar. It is measured
with the `party_hud/__pycache__` that Python writes on the first run; without it (a read-only install) Python compiles
every module on each start.

AMD Ryzen 9 5900XT, Linux, Python 3.14.8:

| agents | collect (ms) | render (ms) | new process (ms) |
|---:|---:|---:|---:|
| 1 | 0.027 | 0.1 | 40.2 |
| 5 | 0.056 | 0.294 | 41.6 |
| 10 | 0.089 | 0.323 | 41.4 |
| 20 | 0.153 | 0.364 | 42.0 |
| 50 | 0.376 | 0.543 | 42.5 |

Same machine, Python 3.10.22 (uv standalone build):

| agents | collect (ms) | render (ms) | new process (ms) |
|---:|---:|---:|---:|
| 1 | 0.029 | 0.114 | 26.0 |
| 5 | 0.058 | 0.319 | 26.1 |
| 10 | 0.09 | 0.348 | 26.4 |
| 20 | 0.154 | 0.404 | 26.5 |
| 50 | 0.346 | 0.59 | 27.0 |

Peak memory of the benchmark process: 22.5 MB.

The real collector also runs `tmux list-panes` once, `tmux capture-pane` once per non-Claude agent, and reads
the tail (last 256 KB) of each transcript; transcripts that did not change since the last read are skipped.
Those costs only show up in the live measurement.

## Live: your real tmux (`bench/live.sh`)

Run inside tmux with the sidebars open:

```bash
bench/live.sh 300
```

It samples every 5 s and reports how many sidebar processes are running, their CPU together (100% = one core),
average and peak memory (RSS), and how many snapshots were collected.

### Now: only visible sidebars run

AMD Ryzen 9 5900XT, Linux, tmux 3.8, Python 3.14, 24 windows (24 sidebar panes), 4 agents, 300 s,
normal use with window switching:

| measure | result |
|---|---|
| running sidebar processes | average 1.3, peak 5 (several windows visited within 2 s) |
| CPU, all sidebar processes | 0.22 % of one core |
| memory (RSS), all sidebars | average 32.4 MB, peak 121.7 MB |

Snapshot counts are not shown for these runs: the counter was reset on every window switch (fixed since).

A second run, with the sidebars switched on during the run, so the first seconds include all 24 starting at once:

| measure | result |
|---|---|
| running sidebar processes | average 2.5, peak 24 (the moment they were switched on) |
| memory (RSS), all sidebars | average 61.7 MB, peak 564.2 MB (same moment) |

Before: 24 processes and 591.6 MB all the time, so normal use now takes about 95 % less memory.
CPU was not measured correctly in this second run (`ps` reports whole seconds on Linux); `bench/live.sh` now
reads clock ticks from `/proc` instead.

### Before: one process per window

AMD Ryzen 9 5900XT, Linux, tmux 3.8, Python 3.14, 24 windows (24 sidebars), 300 s:

| measure | result |
|---|---|
| CPU, all 24 sidebars together | 2.12 % of one core (0.09 % each) |
| tmux server CPU, same 300 s | 2.99 % (all clients, includes normal typing) |
| memory (RSS), all sidebars | 591.6 MB (24.7 MB each) |

Agent and snapshot counts are missing from this run (the state folder had a different name); rerun to fill them in.

Memory was the main cost: every window ran its own Python process (about 11 MB for Python itself, 8 MB for
importing party-hud, the rest built up while running). CPU stays low because only one process collects data.
Now a sidebar stops its process after 2 s out of view (the pane keeps its last frame) and a tmux hook restarts it
when you switch to that window, so memory scales with the windows you are looking at, not the windows you have.

## Collection rate with many sidebars (`tests/party-tmux-test.sh`)

The integration test opens 20+ windows on a private tmux server and checks that data is collected at most
6 times in 10 seconds, no matter how many sidebars are open.
