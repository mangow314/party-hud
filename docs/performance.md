# Performance

Two scripts measure the cost. Numbers below are copied from their output; rerun them on your machine.
One command runs both: `bench/live.sh [seconds]` prints the live numbers, then the offline table.

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

Peak memory of the benchmark process: 17.1 MB (22.4 MB before ticket 044).

Columns added later: `select` is one frame of the select screen (`render_select`, 179 × 47, cursor on the first member,
no images, a fake report of 70 lines) and `report` is one frame of the report page (`report_parts`, 179 × 47, split
layout with art, fixed frame, the same report). Median of 20 runs, because a frame costs about 10 ms. They are new
columns, so there are no earlier numbers. The tables above predate them.

`render_markdown` keeps the layout of the last 32 inputs, so a redraw of an unchanged report skips it. The bench
therefore has two kinds of each column: `select` and `report` draw the same report again and again (a redraw of
unchanged content, the usual frame); `select cold` and `report cold` clear the layout cache before every frame (the
frame where the report text or the width has just changed). Before the cache, `select` was 8.5 to 11.4 ms and `report`
7.4 to 7.6 ms (1 to 50 agents). Now:

| agents | select (ms) | report (ms) | select cold (ms) | report cold (ms) |
|---:|---:|---:|---:|---:|
| 1 | 0.53 | 0.22 | 3.67 | 3.38 |
| 50 | 2.99 | 0.22 | 6.18 | 3.42 |

(Before ticket 044, `cw` cached: select 1.17 / 4.23 ms, report 0.24 / 0.23 ms, select cold 8.35 / 11.5 ms, report cold
7.39 / 7.57 ms for 1 / 50 agents. Full table after 044: select 0.53, 0.97, 1.30, 1.74, 2.99 ms and select cold 3.67,
4.16, 4.52, 4.95, 6.18 ms for 1, 5, 10, 20, 50 agents; new process 45.9 to 47.5 ms, unchanged.)

`bench/bench.py` also runs on its own, with no tmux (other machines, CI): `python3 bench/bench.py` prints the table,
`--json` prints the same data.

The real collector also runs `tmux list-panes` once, `tmux capture-pane` once per non-Claude agent, and reads
the tail (last 256 KB) of each transcript; transcripts that did not change since the last read are skipped.
Those costs only show up in the live measurement.

## In use: a fixed key script (`bench/use.py`)

The target is `cpu_pct` below 1: the select screen and report page, key presses included, cost under 1 % of one core.
`python3 bench/bench.py` ends with an "in use" part (`--json`: the `use` object; `--no-use` skips it). It runs the real
`run_menu` in a pty (179 x 47) as a child process and sends keys on a fixed schedule; the schedule is the `STEPS` table
in `bench/use.py`, about 27 s: open the select screen (process start, imports, first images), idle with the cursor on a
working member, `k` x4 to members not seen yet, `j` x3 back to seen ones, Enter into the report page (images and
opening animation), scroll `j j j k k`, `n` to the next member, `h` back to the select screen, `q`, then open again
and `q`. A step's CPU is the growth of the child's user+sys time between its start and its end (Linux:
`/proc/<pid>/schedstat`; macOS: `ps -o time=`, 10 ms steps); the step that ends in an exit uses the exit's rusage. The
run is repeated 3 times and every number is the median; the whole of `bench.py` takes about 90 s.

Replaced inside the child only (monkeypatch, nothing in `party_hud/` knows about it): `get_snapshot` returns a fixed
snapshot (5 leads: 1 waiting, 3 done, 1 working with a live report and a previous one), `report_for` returns a fixed
70-line Markdown report per member (all different, so the layout cache cannot hide a change of member), `capture`
and `tmux` return nothing, `mark_seen` does nothing, images are forced on and really written to the pty (with the
tmux passthrough wrapper), the opening animation is on. Not covered: a real tmux (`resize-pane`, hooks, `list-panes`),
resizes, and what the terminal spends decoding and drawing the images.

