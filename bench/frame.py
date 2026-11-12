"""What a frame costs: where the CPU of the fixed key script (bench/use.py) goes, frame by frame.

  python3 bench/frame.py

About 90 s, no tmux, stdlib only. Same fake outside world as bench/use.py (a fixed snapshot, 70-line reports, images on,
179 x 47); only the measuring process patches product functions, no product file is touched. Parts:
  1. One select frame in this process (`time.perf_counter`, REPS runs, median): `render_select` for a seen, a working and
     an unseen member (first Markdown layout), then the whole loop body of `run_select` split into its pieces, how many
     rows a second frame repeats, and what the Markdown costs when only the rows on screen are laid out.
  2. The idle 5 s on the working member: frames drawn, why each wake happened, CPU per wake split into snapshot, compute,
     write, other. 3. Per k / j press: report_for stub, snapshot, Markdown, rest of the screen, images.
  4. h, Enter, n: fixed cost of entering a screen, draw, images. 5. Process start-up and exit, and `os._exit(0)` instead
     of the normal interpreter shutdown. 6. Writing a whole frame against only the changed rows into a pty (CPU incl.
     the diff). 7. cProfile ranking of the frames.
Parts 2-5 and the final table come from PLAYS concurrent plays of the fixed key script (use.STEPS) in a pty. The child
(`child_main`) is bench/use.py's child with timers around the product functions and a record of every wake: CPU time
(`time.process_time_ns`) between two `select.select` calls is one wake, and the exclusive CPU of the wrapped functions
in it. Every number is the median of the plays.
"""

import fcntl
import importlib
import json
import os
import pty
import select
import statistics
import struct
import subprocess
import sys
import tempfile
import termios
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)

ROWS, COLS = 47, 179
REPS = 30
PLAYS = 3
EXIT_RUNS = 7
PUBLISHED_MS = 224.6
CATS = ("snap", "rfor", "md", "sel", "rep", "anim", "write", "img", "load")
BOOT = "import sys; sys.path.insert(0, sys.argv[1]); import frame; frame.child_main(*sys.argv[2:])"
DRAIN = "import os\nwhile True:\n    try:\n        if not os.read(0, 65536):\n            break\n    except OSError:\n        break\n"
REASONS = {
    (True, True): "time tick + snapshot reread",
    (True, False): "time tick, no reread",
    (False, True): "snapshot reread, frame unchanged",
    (False, False): "other: nothing drawn or read",
}
UI_WRAPS = [
    ("get_snapshot", "snap"),
    ("report_for", "rfor"),
    ("select_roster", "sel"),
    ("select_banner", "sel"),
    ("select_cards", "sel"),
    ("render_select", "sel"),
    ("select_image_plan", "sel"),
    ("report_queue", "rep"),
    ("report_parts", "rep"),
    ("report_view", "rep"),
    ("report_frames", "rep"),
    ("select_images_out", "img"),
    ("report_images", "img"),
    ("report_first_deletes", "img"),
    ("load_images", "load"),
]


def med(xs):
    xs = list(xs)
    return statistics.median(xs) if xs else 0.0


def fx(x, nd=1):
    return "-" if x is None else f"{x:.{nd}f}"


class Timers:
    """Exclusive time of wrapped functions per category: time spent in a wrapped function called from another is the callee's."""

    def __init__(self, clock):
        self.clock = clock
        self.acc: dict[str, int] = {}
        self.count: dict[str, int] = {}
        self.stack: list[list] = []

    def enter(self, cat):
        now = self.clock()
        if self.stack:
            top = self.stack[-1]
            self.acc[top[0]] = self.acc.get(top[0], 0) + now - top[1]
        self.stack.append([cat, now])
        self.count[cat] = self.count.get(cat, 0) + 1

    def exit(self):
        now = self.clock()
        cat, start = self.stack.pop()
        self.acc[cat] = self.acc.get(cat, 0) + now - start
        if self.stack:
            self.stack[-1][1] = now

    def wrap(self, mod, name, cat):
        """Replace mod.name by a timed one; returns the function that puts the original back."""
        fn = getattr(mod, name)

        def inner(*a, **k):
            self.enter(cat)
            try:
                return fn(*a, **k)
            finally:
                self.exit()

        setattr(mod, name, inner)
        return lambda: setattr(mod, name, fn)


def install_fakes(data):
    """bench/use.py's fake outside world, in this process."""
    from party_hud import collect, common, render, sidebars, ui

    ui.get_snapshot = lambda fixture=None: {"towns": data["towns"]}
    ui.report_for = lambda a: data["reports"][a["pane"]]
    ui.capture = lambda *a, **k: ""
    ui.mark_seen = lambda *a: None
    ui.art_supported = lambda *a: True
    fake_tmux = lambda *a: "on" if "@party_anim" in a else ""
    fake_tmux_run = lambda args, timeout=None: (0, "", "")
    ui.tmux = sidebars.tmux = common.tmux = fake_tmux
    common.tmux_run = sidebars.tmux_run = collect.tmux_run = fake_tmux_run
    return ui, render