AMD Ryzen 9 5900XT, Linux, Python 3.14.8, `cpu_pct` 0.832 / 0.845 / 0.838 in the three runs of one `bench.py` after ticket 043 (median 0.838; after 044, before 043: 0.894 / 0.843 / 0.846, median 0.846; before 044, after 042: 1.138 / 1.094 / 1.117, median 1.117; before ticket 042, with a snapshot read of its own: 1.278 / 1.283 / 1.281, median 1.281):

| step | CPU (ms) | written (KB) |
|---|---:|---:|
| open select | 54.0 | 493.9 |
| idle on working (5 s) | 21.8 | 302.6 |
| k x4, new members (4 s) | 37.1 | 270.3 |
| j x3, seen members (3 s) | 13.2 | 180.2 |
| Enter, open report | 8.6 | 334.0 |
| scroll j j j k k (3 s) | 2.4 | 106.0 |
| n, next member | 7.1 | 309.7 |
| h, back to select | 15.8 | 523.2 |
| q, close | 6.0 | 0.1 |
| reopen, then q (3 s) | 63.5 | 554.5 |

Total 0.84 % over 27.5 s (ticket 043, a 6-row report banner and a 14-column big portrait, changed the report steps only by the smaller placeholder text: written 357 -> 334 KB on Enter, 324 -> 310 KB on `n`, 166 -> 106 KB on scroll; CPU stays within the run-to-run noise; before ticket 043 0.85 %; before ticket 044: 1.12 %, 1.28 % before 042), peak RSS 20.6 MB (22.4 MB before 044, the bench process's own peak): below the target (the idle step 41.3 -> 27.9 -> 21.8 ms). Where the time goes (cProfile of the child, steps cut at
each key; profiling inflates every number, read the shares):

- A select frame is the cost. Measured without a profiler on the same data (`time.perf_counter`, median of 30):
  `render_select` takes 1.9 ms for a member seen before (layout cached), 2.1 ms for the working member, 12.0 ms for a
  member not seen yet (the Markdown layout is added). Before ticket 042 a working cursor redrew about 3 times a second even when idle
  (snapshot every second plus the clock tick), and about 60 KB a second was written; the snapshot is now read at the
  wake of a clock tick, so it is 2 times at most.
- Ticket 044 made `cw` fast: an all-ASCII string is `len(s)` (checked: no code point 0 to 127 is combining or W/F),
  anything else sums a per-character width from an `lru_cache` of 4096 entries (an entry is a one-char key and a small
  int, a few hundred KB at most; the cache is filled only by characters actually drawn). The numbers above are after it.
  The text below measured the state before it.
- Before 044, the cost was `common.cw` (display width, a Python generator per character). The profiler makes a per-character
  generator look worse than it is (it counts every call), so its 8 ms a frame and 77 to 83 % share are only a ranking.
  Real share, measured by swapping `cw` for an `lru_cache` wrapper in the measuring script only: a seen frame
  1.89 -> 0.69 ms (63 %), a working frame 2.06 -> 0.70 ms (66 %), an unseen frame 11.98 -> 4.91 ms (59 %). That is the
  most a cache of `cw` can save, about 60 % of every select frame. Calls per frame (counted on the child's data): 413
  calls over 14 139 characters for a seen frame, 500 over 13 919 for the working one, 22 574 over 36 300 for an
  unseen one (the Markdown layout calls it per token).
- A new member's preview (`k`) adds the Markdown layout of the report: `md_rows` 32 ms under the profiler (68 blocks,
  `md_tokens` half of it), 10 ms without. Seen members reuse the cache (`j x3` costs a third of `k x4`).
  The preview now lays out only the part of the report it shows (`render_markdown(..., limit)`, stopping at the end of the block that
  brings the rows past the preview height; a table is one block): `render_select` for a member not seen yet 5.61 -> 3.17 ms
  (`bench/frame.py`, median of 30; the first layout of a whole report 4.28 ms, of the part shown 2.73 ms), and in the key script
  (`bench/bench.py`, before -> after) open select 58.5 -> 49.4 ms, `k x4` 38.5 -> 27.9 ms, reopen 65.7 -> 60.9 ms, the other steps within
  1.1 ms, in use 0.847 -> 0.781 % of one core (medians of 3 runs). The report page still lays out the whole report.
- Starting a process (open select, reopen): `import party_hud.ui` 14 ms, `load_art` 0.4 ms (56 PNGs opened, not read; each file is read when it is sent), the
  base64 encoding of the images 0.03 to 0.4 ms each; the rest is the select frames above. A process start is 65 to 80 ms
  of which frames are about half.
- The report page is cheap once drawn: scrolling costs 3 ms for 5 keys; Enter and `n` cost 13 to 15 ms, mostly one
  Markdown layout.

Do the banner and the portraits get cheaper when they take fewer cells? No. The PNGs have a fixed size and the cell
count only sets the placement (`c=`, `r=` in `kitty_image`, `art.py:119`): the small portrait is 192 x 216
(`PORTRAIT_PX`, 46 KB), the big one 384 x 432 (136 KB), banners are 960 px wide and 240 to 120 px tall for the 4:1
to 8:1 shapes (`BANNER_RATIOS`, `art.py:43`), picked by the shape of the cells, not by their number. Halving
the banner row limit from 10 to 5 (patched in the child, 3 runs each): Enter 14.3 -> 14.7 ms CPU and
357 -> 330 KB written (the 8:1 banner is a smaller file); the select screen's idle output fell 303 -> 216 KB, because
fewer placeholder rows are text; `cpu_pct` 1.25 -> 1.22. Terminal-side decoding is not in these numbers.

Are images resent or reused? Reused within one process, resent on a new one. `run_menu` reads the files and builds one `sent`
(`load_images`) and passes it to every `run_select` and `run_report` it starts, and neither deletes images on exit, so `h` and
Enter send only the images whose cells changed: `h` writes 523 -> 180 or 210 KB depending on the run (the select banner and portraits were already in
the terminal; what is left is the frame), Enter stays at 335 KB (the page itself and the big portrait, which the select
screen never sends). Reopening from the key binding is a new process and sends again. Inside the report page `n` keeps `sent` and
`report_images` skips an image whose cells are unchanged; only the new member's big portrait is sent (311 KB written, mostly
the page itself). A resize redraw resends only images whose cell count changed, under the same id; the script has no resize,
so this part is read from the code, not measured.

## Report page: time to the first image (`bench/art.py`)

`python3 bench/art.py` (about 20 s, no tmux, stdlib only) runs the real `run_report` / `run_menu` in a pty (179 x 47)
and timestamps every read of the child's output. Scenarios, 5 runs each, median: (a) the report page opened directly,
animation on; (b) the same, animation off; (c) `run_menu`: the select screen, wait until its images are out, Enter, the
report page (only the report page is timed). Each prints process start (in (c): the Enter key) to the first frame (first
`\x1b[H`), the first frame to the last animation frame, the first image (first `a=T`) to the last image, and the line
`first image after first frame`. `load_art()` and the Python start plus
`import party_hud.ui` are timed on their own.

What is measured is time inside the program. Not covered: what tmux spends forwarding the passthrough, what the terminal
spends decoding and drawing the images, and in (c) the two tmux round trips of `fit_report_pane` (it needs `TMUX_PANE`,
which the child does not have). In (c) `load_art()` runs when the select screen opens, so it is not in the report
segment, and the first image of the report page is its banner (the small portrait is not on the split page).

AMD Ryzen 9 5900XT, Linux, Python 3.14.8, HEAD 7a96a3b plus the change that sends the images with the first frame:

| segment (ms) | (a) animation on | (b) animation off | (c) menu, Enter |
|---|---:|---:|---:|
| process start (or key) -> first frame | 41.6 | 41.9 | 4.9 |
| first frame -> last animation frame | 400.1 | 0.0 | 400.6 |
| **first frame -> first image** | **0.9** | **1.0** | **0.5** |
| first image -> last image | 0.5 | 0.5 | 0.4 |

Before, a fixed 0.3 s wait came first and the images followed the last animation frame (401 / 300 / 401 ms).

On their own: `load_art()` 0.3 ms (56 PNGs, warm cache), `python3` + `import party_hud.ui` 31.6 ms.

The images are written right after the first frame, so the animation no longer delays them: the first image comes
1 ms or less after the first frame, and the other animation frames follow. Opening the files (`load_art`), reading one when it is sent, encoding and
writing the images are 1 ms or less each. The 2 s seen in a real tmux is not in these numbers; it has to come from
outside the program (tmux round trips such as `fit_report_pane`, forwarding and terminal decoding), or from
`RESIZE_SETTLE` (0.15 s) restarting after the pane resize signal, which this script does not produce.

## Memory and start-up (`bench/mem.py`)

`python3 bench/mem.py` (about 40 s, no tmux, stdlib only, Linux and macOS) prints four parts. RSS is always read from
outside the process: `/proc/<pid>/status` `VmRSS` on Linux, `ps -o rss= -p <pid>` elsewhere.

1. RSS of the three long-running processes in a pty (179 x 47): the sidebar (`run_ui`), the select screen (through
   `run_menu`, as in use) and the report page (`run_report`). The child is `import party` plus the real `ui` functions
   with the outside world replaced, as in `bench/use.py` (fixed snapshot and reports, no tmux, images forced on and
   written to the pty, `load_art` real). Three points: after the first frame and its images, after 5 s idle, after a
   round of keys (sidebar: `j k J K n` moves; select: `k` x4, every member seen; report: `n` x5 through the pages,
   `j j j k k`). 3 runs, median; the three kinds of one run go at the same time.
2. Import cost: a fresh `python3` per state (no accumulating in one process), RSS and the time the imports took
   inside the child, median of 3. The standard library list is read from the module-level import statements of `party.py`
   and `party_hud/*.py` (an import inside a function is not start-up cost). Then one more `party_hud` module per process, then `load_art()`, then each standard library
   module alone over an empty Python. The numbers of one module alone are not additive: `json` and `re` share
   what each pulls in.