class Sink:
    """A pty whose output a separate process drains, so the write cost seen here is the writer's alone."""

    def __init__(self):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, COLS * 10, ROWS * 20))
        self.drain = subprocess.Popen(
            [sys.executable, "-c", DRAIN], stdin=master, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        os.close(master)
        self.f = os.fdopen(slave, "w", encoding="utf-8", buffering=1)

    def write(self, s):
        self.f.write(s)

    def flush(self):
        self.f.flush()

    def close(self):
        self.f.close()
        self.drain.kill()
        self.drain.wait()


# ---------------------------------------------------------------- the child of the pty plays


class Rec:
    """One record per wake: CPU between two `select.select` calls and the exclusive CPU of the wrapped functions in it."""

    def __init__(self, tm, render):
        self.tm, self.render = tm, render
        self.iters: list[dict] = []
        self.events: list[list] = []
        self.cur: dict | None = None
        self.screen = ""
        self.frames = 0
        self.in_anim = False
        self.seen_frame = False

    def event(self, name):
        self.events.append([name, time.process_time_ns(), time.monotonic()])

    def open(self, cause):
        self.cur = {
            "t": time.monotonic(),
            "cause": cause,
            "acc0": dict(self.tm.acc),
            "n0": dict(self.tm.count),
            "frames0": self.frames,
            "miss0": self.render._markdown_rows.cache_info().misses,
            "cpu0": time.process_time_ns(),
        }

    def close(self, screen=None):
        cur = self.cur
        if cur is None:
            return
        cpu1 = time.process_time_ns()
        acc = {k: v - cur["acc0"].get(k, 0) for k, v in self.tm.acc.items()}
        self.iters.append(
            {
                "t": cur["t"],
                "cause": cur["cause"],
                "cpu0": cur["cpu0"],
                "cpu": cpu1 - cur["cpu0"],
                "c": {k: v for k, v in acc.items() if v},
                "frames": self.frames - cur["frames0"],
                "snaps": self.tm.count.get("snap", 0) - cur["n0"].get("snap", 0),
                "miss": self.render._markdown_rows.cache_info().misses - cur["miss0"],
                "screen": screen or self.screen,
            }
        )
        self.cur = None


class SelectShim:
    """Stands in for the `select` module of party_hud.ui: every wait ends one wake record and starts the next."""

    def __init__(self, rec):
        self.rec, self.real = rec, select

    def select(self, rl, wl, xl, timeout=None):
        if self.rec.in_anim:
            return self.real.select(rl, wl, xl, timeout)
        self.rec.close()
        result = self.real.select(rl, wl, xl, timeout)
        ready = result[0]
        cause = "key" if rl[0] in ready else "winch" if len(rl) > 1 and rl[1] in ready else "timeout"
        self.rec.open(cause)
        return result

    def __getattr__(self, name):
        return getattr(self.real, name)


class Out:
    """sys.stdout with the write and flush time counted (image sequences apart from frames)."""

    def __init__(self, f, rec):
        self.f, self.rec, self.cat, self.arm = f, rec, "write", False

    def write(self, s):
        if s.startswith("\033[H"):
            self.rec.frames += 1
            if not self.rec.seen_frame:
                self.rec.seen_frame = self.arm = True
        self.cat = "img" if "_G" in s else "write"
        self.rec.tm.enter(self.cat)
        try:
            return self.f.write(s)
        finally:
            self.rec.tm.exit()

    def flush(self):
        self.rec.tm.enter(self.cat)
        try:
            self.f.flush()
        finally:
            self.rec.tm.exit()
        if self.arm:
            self.arm = False
            self.rec.event("first frame")

    def __getattr__(self, name):
        return getattr(self.f, name)


def child_main(data_path, rec_path, exit_mode):
    """bench/use.py's child with timers and a wake record. exit_mode "os_exit" leaves with os._exit(0) after the record is written."""
    t_entry = time.process_time_ns()
    from party_hud import collect, render, ui

    with open(data_path) as f:
        data = json.load(f)
    install_fakes(data)
    real_run = subprocess.run

    def run(args, *a, **k):
        if args and args[0] == "tmux":
            raise RuntimeError(f"bench child started tmux: {args}")
        return real_run(args, *a, **k)

    subprocess.run = run
    del collect
    tm = Timers(time.process_time_ns)
    rec = Rec(tm, render)
    for name, cat in UI_WRAPS:
        tm.wrap(ui, name, cat)
    tm.wrap(render, "render_markdown", "md")
    real_anim = ui.play_report_anim

    def anim(*a, **k):
        rec.in_anim = True
        tm.enter("anim")
        try:
            return real_anim(*a, **k)
        finally:
            tm.exit()
            rec.in_anim = False

    ui.play_report_anim = anim
    real_select, real_report = ui.run_select, ui.run_report

    def screen(name, fn, *args):
        rec.event("enter " + name)
        rec.screen = name
        try:
            return fn(*args)
        finally:
            rec.screen = ""
            rec.event("leave " + name)

    ui.run_select = lambda sel=None, fixture=None, images=None: screen(
        "select", real_select, sel or data["working"], fixture, images
    )
    ui.run_report = lambda pane=None, fixture=None, back=False, images=None: screen(
        "report", real_report, pane, fixture, back, images
    )
    ui.select = SelectShim(rec)
    real_stdout = sys.stdout
    sys.stdout = Out(real_stdout, rec)
    t_ready = time.process_time_ns()
    rec.open("start")
    ui.run_menu()
    rec.close("close")
    with open(rec_path, "w") as f:
        json.dump({"t_entry": t_entry, "t_ready": t_ready, "iters": rec.iters, "events": rec.events}, f)
    if exit_mode == "os_exit":
        real_stdout.flush()
        os._exit(0)


# ---------------------------------------------------------------- parts 1, 6, 7: this process


def cut_report(report, n):
    """The report with its Markdown source cut to n lines (the preview of a working member shows the previous report)."""
    if report.get("live"):
        prev = report["prev"]
        return dict(report, prev=dict(prev, text="\n".join(prev["text"].split("\n")[:n])))
    return dict(report, text="\n".join(report["text"].split("\n")[:n]))


def source_lines(report):
    return len((report["prev"] if report.get("live") else report)["text"].split("\n"))


class Scene:
    def __init__(self, data):
        self.data = data
        self.ui, self.render = install_fakes(data)
        self.art = self.ui.load_art()
        self.towns = data["towns"]
        self.roster = self.render.select_roster(self.towns)
        self.panes = [a["pane"] for t in self.towns for a in t["agents"]]
        banner = self.ui.select_banner(COLS - 1, ROWS, self.ui.cell_ratio())
        assert banner
        self.title = [
            " " * banner[3] + self.ui.image_row(self.ui.select_banner_id(banner[2]), r, banner[0])
            for r in range(banner[1])
        ]

    def select(self, sel, now, cut=None):
        """`render_select` as `run_select` calls it."""
        report = self.data["reports"][sel]
        if cut:
            report = cut_report(report, cut)
        return self.render.render_select(
            self.roster, self.towns, sel, COLS - 1, ROWS, report, now, self.title, True, []
        )

    def loop_frame(self, sel, now, cached, sink, marks):
        """The body of `run_select`'s loop for one frame (no waiting, a frame is always written). Returns the preview cache."""
        ui = self.ui
        towns = ui.get_snapshot()["towns"]
        roster = ui.select_roster(towns)
        shared = {ui.portrait_id(a) for _, a, _ in roster}
        width = COLS - 1
        ui.set_tick(int(now))
        banner = ui.select_banner(width, ROWS, ui.cell_ratio())
        plan, title, head_rows = [], None, 1
        if banner:
            head_rows = banner[1]
            pad = " " * banner[3]
            title = [pad + ui.image_row(ui.select_banner_id(banner[2]), r, banner[0]) for r in range(head_rows)]
            plan = ui.select_title_plan(self.art, banner, ui.select_layout(ROWS, head_rows)[2])
        body_h = ui.select_layout(ROWS, head_rows)[3]
        lw, preview = ui.select_widths(width)
        report = None
        if sel and preview:
            a = next(m for _, m, _ in roster if m["pane"] == sel)
            if ui.select_reread(cached, a, time.monotonic()):
                report = ui.report_for(a)
                peek = ui.report_peek({}, a["pane"], report, None, lambda p: ui.capture(p, color=True))
                cached = ((a["pane"], a["round"]), report, peek, time.monotonic())
            report = cached[1]
        plan += ui.select_image_plan(ui.select_cards(roster, sel, lw, body_h, True), self.art)
        rows = ui.render_select(roster, towns, sel, width, ROWS, report, now, title, True, cached[2])
        t = time.perf_counter()
        frame = "\n".join(rows)
        anchors = (
            [ui.SECOND]
            if any(m["status"] == "working" or (m["hp"] is not None and m["hp"] <= 10) for _, m, _ in roster)
            else []
        )
        if sel and preview and report:
            cur = next(m for _, m, _ in roster if m["pane"] == sel)
            if cur["status"] == "waiting" and report.get("end"):
                anchors.append(ui.time_anchor(report["end"], now))
            elif cur["status"] == "working" and report.get("live") and report.get("start"):
                anchors.append(ui.time_anchor(report["start"], now))
        ui.tick_wait(now, anchors)
        changed = frame != ""
        t1 = time.perf_counter()
        if changed:
            sink.write("\033[H" + "\033[K\n".join(frame.split("\n")) + "\033[K\033[J")
            sink.flush()
        marks["join"] = marks.get("join", 0.0) + t1 - t
        marks["write"] = marks.get("write", 0.0) + time.perf_counter() - t1
        del shared
        return cached


def sample_ms(fn, before=None, n=REPS):
    for _ in range(3):
        if before:
            before()
        fn()
    out = []
    for _ in range(n):
        if before:
            before()
        t = time.perf_counter()
        fn()
        out.append(time.perf_counter() - t)
    return statistics.median(out) * 1000


# (attribute, category) pairs timed inside one frame, in party_hud.ui and party_hud.render
FRAME_UI = [
    ("select_roster", "roster"),
    ("select_banner", "title"),
    ("image_row", "title"),
    ("select_cards", "plan"),
    ("render_select", "rs"),
]
FRAME_RENDER = [
    ("select_view", "view"),
    ("card", "card"),
    ("select_card", "cardwrap"),
    ("select_row", "cardwrap"),
    ("select_preview", "pre"),
    ("report_rows", "rows"),
    ("render_markdown", "md"),
    ("select_summary", "sumhint"),
    ("hint_line", "sumhint"),
]
PIECES = [
    ("roster", "select_roster (roster order)"),
    ("title", "banner: select_banner + image_row"),
    ("plan", "select_cards (which cards are on screen)"),
    ("view", "select_view (layout; its card() calls counted in card)"),
    ("card", "card() all calls"),
    ("cardwrap", "select_card + select_row (key cell, row join)"),
    ("pre", "select_preview (header rows, ask text, padding)"),
    ("rows", "report_rows (excl. Markdown)"),
    ("md", "render_markdown (Markdown layout)"),
    ("sumhint", "select_summary + hint_line"),
    ("rs", "render_select (rest: pad_to, column join)"),
    ("join", "join + anchors + compare with last frame"),
    ("write", "write + flush to a pty"),
]


def part1(sc, sink, emit):
    render = sc.render
    seen, working, unseen = sc.panes[1], sc.data["working"], sc.panes[2]
    cases = [
        ("seen member", seen, False),
        ("working member", working, False),
        ("unseen member, first layout", unseen, True),
    ]
    now = time.time()
    clear = render.clear_markdown_cache
    r_ms = {}
    for name, sel, fresh in cases:
        r_ms[name] = sample_ms(lambda sel=sel: sc.select(sel, now), clear if fresh else None)
    emit(1, f"select frame, seen member: {r_ms['seen member']:.2f} ms")
    emit(1, f"select frame, working member: {r_ms['working member']:.2f} ms  (render_select only)")
    emit(1, f"select frame, unseen member, first layout: {r_ms['unseen member, first layout']:.2f} ms")
    emit(1, "")
    emit(1, f"One whole frame = the loop body of run_select, written to a pty (ms, median of {REPS})")
    loops = {}
    for name, sel, fresh in cases:
        state = {"cached": (None, None, [], 0.0)}

        def run(marks, sel=sel, fresh=fresh, state=state):
            if fresh:
                clear()
                state["cached"] = (None, None, [], 0.0)
            state["cached"] = sc.loop_frame(sel, now, state["cached"], sink, marks)

        for _ in range(3):
            run({})
        out = []
        for _ in range(REPS):
            t = time.perf_counter()
            run({})
            out.append(time.perf_counter() - t)
        loops[name] = (run, statistics.median(out) * 1000)
    per = {}
    counts = {}
    for name, (run, _) in loops.items():
        tm = Timers(time.perf_counter_ns)
        undo = [tm.wrap(sc.ui, n, c) for n, c in FRAME_UI] + [tm.wrap(render, n, c) for n, c in FRAME_RENDER]
        reps, wrapped = [], []
        try:
            for _ in range(REPS):
                before, n0 = dict(tm.acc), dict(tm.count)
                marks = {}
                t = time.perf_counter_ns()
                run(marks)
                wrapped.append((time.perf_counter_ns() - t) / 1e6)
                d = {k: (v - before.get(k, 0)) / 1e6 for k, v in tm.acc.items()}
                d["join"], d["write"] = marks["join"] * 1000, marks["write"] * 1000
                reps.append(d)
                counts[name] = {k: v - n0.get(k, 0) for k, v in tm.count.items()}
        finally:
            for u in undo:
                u()
        per[name] = ({k: med(d.get(k, 0.0) for d in reps) for k, _ in PIECES}, med(wrapped))
    names = [c[0] for c in cases]
    emit(1, f"  {'':<56}" + "".join(f"{n.split(',')[0]:>16}" for n in names))
    emit(1, f"  {'whole frame (no timers)':<56}" + "".join(f"{loops[n][1]:16.2f}" for n in names))
    for key, label in PIECES:
        emit(1, f"  {label:<56}" + "".join(f"{per[n][0][key]:16.2f}" for n in names))
    rest = {n: per[n][1] - sum(per[n][0].values()) for n in names}
    emit(1, f"  {'rest of the loop body (not timed)':<56}" + "".join(f"{rest[n]:16.2f}" for n in names))
    emit(
        1,
        f"  {'whole frame with timers (wrapper overhead included)':<56}" + "".join(f"{per[n][1]:16.2f}" for n in names),
    )
    emit(1, f"  {'card() calls per frame':<56}" + "".join(f"{counts[n].get('card', 0):16d}" for n in names))
    emit(1, f"  {'render_markdown calls per frame':<56}" + "".join(f"{counts[n].get('md', 0):16d}" for n in names))
    emit(1, "")
    emit(1, "Second frame of the same member, one tick later (rows identical to the first frame)")
    for name, sel in (("working member", working), ("seen member", seen)):
        a, b = sc.select(sel, now), sc.select(sel, now + 1)
        c = sc.select(sel, now)
        same = sum(x == y for x, y in zip(a, b))
        emit(
            1,
            f"  {name}: {same} of {len(a)} rows identical = {100 * same / len(a):.0f} %, changed rows "
            f"{[i for i, (x, y) in enumerate(zip(a, b)) if x != y]}; same instant again: {sum(x == y for x, y in zip(a, c))} of {len(a)}",
        )
    emit(1, "")
    # Markdown laid out only as far as the preview shows
    out = {}
    for name, sel in (("unseen member", unseen), ("working member, previous report", working)):
        report = sc.data["reports"][sel]
        base = sc.select(sel, now)
        n_cut = source_lines(report)
        for n in range(5, source_lines(report) + 1):
            rows = sc.select(sel, now, n)
            if sum(x != y for x, y in zip(base, rows)) <= 1:
                n_cut = n
                break
        full = sample_ms(lambda sel=sel: sc.select(sel, now), clear)
        cutd = sample_ms(lambda sel=sel, n=n_cut: sc.select(sel, now, n), clear)
        out[name] = (n_cut, source_lines(report), full, cutd)
    emit(1, "Markdown laid out only as far as the preview shows (source cut to the fewest lines that leave the rows on")
    emit(1, "screen unchanged except the '... N more lines' row; first layout, render_select only, ms)")
    for name, (n_cut, n_all, full, cutd) in out.items():
        emit(1, f"  {name}: {n_cut} of {n_all} source lines: {full:.2f} -> {cutd:.2f} ms, saves {full - cutd:.2f} ms")
    return r_ms, out


def write_cost(sink, old, new):
    def do_full():
        frame = "\n".join(new)
        sink.write("\033[H" + "\033[K\n".join(frame.split("\n")) + "\033[K\033[J")
        sink.flush()

    def do_diff():
        out = "".join(f"\033[{i + 1};1H{r}\033[K" for i, (o, r) in enumerate(zip(old, new)) if o != r)
        if out:
            sink.write(out)
            sink.flush()

    def cpu_us(fn):
        for _ in range(20):
            fn()
        out = []
        for _ in range(5):
            t = time.process_time()
            for _ in range(100):
                fn()
            out.append((time.process_time() - t) / 100 * 1e6)
        return statistics.median(out)

    full_bytes = len(("\033[H" + "\033[K\n".join("\n".join(new).split("\n")) + "\033[K\033[J").encode())
    diff_bytes = len("".join(f"\033[{i + 1};1H{r}\033[K" for i, (o, r) in enumerate(zip(old, new)) if o != r).encode())
    changed = sum(o != r for o, r in zip(old, new))
    return changed, full_bytes, diff_bytes, cpu_us(do_full), cpu_us(do_diff)


def part6(sc, sink, emit):
    now = time.time()
    working, seen, other = sc.data["working"], sc.panes[1], sc.panes[2]
    cases = [
        ("tick, working member selected", sc.select(working, now), sc.select(working, now + 1)),
        ("tick, seen member selected", sc.select(seen, now), sc.select(seen, now + 1)),
        ("j: cursor to the next seen member", sc.select(seen, now), sc.select(other, now)),
    ]
    emit(6, "Writing a frame into a pty: the whole frame against only the changed rows (cursor-addressed). CPU is")
    emit(6, "time.process_time of this process per frame, the diff is computed inside the timed call; the pty is")
    emit(6, "drained by another process.")
    emit(6, f"  {'case':<38}{'rows':>6}{'full B':>9}{'diff B':>9}{'full us':>9}{'diff us':>9}{'diff/full':>11}")
    res = {}
    for name, old, new in cases:
        changed, fb, db, fu, du = write_cost(sink, old, new)
        res[name] = (fu, du)
        emit(6, f"  {name:<38}{changed:>3}/{len(new):<2}{fb:>9}{db:>9}{fu:>9.0f}{du:>9.0f}{du / fu:>11.2f}")
    return res


def part7(sc, sink, emit):
    import cProfile
    import io
    import pstats

    now = time.time()
    render = sc.render
    seen, working, unseen = sc.panes[1], sc.data["working"], sc.panes[2]
    state = {"cached": (None, None, [], 0.0)}

    def k_press():
        render.clear_markdown_cache()
        state["cached"] = sc.loop_frame(unseen, now, (None, None, [], 0.0), sink, {})

    cases = [
        ("render_select, seen member", lambda: sc.select(seen, now), None),
        ("render_select, working member", lambda: sc.select(working, now), None),
        (
            "render_select, unseen member (cleared Markdown cache)",
            lambda: sc.select(unseen, now),
            render.clear_markdown_cache,
        ),
        ("one k: whole loop frame on an unseen member", k_press, None),
    ]
    emit(
        7, "cProfile, 10 frames per table, top 12 by cumulative time. The profiler adds a fixed cost to every call, so"
    )
    emit(7, "it inflates per-character helpers: read the RANKING only, not the seconds.")
    for name, fn, before in cases:
        fn()
        if before:
            before()
        pr = cProfile.Profile()
        pr.enable()
        for _ in range(10):
            if before:
                before()
            fn()
        pr.disable()
        s = io.StringIO()
        pstats.Stats(pr, stream=s).strip_dirs().sort_stats("cumulative").print_stats(12)
        lines = [l for l in s.getvalue().split("\n") if l.strip()]
        emit(7, "")
        emit(7, f"[{name}]")
        for l in lines:
            if l.lstrip().startswith("Ordered by") or l.lstrip().startswith("List reduced"):
                continue
            emit(7, "  " + l)


# ---------------------------------------------------------------- parts 2-5: the plays


def play_main(data_path, work):
    """One run of bench/use.py's STEPS with the recording child; writes work/result.json."""
    from use import EXIT_WAIT, STEPS, Child, cpu_seconds

    steps, procs = [], []
    child, cpu_prev = None, 0.0
    try:
        for name, keys, secs, spawn, wait_exit in STEPS:
            t_step = time.monotonic()
            if spawn:
                rec = os.path.join(work, f"rec{len(procs)}.json")
                child = Child([sys.executable, "-c", BOOT, HERE, data_path, rec, "normal"])
                procs.append({"rec": rec, "cpu_ms": None})
                cpu_prev = 0.0
            assert child
            written_prev, t0 = child.written, time.monotonic()
            pending = list(keys)
            while True:
                now = time.monotonic() - t0
                while pending and now >= pending[0][0]:
                    os.write(child.master, pending.pop(0)[1].encode())
                if child.poll():
                    if not wait_exit or pending:
                        raise RuntimeError(f"child exited early in step {name!r}: {child.tail!r}")
                    break
                if not pending and now >= secs and not wait_exit:
                    break
                if wait_exit and not pending and now >= secs + EXIT_WAIT:
                    raise RuntimeError(f"child did not exit after step {name!r}: {child.tail!r}")
                due = pending[0][0] if pending else secs
                child.read(max(0.0, min(0.05, due - now)))
            if wait_exit:
                while child.open and select.select([child.master], [], [], 0)[0]:
                    child.read(0)
                usage = child.rusage
                assert usage
                cpu = usage.ru_utime + usage.ru_stime
                procs[-1]["cpu_ms"] = cpu * 1000
                child.kill()
            else:
                cpu = cpu_seconds(child.proc.pid)
            steps.append(
                {
                    "name": name,
                    "keys": len(keys),
                    "t0": t_step,
                    "t1": time.monotonic(),
                    "cpu_ms": (cpu - cpu_prev) * 1000,
                    "out_kb": (child.written - written_prev) / 1024,
                }
            )
            cpu_prev = cpu
    finally:
        if child:
            child.kill()
    with open(os.path.join(work, "result.json"), "w") as f:
        json.dump({"steps": steps, "procs": procs}, f)


def load_play(work):
    with open(os.path.join(work, "result.json")) as f:
        res = json.load(f)
    its = []
    for pi, p in enumerate(res["procs"]):
        with open(p["rec"]) as f:
            p["data"] = json.load(f)
        for it in p["data"]["iters"]:
            step = [s for s in res["steps"] if s["t0"] <= it["t"]][-1]
            its.append(dict(it, proc=pi, step=step["name"]))
    res["its"] = its
    return res


def check_play(res):
    """None when every step saw exactly its keys as wakes, else a reason."""
    for s in res["steps"]:
        n = sum(1 for it in res["its"] if it["step"] == s["name"] and it["cause"] == "key")
        if n != s["keys"]:
            return f"step {s['name']!r}: {n} key wakes for {s['keys']} keys"
    return None


def it_metrics(M, prefix, xs):
    """Median per wake of the categories, in ms."""
    M[prefix + "|n"] = len(xs)
    if not xs:
        return
    M[prefix + "|cpu"] = med(x["cpu"] / 1e6 for x in xs)
    for c in CATS:
        M[f"{prefix}|{c}"] = med(x["c"].get(c, 0) / 1e6 for x in xs)
    M[prefix + "|other"] = med((x["cpu"] - sum(x["c"].values())) / 1e6 for x in xs)
    M[prefix + "|miss"] = med(x["miss"] for x in xs)


def leave_entry(res, it):
    """(CPU from the key to the old screen's exit, CPU from the new screen's entry to its first wait), ms."""
    evs = res["procs"][it["proc"]]["data"]["events"]
    end = it["cpu0"] + it["cpu"]
    inside = [e for e in evs if it["cpu0"] <= e[1] <= end]
    leave = next((e for e in inside if e[0].startswith("leave")), None)
    enter = next((e for e in inside if e[0].startswith("enter")), None)
    return (leave[1] - it["cpu0"]) / 1e6 if leave else None, (end - enter[1]) / 1e6 if enter else None


def summarize(res, inst):
    M = {}
    its = res["its"]
    for s in res["steps"]:
        name = s["name"]
        xs = [x for x in its if x["step"] == name]
        M[f"{name}|cpu"] = s["cpu_ms"]
        M[f"{name}|kb"] = s["out_kb"]
        M[f"{name}|its"] = sum(x["cpu"] for x in xs) / 1e6
        M[f"{name}|wakes"] = len(xs)
        M[f"{name}|frames"] = sum(x["frames"] for x in xs)
        for c in CATS:
            M[f"{name}|sum {c}"] = sum(x["c"].get(c, 0) for x in xs) / 1e6
        M[f"{name}|sum other"] = M[f"{name}|its"] - sum(M[f"{name}|sum {c}"] for c in CATS)
        M[f"{name}|outside"] = s["cpu_ms"] - M[f"{name}|its"]
        keyed = [x for x in xs if x["cause"] == "key"]
        timed = [x for x in xs if x["cause"] == "timeout"]
        it_metrics(M, f"key|{name}", keyed)
        it_metrics(M, f"tick|{name}", timed)
        if keyed and name in ("h, back to select", "Enter, open report", "n, next member"):
            lv, en = leave_entry(res, keyed[0])
            if lv is not None:
                M[f"key|{name}|leave"] = lv
            if en is not None:
                M[f"key|{name}|entry"] = en
        if name == "idle on working":
            for (wrote, snap), label in REASONS.items():
                it_metrics(M, f"idle|{label}", [x for x in timed if (x["frames"] > 0, x["snaps"] > 0) == (wrote, snap)])
    parts = {"kai": 0.0, "sel": 0.0, "rep": 0.0, "md": 0.0}
    total = 0.0
    for pi, p in enumerate(res["procs"]):
        d = p["data"]
        xs = [x for x in its if x["proc"] == pi]
        first, last = xs[0], xs[-1]
        ff = next(e for e in d["events"] if e[0] == "first frame")
        t_end = (last["cpu0"] + last["cpu"]) / 1e6
        pre = f"proc{pi}"
        M[f"{pre}|python + frame.py"] = d["t_entry"] / 1e6
        M[f"{pre}|imports + patches"] = (d["t_ready"] - d["t_entry"]) / 1e6
        M[f"{pre}|first frame at"] = ff[1] / 1e6
        M[f"{pre}|first wake"] = first["cpu"] / 1e6
        M[f"{pre}|first wake after frame"] = (first["cpu0"] + first["cpu"] - ff[1]) / 1e6
        M[f"{pre}|first wake img"] = first["c"].get("img", 0) / 1e6
        M[f"{pre}|first wake load"] = first["c"].get("load", 0) / 1e6
        M[f"{pre}|close wake"] = last["cpu"] / 1e6
        M[f"{pre}|close write"] = last["c"].get("write", 0) / 1e6
        M[f"{pre}|cpu at end of record"] = t_end
        M[f"{pre}|total"] = p["cpu_ms"]
        M[f"{pre}|shutdown"] = p["cpu_ms"] - t_end - inst["dump"]
        total += p["cpu_ms"]
        parts["kai"] += (
            d["t_entry"] / 1e6
            - inst["load"]
            + (d["t_ready"] - d["t_entry"]) / 1e6
            + sum(x["c"].get("load", 0) for x in xs) / 1e6
            + last["cpu"] / 1e6
            + M[f"{pre}|shutdown"]
        )
        for x in xs:
            md = x["c"].get("md", 0) / 1e6
            parts["md"] += md
            if x["screen"] == "select":
                parts["sel"] += x["cpu"] / 1e6 - md - x["c"].get("load", 0) / 1e6
            elif x["screen"] == "report":
                parts["rep"] += x["cpu"] / 1e6 - md
    n_proc = len(res["procs"])
    M["rec|total"] = total
    M["rec|kai"], M["rec|sel"], M["rec|md"], M["rec|rep"] = parts["kai"], parts["sel"], parts["md"], parts["rep"]
    M["rec|measurement"] = n_proc * (inst["load"] + inst["dump"])
    M["rec|other"] = total - sum(parts.values()) - M["rec|measurement"]
    return M


def merge(ms):
    keys = {k for m in ms for k in m}
    return {k: statistics.median([m[k] for m in ms if k in m]) for k in keys}


def run_plays(data_path, tmp):
    done = []
    for i in range(PLAYS):
        work = os.path.join(tmp, f"play{i}")
        os.mkdir(work)
        subprocess.run([sys.executable, os.path.abspath(__file__), "--play", data_path, work], check=True, timeout=60)
        done.append(work)
    return [load_play(w) for w in done]


def exit_trials(data_path, tmp):
    """Child CPU of open -> first frame and images -> q, with the normal exit and with os._exit(0); alternating."""
    from use import Child

    cpus = {"normal": [], "os_exit": []}
    for i in range(EXIT_RUNS):
        for mode in ("normal", "os_exit"):
            child = Child([sys.executable, "-c", BOOT, HERE, data_path, os.path.join(tmp, f"exit{i}{mode}.json"), mode])
            try:
                last, quiet, t_end = -1, time.monotonic(), time.monotonic() + 15
                while True:
                    child.read(0.05)
                    if child.written != last:
                        last, quiet = child.written, time.monotonic()
                    elif last > 0 and time.monotonic() - quiet >= 0.2:
                        break
                    if time.monotonic() > t_end:
                        raise RuntimeError(f"no first frame: {child.tail!r}")
                os.write(child.master, b"q")
                t_end = time.monotonic() + 10
                while not child.poll():
                    child.read(0.05)
                    if time.monotonic() > t_end:
                        raise RuntimeError("child did not exit")
                usage = child.rusage
                assert usage
                cpus[mode].append((usage.ru_utime + usage.ru_stime) * 1000)
            finally:
                child.kill()
    return {m: statistics.median(v) for m, v in cpus.items()}


def cpu_of(args, runs=7):
    out = []
    for _ in range(runs):
        p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        usage = os.wait4(p.pid, 0)[2]
        p.returncode = 0
        out.append((usage.ru_utime + usage.ru_stime) * 1000)
    return statistics.median(out)


def instrumentation(res):
    """(ms to import this file in a child beyond bench/use.py, ms to write one child's record)."""

    def import_cpu(module):
        code = f"import sys; sys.path.insert(0, {HERE!r}); sys.path.insert(0, {ROOT!r}); import {module}"
        return cpu_of([sys.executable, "-c", code])

    bare = cpu_of([sys.executable, "-c", "pass"])
    harness, mine, product = import_cpu("use"), import_cpu("frame"), import_cpu("party_hud.ui")
    payload = res["procs"][0]["data"]
    out = []
    for _ in range(20):
        t = time.process_time()
        with open(os.path.join(tempfile.gettempdir(), f"party-frame-dump-{os.getpid()}.json"), "w") as f:
            json.dump(payload, f)
        out.append((time.process_time() - t) * 1000)
    os.unlink(os.path.join(tempfile.gettempdir(), f"party-frame-dump-{os.getpid()}.json"))
    return {
        "load": max(mine - harness, 0.0),
        "dump": statistics.median(out),
        "bare": bare,
        "harness": harness - bare,
        "product": product - bare,
    }


# ---------------------------------------------------------------- printing


def print_steps(M, steps, emit):
    emit(
        0,
        "Per step, child CPU in ms (median of the plays). cpu = as bench/use.py measures it; wakes = records in the step;",
    )
    emit(0, "the other columns are the exclusive CPU of the wrapped functions summed over the step's wakes.")
    head = f"  {'step':<20}{'cpu':>7}{'out KB':>8}{'wakes':>7}{'frames':>7}{'snap':>6}{'md':>6}{'sel':>6}{'rep':>6}{'anim':>6}{'write':>7}{'img':>6}{'load':>6}{'other':>7}{'outside':>8}"
    emit(0, head)
    for s in steps:
        n = s["name"]
        g = lambda k, n=n: M.get(f"{n}|{k}", 0.0)
        emit(
            0,
            f"  {n:<20}{g('cpu'):>7.1f}{g('kb'):>8.1f}{g('wakes'):>7.0f}{g('frames'):>7.0f}{g('sum snap'):>6.1f}{g('sum md'):>6.1f}"
            f"{g('sum sel'):>6.1f}{g('sum rep'):>6.1f}{g('sum anim'):>6.1f}{g('sum write'):>7.1f}{g('sum img'):>6.1f}"
            f"{g('sum load'):>6.1f}{g('sum other'):>7.1f}{g('outside'):>8.1f}",
        )
    step_total = sum(M.get(f"{s['name']}|cpu", 0.0) for s in steps)
    emit(0, f"  {'total':<20}{step_total:>7.1f}   (bench/use.py: {PUBLISHED_MS} ms)")
    emit(
        0,
        "  outside = step CPU not inside any wake: process start-up and imports before the first wake, exit after the last.",
    )


def row(M, prefix, cols):
    return "".join(f"{fx(M.get(f'{prefix}|{c}'), 2):>12}" for c in cols)


def print_parts(M, steps, extra, exits, inst, emit, plays, skipped):
    emit(2, f"Idle on the working member, 5 s window; {plays} plays ({skipped} dropped), real run_select in a pty.")
    name = "idle on working"
    frames = round(M[f"{name}|frames"])
    emit(2, f"idle on working, 5 s: {frames} frames, {M[f'{name}|cpu']:.1f} ms")
    emit(
        2,
        f"  (the same window summed from the wake records: {M[f'{name}|its']:.1f} ms in {M[f'{name}|wakes']:.0f} wakes)",
    )
    emit(
        2,
        f"  {'why it woke':<36}{'wakes':>6}{'cpu/wake':>10}{'snapshot':>10}{'compute':>9}{'write':>7}{'other':>7}   (ms, median per wake)",
    )
    for label in REASONS.values():
        p = f"idle|{label}"
        if M.get(p + "|n", 0) == 0:
            continue
        compute = M[p + "|md"] + M[p + "|sel"] + M[p + "|rep"]
        other = M[p + "|cpu"] - M[p + "|snap"] - compute - M[p + "|write"]
        emit(
            2,
            f"  {label:<36}{M[p + '|n']:>6.0f}{M[p + '|cpu']:>10.2f}{M[p + '|snap']:>10.2f}{compute:>9.2f}{M[p + '|write']:>7.2f}{other:>7.2f}",
        )
    emit(
        2, "  compute = select compute (roster, cards, render_select) + Markdown + report; other = what no timer covers"
    )
    emit(2, "  (get_terminal_size, tick math, string joins, the select call itself).")

    emit(
        3,
        "Per key press (median over the presses of the plays), ms. report_for is bench/use.py's dict lookup: the real",
    )
    emit(
        3,
        "reading and parsing of the agent's log is NOT in the fixed script and was not measured (it needs real logs).",
    )
    cols = ("cpu", "rfor", "snap", "md", "sel", "write", "img", "other", "miss")
    emit(
        3,
        f"  {'press':<26}"
        + "".join(
            f"{c:>12}"
            for c in (
                "cpu",
                "report_for",
                "snapshot",
                "markdown",
                "select calc",
                "write",
                "images",
                "other",
                "md misses",
            )
        ),
    )
    for label, step in (("k, new member", "k x4, new members"), ("j, seen member", "j x3, seen members")):
        emit(3, f"  {label:<26}" + row(M, f"key|{step}", cols))
    for label, step in (("tick in the k step", "k x4, new members"), ("tick in the j step", "j x3, seen members")):
        emit(3, f"  {label:<26}" + row(M, f"tick|{step}", cols) + f"   ({M.get(f'tick|{step}|n', 0):.0f} ticks)")
    emit(3, "  select calc = select_roster, select_banner, select_cards, render_select without the Markdown;")
    emit(3, "  write = frame write+flush; images = kitty sequences (none after the first frame while the cards stay).")
    for l in extra["cut"]:
        emit(3, l)

    emit(
        4,
        "h, Enter and n: the wake of the key press, ms (median). leave = key until the old screen has exited (tcsetattr,",
    )
    emit(
        4,
        "exit write); entry = new screen's set-up until its first wait (fixed cost + first frame + images + animation).",
    )
    cols4 = ("cpu", "leave", "entry", "other", "sel", "rep", "md", "write", "img", "anim", "snap")
    emit(
        4,
        f"  {'step':<22}"
        + "".join(
            f"{c:>9}"
            for c in (
                "cpu",
                "leave",
                "entry",
                "other",
                "select",
                "report",
                "markdown",
                "write",
                "images",
                "anim",
                "snapshot",
            )
        ),
    )
    for step in ("h, back to select", "Enter, open report", "n, next member", "scroll j j j k k"):
        p = f"key|{step}"
        emit(4, f"  {step:<22}" + "".join(f"{fx(M.get(f'{p}|{c}'), 2):>9}" for c in cols4))
    emit(
        4,
        "  other = the part of the wake no timer covers = the fixed cost of entering/leaving (tmux queries are faked: ~0),",
    )
    emit(4, "  os.pipe/signal/termios set-up, get_terminal_size, string work. Wakes after the key in the same step:")
    for step in ("h, back to select", "Enter, open report", "n, next member"):
        n_all, n_key = M.get(f"{step}|wakes", 0), M.get(f"key|{step}|n", 0)
        emit(
            4,
            f"  {step:<22} {n_all - n_key:.0f} more wakes, {M.get(f'{step}|its', 0) - M.get(f'key|{step}|cpu', 0) * n_key:.2f} ms",
        )

    emit(5, "Process start and exit (child CPU, ms, median).")
    emit(
        5,
        f"  Start-up pieces measured on their own (fresh processes): bare python3 {inst['bare']:.1f} ms; product imports"
        f" (import party_hud.ui) +{inst['product']:.1f} ms; this harness's stdlib imports (as bench/use.py) +{inst['harness']:.1f} ms;",
    )
    emit(
        5,
        "  the last two overlap (shared stdlib modules), so below 'python start' and 'imports' split by order, not by owner.",
    )
    for pi, label in ((0, "open select (first child)"), (1, "reopen, then q (second child)")):
        p = f"proc{pi}"
        emit(5, f"  {label}")
        emit(
            5,
            f"    python start + this file's load {M[p + '|python + frame.py']:6.1f}   (this file's own load is measured noise: {inst['load']:.1f} ms, taken out below)",
        )
        emit(5, f"    imports + patches             {M[p + '|imports + patches']:6.1f}")
        emit(5, f"    first frame written at CPU    {M[p + '|first frame at']:6.1f}   (since process start)")
        emit(
            5,
            f"    first wake                    {M[p + '|first wake']:6.1f}   = load_images {M[p + '|first wake load']:.1f} + images {M[p + '|first wake img']:.1f} + the frame and the rest",
        )
        emit(
            5,
            f"    after the first frame, same wake {M[p + '|first wake after frame']:6.1f}   (images and set-up, before its first wait)",
        )
        emit(
            5,
            f"    close wake (q)                {M[p + '|close wake']:6.1f}   of which exit write {M[p + '|close write']:.2f}",
        )
        emit(
            5,
            f"    interpreter shutdown          {M[p + '|shutdown']:6.1f}   (child total {M[p + '|total']:.1f} - record end {M[p + '|cpu at end of record']:.1f} - record dump {inst['dump']:.1f})",
        )
    open_step, re_step = "open select", "reopen, then q"
    after = M[f"{open_step}|cpu"] - M["proc0|first frame at"]
    emit(
        5,
        f"  open select: step CPU {M[open_step + '|cpu']:.1f} ms, first frame at {M['proc0|first frame at']:.1f}; after the first frame {after:.1f} ms:",
    )
    emit(
        5,
        f"    rest of the first wake {M['proc0|first wake after frame']:.1f} + {M[open_step + '|wakes'] - 1:.0f} later wakes {M[open_step + '|its'] - M['proc0|first wake']:.1f}",
    )
    for l in extra["open"]:
        emit(5, l)
    d = M[f"{re_step}|cpu"] - M[f"{open_step}|cpu"]
    ticks_re = M[f"{re_step}|its"] - M["proc1|first wake"] - M["proc1|close wake"]
    ticks_op = M[f"{open_step}|its"] - M["proc0|first wake"]
    emit(5, f"  reopen, then q ({M[re_step + '|cpu']:.1f}) - open select ({M[open_step + '|cpu']:.1f}) = {d:.1f} ms:")
    emit(
        5,
        f"    close wake {M['proc1|close wake']:.1f} + interpreter shutdown {M['proc1|shutdown']:.1f} + record dump {inst['dump']:.1f} (measurement)",
    )
    emit(5, f"    later wakes (ticks) of 3.0 s {ticks_re:.1f} - of 2.0 s {ticks_op:.1f} = {ticks_re - ticks_op:.1f}")
    emit(
        5,
        f"    differences of the first wake and start-up {M['proc1|first wake'] - M['proc0|first wake']:.1f} + {M['proc1|python + frame.py'] - M['proc0|python + frame.py']:.1f}",
    )
    n, o = exits["normal"], exits["os_exit"]
    emit(
        5,
        f"  os._exit(0) after the select screen has closed (open, first frame and images, q; {EXIT_RUNS} runs each, interleaved):",
    )
    emit(5, f"    normal exit {n:.1f} ms, os._exit(0) {o:.1f} ms of child CPU: saves {n - o:.1f} ms")

    emit(6, "")


def print_total(M, emit):
    total = M["rec|total"]
    meas = M["rec|measurement"]
    cats = [
        ("process start and exit (start-up, imports, load_images, q wake, shutdown)", M["rec|kai"]),
        ("select frames (select wakes, without Markdown)", M["rec|sel"]),
        ("Markdown layout (all wakes)", M["rec|md"]),
        ("report page (report wakes, without Markdown)", M["rec|rep"]),
        ("other (not inside a wake, not measurement)", M["rec|other"]),
    ]
    emit(8, "Total: the fixed script's child CPU split by what was measured (median of the plays)")
    for label, v in cats:
        emit(8, f"  {label:<76}{v:>8.1f} ms  {100 * v / total:5.1f} %")
    s = sum(v for _, v in cats)
    emit(8, f"  {'sum of the five':<76}{s:>8.1f} ms")
    emit(8, f"  {'measurement itself (loading this file, writing the record), taken out':<76}{meas:>8.1f} ms")
    emit(8, f"  {'child CPU of this run (sum of both children)':<76}{total:>8.1f} ms")
    emit(8, f"  {'bench/use.py published total':<76}{PUBLISHED_MS:>8.1f} ms")
    emit(
        8,
        f"  gap: sum of the five {s:.1f} - published {PUBLISHED_MS} = {s - PUBLISHED_MS:+.1f} ms ({100 * (s - PUBLISHED_MS) / PUBLISHED_MS:+.1f} %); this run's total - published = {total - PUBLISHED_MS:+.1f} ms",
    )


def main():
    if "-h" in sys.argv or "--help" in sys.argv:
        print(__doc__)
        return
    from use import STEPS, make_data

    t_start = time.monotonic()
    out: dict[int, list[str]] = {}

    def emit(n, line):
        out.setdefault(n, []).append(line)

    fixture = importlib.import_module("bench").fixture
    with tempfile.TemporaryDirectory(prefix="party-frame-") as tmp:
        data_path = os.path.join(tmp, "data.json")
        make_data(data_path, fixture)
        with open(data_path) as f:
            data = json.load(f)
        sc = Scene(data)
        sink = Sink()
        try:
            _, cuts = part1(sc, sink, emit)
            part6(sc, sink, emit)
            part7(sc, sink, emit)
        finally:
            sink.close()
        plays = run_plays(data_path, tmp)
        exits = exit_trials(data_path, tmp)
        inst = instrumentation(plays[0])
        good, skipped = [], 0
        for p in plays:
            why = check_play(p)
            if why:
                skipped += 1
                print(f"dropped a play: {why}", file=sys.stderr)
            else:
                good.append(p)
        if not good:
            raise RuntimeError("no valid play")
        steps = [{"name": s[0]} for s in STEPS]
        Ms = [summarize(p, inst) for p in good]
        M = merge(Ms)
        first = good[0]
        its0 = [x for x in first["its"] if x["step"] == "open select" and x["proc"] == 0]
        t_first = its0[0]["t"]
        extra = {"open": [], "cut": []}
        for x in its0[1:]:
            reason = REASONS[(x["frames"] > 0, x["snaps"] > 0)] if x["cause"] == "timeout" else x["cause"]
            extra["open"].append(
                f"      +{(x['t'] - t_first) * 1000:6.0f} ms after start of run_menu: {reason}, {x['cpu'] / 1e6:.2f} ms"
            )
        extra["cut"].append(
            "  Markdown laid out only as far as the preview shows (first layout, render_select, see part 1):"
        )
        for name, (n_cut, n_all, full, cutd) in cuts.items():
            extra["cut"].append(
                f"    {name}: {n_cut} of {n_all} source lines: {full:.2f} -> {cutd:.2f} ms, saves {full - cutd:.2f} ms per first layout"
            )
        print_steps(M, steps, lambda n, l: emit(0, l))
        print_parts(M, steps, extra, exits, inst, emit, len(good), skipped)
        print_total(M, emit)
    titles = {
        0: "0. Step overview",
        1: "1. One select frame, 179 x 47, images on",
        2: "2. Idle 5 s on the working member",
        3: "3. k and j",
        4: "4. h, Enter, n",
        5: "5. Process start and exit",
        6: "6. Whole frame against changed rows only",
        7: "7. cProfile ranking",
        8: "Total",
    }
    for n in (1, 2, 3, 4, 5, 6, 7, 0, 8):
        print(f"== {titles[n]} ==")
        for line in out.get(n, []):
            print(line)
        print()
    print(
        f"run time {time.monotonic() - t_start:.0f} s, {len(good)} valid plays of {PLAYS}, python {sys.version.split()[0]}"
    )


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--play":
        play_main(sys.argv[2], sys.argv[3])
    else:
        main()