3. Which sub-command needs which module (table below, from the code).
4. A fresh `run_menu` from spawn to the first frame and the first image byte, segments timed inside the child with
   `time.perf_counter` (the Python start is the spawn to the child's first line, wall clock); 5 runs, median.

Every child imports the built-in `time` first for its clock; the "empty Python" row includes it.

AMD Ryzen 9 5900XT, Linux 7.2.11, Python 3.14.8, with the image files read when they are sent (before: HEAD `f6a0f5e`,
which kept all 56 PNGs in memory: 17.1 / 17.4 / 17.3 MB after the first frame; before the lazy imports 18.8 / 19.1 / 18.8 MB):

| process | after first frame | after 5 s idle | after use |
|---|---:|---:|---:|
| sidebar (MB) | 15.1 | 15.1 | 15.1 |
| select (MB) | 15.3 | 15.3 | 15.4 |
| report (MB) | 14.9 | 14.9 | 15.1 |

Two of the three runs agree within 0.3 MB; the first run of a `bench/mem.py` call is 3.5 MB higher (18.5 to
18.8 MB here), so the median of 3 hides a cold start.

| state (fresh process) | RSS (MB) | added (MB) | imports took (ms) | added (ms) |
|---|---:|---:|---:|---:|
| empty Python | 9.9 | | 0.0 | |
| the 22 standard library modules the product imports at module level | 13.2 | 3.4 | 12.2 | 12.2 |
| + `party_hud.common` | 13.3 | 0.1 | 12.4 | 0.2 |
| + `.art` | 13.4 | 0.1 | 13.2 | 0.8 |
| + `.collect` | 13.6 | 0.3 | 13.8 | 0.6 |
| + `.render` | 13.9 | 0.2 | 15.0 | 1.2 |
| + `.sidebars` | 13.9 | 0.0 | 15.4 | 0.4 |
| + `.ui` | 14.0 | 0.1 | 15.1 | -0.4 |
| + `load_art()` (result kept) | 14.0 | 0.0 | 16.0 | 0.9 |

(Before: `load_art()` kept the 56 PNGs, 16.1 MB, +2.1 MB, +2.0 ms.)

(Before, the list had 26 modules, counting the ones imported inside functions: `traceback`, `shutil`, `argparse`,
`typing`; the row was 17.0 MB and 29.0 ms.)

Standard library modules alone over the empty Python, above 0.1 MB: `subprocess` 2.1, `json` 1.6, `glob` 1.5, `re` 1.3,
`contextlib` 0.7, `functools` 0.7, `signal` 0.4, `base64` 0.3, `unicodedata` 0.1, `zlib` 0.1 MB. `glob`, `datetime`,
`shlex` and `contextlib` on top of the others add 0.09 MB or less and 0.2 ms or less each (9 runs, median), so they stay
imported at the top.

Fresh `run_menu`, spawn to first frame and first image (median of 5, ms):

| segment | ms |
|---|---:|
| Python start (spawn to the first line of the child) | 9.6 |
| `import party` and `party_hud.ui` | 15.4 |
| `load_images` (fake tmux, real `load_art`) | 0.4 |
| first `get_snapshot` (fake) | 0.0 |
| first `render_select` | 5.8 |
| write and flush of the first frame | 0.2 |
| the rest of `run_menu` until the frame | 0.8 |
| first frame at | 32.3 |
| first image written at | 34.2 |

What the numbers say, ranked:

- RSS of a running process is 14.9 to 15.4 MB. Of that, an empty Python is 9.9 MB, the standard library modules the
  product imports add 3.4 MB and all `party_hud` modules together add 0.8 MB. The images add nothing: `load_art` only
  opens the 56 files, and `send_image` reads one when it sends it (they were 2.1 MB when all 56 stayed in memory).
- Largest single standard library modules (overlapping): `subprocess`, `json`, `glob`, `re`.
- Start of a select process: Python start 9.6 ms, `import party` and `party_hud.ui` 15.4 ms, then the first
  `render_select` 5.8 ms.
- Not measured: macOS (the `ps` path is written but was not run), and the terminal or tmux side of the images.

Which `party_hud` modules each sub-command calls into (read from the code; `party.py` imports `collect`, `common` and
`sidebars` at the top and `render` and `ui` inside the branch that needs them, so `--ensure`, `--tidy`, `--ask` and the
other short-lived sub-commands never load those two):

| sub-command | `common` | `art` | `collect` | `render` | `sidebars` | big parts |
|---|---|---|---|---|---|---|
| sidebar (`run_ui`) | `tmux`, `load_cursor` | `load_art`, `send_image` | `get_snapshot`, `collect` | `render` | `mark_sidebar`, `install_hooks`, `open_report_pane` | images, tmux open pane (`r`); no Markdown, no `report_for` |
| select (`run_menu`, `run_select`) | `tmux` | `load_art`, `send_image` | `get_snapshot`, `report_for` | `render_select` | `fit_report_pane`, `open_report_pane` | images, Markdown layout (`render_markdown` in `report_rows`), report parsing |
| report (`run_report`) | `tmux` | `load_art`, `send_image` | `get_snapshot`, `report_for` | `report_parts` | `mark_seen`, `fit_report_pane` | images, Markdown layout, report parsing |
| `--report-text` (`report_text`) | `tmux_run` | | `report_text`, `report_for` | | `crew_replied`, `mark_seen` | report parsing; no Markdown, no images |
| `--ask` (`ask`) | `tmux_run` | | `get_snapshot` | | `crew_asked` | tmux `load-buffer`, `paste-buffer` |
| `--summon` (`summon`) | `tmux_run`, `tmux` | | `get_snapshot` | | `summon`, `crew_summoned` | tmux open pane |
| `--dismiss` (`dismiss`) | `tmux_run` | | `get_snapshot` | | `dismiss` | tmux close pane |
| collector (`get_snapshot` taking `snapshot.lock`) | `tmux_run` | | `collect` | | | pane list, transcript tails, agent reports; no Markdown, no images |

`ui` is needed by the sidebar, select and report only; `jump_next` (`--next`) and `open_select` (`--menu`) are in
`ui` too but call only `get_snapshot`, `tmux`, `save_cursor` and `open_report_pane`.

## Live: your real tmux (`bench/live.sh`)

Run inside tmux with the sidebars open:

```bash
bench/live.sh 300              # live numbers, then the offline table above
bench/live.sh 300 --no-offline # live numbers only
```

It samples every 5 s. The first six lines are the sidebars: panes, agents, running sidebar processes (average, max),
their CPU together (100% = one core), average and peak memory (RSS), and how many snapshots were collected.
The next three lines (`running other screens`, `other screens CPU`, `other screens RSS`) are the same measures for
`--select`, `--menu`, `--report` and `--report-text --wait` processes; they are 0 when none is open.
Measured 2026-11-11 on the same machine, 60 s with some interaction: on average 0.6 of these processes ran at a
time, CPU 0.20 %, RSS average 13.3 MB. There are no earlier numbers.

Do not leave another copy of `party.py` running while you measure (for example the plugin directory and a development
checkout at once): copies do not share a snapshot, so collections come out too high. `bench/live.sh` prints a warning
when it sees more than one `party.py` path.

### Now: only visible sidebars run

Measured 2026-11-11 (`bash bench/live.sh 60`): AMD Ryzen 9 5900XT, Linux, tmux 3.8, Python 3.14, 18 sidebar panes,
2 agents, 60 s, Party Select screen open, normal use:

| measure | result |
|---|---|
| running sidebar processes | average 1.1, max 2 |
| CPU, all sidebar processes | 0.18 % of one core |
| memory (RSS), all sidebars | average 23.2 MB, peak 42.3 MB |
| snapshots collected | 31 in 60 s |

Earlier measurement, 24 windows (24 sidebar panes), 4 agents, 300 s, normal use with window switching (many windows
visited, so higher peaks):

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

## Long turn: `claude_live` (ticket 046)

A working turn whose prompt is further back than the last 1 MB of the log (`LIVE_TAIL`) is searched for once per log
and remembered in the process. The search parses every line that contains `"type":"user"` (tool results too: whether a
line is a typed prompt is decided after parsing, by the same rule as for a finished turn). Fake 30 MB log: tool call
and tool result lines alternate, each tool result is one string of plain `x` characters (a real one has more escapes,
which parse slower), and the prompt line sits at the given distance from the end. Median of 30 calls, wall time (CPU
time within 1 %), AMD Ryzen 9 5900XT, Linux, Python 3.14. "Before" is about 2 ms in every row:

| prompt is | tool results of 20 KB: first call | 100 KB: first call | later calls (both) |
|---|---:|---:|---:|
| inside the last 1 MB (0.5 MB back) | 1.7 ms | 1.9 ms | 1.7 / 1.9 ms (same as before) |
| 5 MB back | 11.6 ms | 13.2 ms | 1.75 / 1.94 ms |
| 20 MB back | 35.7 ms | 40.0 ms | 1.75 / 1.93 ms |

`party.py --report-text` is a new process for each call, so it pays the first-call number every time (the search reads
the log back to the prompt). The lookback stops at 32 MB before the last 1 MB; a log whose prompt is further back
costs that search once per process (the miss is remembered too).

## Collection rate with many sidebars (`tests/party-tmux-test.sh`)

The integration test opens 20+ windows on a private tmux server and checks that data is collected at most
6 times in 10 seconds, no matter how many sidebars are open.
