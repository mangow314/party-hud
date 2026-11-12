"""The interactive loop of the sidebar: input, cursor, redraws."""

import contextlib
import fcntl
import math
import os
import re
import select
import signal
import struct
import sys
import termios
import time
import tty

from .art import (
    BANNER_MAX_COLS,
    BANNER_RATIOS,
    DIAC,
    LABEL_COLS,
    PORTRAIT_PX,
    SPLIT_BIG_PORTRAIT_COLS,
    SPLIT_GAP,
    SPLIT_MIN_WIDTH,
    SPLIT_SIDE_COLS,
    art_supported,
    banner_id,
    big_portrait_id,
    crest_ids,
    image_row,
    kitty_delete,
    label_id,
    load_art,
    portrait_id,
    select_banner_id,
    send_image,
)
from .collect import alerts, get_snapshot, report_for
from .common import CURSOR_KEYS, ERROR_LOG, PARTY_DIR, capture, cursor_mtime, load_cursor, log_error, save_cursor, tmux
from .render import (
    help_overlay,
    help_screen,
    is_final,
    render,
    render_no_report,
    render_select,
    report_frames,
    report_parts,
    report_view,
    select_cards,
    select_layout,
    select_roster,
    select_view,
    select_widths,
    set_tick,
    side_labels,
    sp_points,
)
from .sidebars import (
    EXE,
    REPORT_BANNER_MAX_ROWS,
    SELECT_BANNER_MAX_ROWS,
    fit_report_pane,
    install_hooks,
    mark_seen,
    mark_sidebar,
    open_report_pane,
)


def follow_here(st, towns, here):
    """Move the cursor to the window you switched to (to its member, or its squad if it has none).
    Leave it alone if it is already there, so a window with several agents keeps the selected one."""
    if not here:
        return
    sel = next((a for t in towns for a in t["agents"] if a["pane"] == st["sel"]), None)
    names = [t["name"] for t in towns]
    if st["focus"] == "party" and sel and sel.get("window") == here["window"]:
        return
    mate = next((a for t in towns for a in t["agents"] if a.get("window") == here["window"]), None)
    if mate:
        st["focus"], st["sel"] = "party", mate["pane"]
    elif here["session"] in names:
        st["focus"], st["squad"] = "squad", names.index(here["session"])


# mouse reporting: 1003 = report motion too (cursor follows the mouse), 1006 = SGR format
MOUSE_ON, MOUSE_OFF = "\033[?1003h\033[?1006h", "\033[?1003l\033[?1006l"


def parse_input(data):
    """Split input into ("key", ch), ("click", row), ("hover", row). Wheel and arrows become k/j, PgUp/PgDn the keys
    "PgUp"/"PgDn"; a lone ESC is Esc."""
    events, i = [], 0
    while i < len(data):
        if data.startswith("\x1b[<", i):  # SGR mouse: ESC [ < button ; col ; row M (press) / m (release)
            end = next((j for j in range(i + 3, len(data)) if data[j] in "Mm"), None)
            if end is None:
                break
            try:
                b, _, y = (int(n) for n in data[i + 3 : end].split(";"))
            except ValueError:
                b, y = -1, 0
            if data[end] == "M":
                if b == 0:
                    events.append(("click", y - 1))
                elif b == 35:
                    events.append(("hover", y - 1))
                elif b in (64, 65):
                    events.append(("key", "k" if b == 64 else "j"))
            i = end + 1
        elif data.startswith(("\x1b[5~", "\x1b[6~"), i):
            events.append(("key", "PgUp" if data[i + 2] == "5" else "PgDn"))
            i += 4
        elif data.startswith(("\x1b[A", "\x1bOA"), i):
            events.append(("key", "k"))
            i += 3
        elif data.startswith(("\x1b[B", "\x1bOB"), i):
            events.append(("key", "j"))
            i += 3
        elif data.startswith("\x1b[", i) or data.startswith("\x1bO", i):
            i += 3
        else:
            events.append(("key", data[i]))
            i += 1
    return events


def report_step(key, i, count):
    """New report index for n (next) / N (previous), wrapping; other keys keep it."""
    return (i + {"n": 1, "N": -1}.get(key, 0)) % count


def report_scroll(key, offset, limit, height):
    """New scroll offset of the report for a key, clamped to 0..limit; other keys keep it."""
    step = {"k": -1, "j": 1, "PgUp": -(height - 1), "PgDn": height - 1}.get(key)
    if key == "g":
        offset = 0
    elif key == "G":
        offset = limit
    elif step:
        offset += step
    return max(0, min(limit, offset))


def help_toggle(key, shown):
    """(shown, consumed) after a key: ? opens the key help; while it is open ?, Esc and q close it and every key is eaten."""
    if shown:
        return key not in ("?", "\x1b", "q"), True
    return key == "?", key == "?"


def handle_key(key, st, towns):
    """Apply a key to the cursor st. Returns None, "jump", "jump_squad", "back" or "hide"."""
    agents = [a for t in towns for a in t["agents"]]
    panes = [a["pane"] for a in agents]
    home = current_squad(st, towns)
    if key in ("j", "k"):
        if st["focus"] == "party" and home is not None:
            mates = [a["pane"] for a in towns[home]["agents"]]
            i = mates.index(st["sel"]) + (1 if key == "j" else -1)
            st["sel"] = mates[max(0, min(len(mates) - 1, i))]
    elif key in ("J", "K") and towns:
        pick_squad(st, towns, ((home or 0) + (1 if key == "J" else -1)) % len(towns))
    elif key.isdigit() and key != "0" and home is not None:
        mates = towns[home]["agents"]
        if int(key) <= len(mates):
            st["focus"], st["sel"] = "party", mates[int(key) - 1]["pane"]
    elif key == "n" and panes:
        st["sel"] = next_waiting(agents, st["sel"]) or st["sel"]
        st["focus"] = "party"
    elif key == "v":
        st["peek"] = not st["peek"]
    elif key == "r" and st["sel"]:
        return "report"
    elif key in ("\r", "\n"):
        if st["focus"] == "squad" and towns:
            return "jump_squad"
        if st["sel"]:
            return "jump"
    elif key in ("q", "\x1b", "P"):
        return "hide" if key == "q" else "back"
    return None


def next_waiting(agents, cur):
    """Next pane after cur (wrapping) that is waiting, else done; cur if only it matches; else None."""
    panes = [a["pane"] for a in agents]
    i = panes.index(cur) if cur in panes else -1
    by_pane = {a["pane"]: a for a in agents}
    order = panes[i + 1 :] + panes[: i + 1]
    return next((p for s in ("waiting", "done") for p in order if alerts(by_pane[p], s)), None)


def current_squad(st, towns):
    if st["focus"] == "squad" and st.get("squad") is not None and st["squad"] < len(towns):
        return st["squad"]
    return next((i for i, t in enumerate(towns) if st["sel"] in [a["pane"] for a in t["agents"]]), None)


def pick_squad(st, towns, i):
    st["squad"] = i
    if towns[i]["agents"]:
        st["focus"], st["sel"] = "party", towns[i]["agents"][0]["pane"]
    else:
        st["focus"] = "squad"


def point_at(target, st, towns):
    kind, value = target
    if kind == "squad":
        if current_squad(st, towns) != value:
            pick_squad(st, towns, value)
        st["squad"] = value
    else:
        st["focus"], st["sel"] = "party", value


HOVER_REST = 0.15


def jump_next():
    agents = [a for t in get_snapshot()["towns"] for a in t["agents"]]
    here = tmux("display-message", "-p", "#{pane_id}").strip()
    target = next_waiting(agents, here)
    if not target or target == here:
        tmux("display-message", "no agent is waiting for you")
        return
    st = {"focus": "party", "sel": target, "squad": None}
    save_cursor(st)
    tmux("switch-client", "-t", target)


def open_select():
    if not any(t["agents"] for t in get_snapshot()["towns"]):
        tmux("display-message", "no party members")
        return
    open_report_pane("", "", select=True)


def select_key(key, panes, sel):
    """(new sel, action) for a key on the select screen: action is None, "open" or "close". panes: pane ids in roster order."""
    if key in ("q", "\x1b"):
        return sel, "close"
    if sel not in panes:
        return sel, None
    i = panes.index(sel)
    if key in ("j", "k"):
        return panes[max(0, min(len(panes) - 1, i + (1 if key == "j" else -1)))], None
    if len(key) == 1 and key in "123456789":
        return (panes[int(key) - 1], "open") if int(key) <= len(panes) else (sel, None)
    if key in ("\r", "\n", "l"):
        return sel, "open"
    return sel, None


def select_reread(cached, a, mono):
    """True when the preview data cached as (key, report, peek, read at) must be read again: another member or round, or a member that works (its turn moves on)."""
    return cached[0] != (a["pane"], a["round"]) or (a["status"] == "working" and mono - cached[3] >= LIVE_REFRESH)


TICK_MARGIN = 0.01
ROUND_HALF = 0.5  # fmt_took rounds, so a shown time turns at timestamp + n + 0.5
SECOND = (0.0, 1.0)
SNAP_AGE = 0.9
SNAP_MAX = 1.9


def time_anchor(ts, now):
    """(anchor, period) of a time shown through fmt_took: seconds and minutes turn at ts + n + ROUND_HALF every second; from 3600 s on only the minute shows, and it turns at ts + 60 n - ROUND_HALF."""
    return (ts - ROUND_HALF, 60.0) if round(now - ts) >= 3600 else (ts + ROUND_HALF, 1.0)


def tick_wait(now, anchors):
    """Seconds from now until the first on-screen time value changes: an anchor is (time, period) and its value changes at time + n * period; the caller picks it (SECOND for the spinner, time_anchor for a time shown through fmt_took). Infinite without anchors (nothing on screen moves with time)."""
    return min(p - (now - a) % p for a, p in anchors) + TICK_MARGIN if anchors else math.inf


def select_phase(now, spins, timed, prev=None):
    """(spinner tick, anchors, state) of a select frame. spins: a member works or has HP <= 10; timed: the cursor member's time_anchor or None; prev: the state of the last frame, or None. A time that turns every second also turns the spinner (and the HP blink), so one anchor wakes both; otherwise the spinner turns on the whole second. When the phase changes the tick holds its last value, so it never steps back or jumps, and the next step falls on the new phase's boundary."""
    sync = timed if timed and timed[1] == 1.0 else None
    anchors = [sync] if sync else [SECOND] if spins else []
    if timed and not sync:
        anchors.append(timed)
    phase = sync[0] % 1.0 if sync else 0.0
    raw = math.floor(now - phase)
    offset = prev[1] if prev and prev[0] == phase else prev[2] - raw if prev else 0
    return raw + offset, anchors, (phase, offset, raw + offset)


def select_wait(fetched, mono, tick_at, wall):
    """Seconds until the select screen is next due: tick_at (wall-clock time a shown time value changes) when that wake still comes within SNAP_MAX of the last snapshot read (it reads then), else one second after the read."""
    tick_in = tick_at - wall
    return max(0.0, tick_in if mono + tick_in - fetched <= SNAP_MAX else fetched + 1 - mono)


def select_image_plan(cards, art):
    """(id, cols, rows) of the small portrait of each card on screen. Empty without art."""
    return [(portrait_id(a), *art[portrait_id(a)][1:]) for a in cards] if art else []


def select_title_plan(art, banner, show):
    """(id, cols, rows) of the select screen's banner: only with art and when the title block is drawn."""
    return [(select_banner_id(banner[2]), *banner[:2])] if art and banner and show else []


def select_images_due(plan, sent):
    """The images of plan not yet sent at these cells: sent maps id -> (cols, rows)."""
    return [img for img in plan if sent.get(img[0]) != img[1:]]


def select_images_out(plan, art, sent, shared):
    """Kitty sequences for the images of plan not sent yet; an id this pane never sent is deleted first so an older image under it is gone (not the shared ones, the sidebars show those)."""
    due = select_images_due(plan, sent)
    return "".join(kitty_delete(i) for i, _, _ in due if i not in sent and i not in shared) + "".join(
        send_image(art, i, c, r) for i, c, r in due
    )


def load_images(fixture):
    """(art, sent) for a screen: art is None without image support; sent maps id -> (cols, rows) already sent to the terminal."""
    art = (
        load_art()
        if not fixture
        and art_supported(
            tmux("show-option", "-gqv", "@party_art").strip(),
            tmux("display-message", "-p", "#{client_termname}").strip(),
        )
        else None
    )
    return art, {}


def run_select(sel=None, fixture=None, images=None):
    """Select screen (prefix R): the member cards beside the report preview of the member under the cursor. Returns the pane whose report to open, or None when it was closed.
    With images, the banner and the portraits of the cards on screen are sent once the window size has settled; they stay in the terminal on exit, since another pane may still show them under the same id."""
    art, sent = images or load_images(fixture)
    queue: list = []
    last_winch = 0.0
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    sys.stdout.write("\033[?1049h\033[?25l" + MOUSE_ON)
    wake_r, wake_w = os.pipe()
    os.set_blocking(wake_r, False)
    os.set_blocking(wake_w, False)
    signal.signal(signal.SIGWINCH, lambda *_: None)
    signal.set_wakeup_fd(wake_w)
    last_frame, helping, cached = None, False, (None, None, [], 0.0)
    towns, fetched, spin = [], -1.0, None
    try:
        tty.setcbreak(fd)
        while True:
            if time.monotonic() - fetched >= SNAP_AGE:
                towns, fetched = get_snapshot(fixture)["towns"], time.monotonic()
            roster = select_roster(towns)
            queue = [(squad, a) for squad, a, _ in roster]
            shared = {portrait_id(a) for _, a in queue}
            panes = [a["pane"] for _, a, _ in roster]
            if sel not in panes:
                sel = panes[0] if panes else None
            size = os.get_terminal_size(sys.stdout.fileno())
            width, now = size.columns - 1, time.time()
            plan, title, report = [], None, None
            head_rows = 1
            banner = select_banner(width, size.lines, cell_ratio()) if art else None
            if banner:
                head_rows = banner[1]
                pad = " " * banner[3]
                title = [pad + image_row(select_banner_id(banner[2]), r, banner[0]) for r in range(head_rows)]
                plan = select_title_plan(art, banner, select_layout(size.lines, head_rows)[2])
            body_h = select_layout(size.lines, head_rows)[3]
            lw, preview = select_widths(width)
            if sel and preview:
                a = next(m for _, m, _ in roster if m["pane"] == sel)
                if select_reread(cached, a, time.monotonic()):
                    report = None if fixture else report_for(a)
                    peek = report_peek({}, a["pane"], report, fixture, lambda p: capture(p, color=True))
                    cached = ((a["pane"], a["round"]), report, peek, time.monotonic())
                report = cached[1]
            timed = None
            if sel and preview and report:
                cur = next(m for _, m, _ in roster if m["pane"] == sel)
                if cur["status"] == "waiting" and report.get("end"):
                    timed = time_anchor(report["end"], now)
                elif cur["status"] == "working" and report.get("live") and report.get("start"):
                    timed = time_anchor(report["start"], now)
            spins = any(m["status"] == "working" or (m["hp"] is not None and m["hp"] <= 10) for _, m, _ in roster)
            tick, anchors, spin = select_phase(now, spins, timed, spin)
            set_tick(tick)
            view = select_view(roster, sel, lw, body_h, art is not None)
            plan += select_image_plan(select_cards(roster, view), art)
            rows = render_select(
                roster, towns, sel, width, size.lines, report, now, title, art is not None, cached[2], view
            )
            if helping:
                rows = help_overlay(rows, "select", width, size.lines)
            frame = "\n".join(rows)
            tick_at = now + tick_wait(now, anchors)
            if frame != last_frame:
                sys.stdout.write("\033[H" + "\033[K\n".join(frame.split("\n")) + "\033[K\033[J")
                sys.stdout.flush()
                last_frame = frame
            due = bool(art) and bool(select_images_due(plan, sent))
            if art and due and time.monotonic() - last_winch >= RESIZE_SETTLE:
                sys.stdout.write(select_images_out(plan, art, sent, shared))
                sys.stdout.flush()
                sent.update((i, (c, r)) for i, c, r in plan)
                due = False
            while True:
                wait = select_wait(fetched, time.monotonic(), tick_at, time.time())
                if due:
                    wait = min(wait, max(0.0, last_winch + RESIZE_SETTLE - time.monotonic()))
                ready = select.select([fd, wake_r], [], [], wait)[0]
                if wake_r in ready:
                    with contextlib.suppress(BlockingIOError):
                        os.read(wake_r, 1024)
                    last_winch = time.monotonic()
                    last_frame = None
                if fd in ready or not ready or last_frame is None:
                    break
            if fd not in ready:
                continue
            data = os.read(fd, 1024)
            if not data:
                return None
            for kind, key in parse_input(data.decode(errors="ignore")):
                if kind != "key":
                    continue
                helping, eaten = help_toggle(key, helping)
                if eaten:
                    continue
                sel, action = select_key(key, panes, sel)
                if action == "open":
                    return sel
                if action == "close":
                    return None
    finally:
        signal.set_wakeup_fd(-1)
        signal.signal(signal.SIGWINCH, signal.SIG_DFL)
        os.close(wake_r)
        os.close(wake_w)
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write(MOUSE_OFF + "\033[?25h\033[?1049l")
        sys.stdout.flush()


def leave_without_teardown():
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)  # skips the interpreter's module and object teardown, about 5 ms of CPU per exit


def run_menu(fixture=None):
    host = "" if fixture else os.environ.get("TMUX_PANE", "")
    images = load_images(fixture)
    pane = run_select(None, fixture, images)
    while pane:
        if host:
            fit_report_pane(host, False)
        pane = run_report(pane, fixture, back=True, images=images)
        if pane:
            if host:
                fit_report_pane(host, True)
            pane = run_select(pane, fixture, images)


def report_queue(towns, pane=None, window=None):
    """[(squad name, member)] to read: pane (any status) first when given, then waiting, done, working with running subagents,
    then everyone else, members in window before the rest."""
    members = [(t["name"], a) for t in towns for a in t["agents"]]
    queue = [m for s in ("waiting", "done") for m in members if alerts(m[1], s)]
    queue += [m for m in members if m[1]["status"] == "working" and m[1].get("summons")]
    rest = [m for m in members if m not in queue]
    here = [m for m in rest if window and m[1].get("window") == window]
    queue += here + [m for m in rest if m not in here]
    mine = [m for m in members if m[1]["pane"] == pane]
    return mine + [m for m in queue if m not in mine]


def open_report(pane):
    open_report_pane(os.environ.get("TMUX_PANE", ""), pane)


def cell_ratio():
    """Cell width / height; 1:2 when the terminal reports no pixel size."""
    try:
        lines, columns, xpix, ypix = struct.unpack(
            "HHHH", fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, bytes(8))
        )
    except OSError:
        lines = columns = xpix = ypix = 0
    return xpix * lines / (ypix * columns) if xpix and ypix and lines and columns else 0.5


def fit_banner(cols, max_rows, ratio):
    """(cols, rows, k) of a banner in at most cols x max_rows cells: rows follow the width, k is the k:1 image (k = 4..8) closest to the cells' pixel shape, cols cut to the image's width only when more than one column is left over."""
    rows = max(1, min(max_rows, round(cols * ratio / 4)))
    a = cols * ratio / rows
    k = min(BANNER_RATIOS, key=lambda k: (abs(k - a), k))
    if cols - rows * k / ratio > 1:
        cols = round(rows * k / ratio)
    return cols, rows, k


def banner_cells(width, ratio):
    """(cols, rows, k) of the report banner, using the k:1 image (k = 4..8) closest to its pixel shape, at most REPORT_BANNER_MAX_ROWS tall.
    Narrow: 4:1, as wide as the text up to BANNER_MAX_COLS, a capped height narrows it. Split: as wide as the right column (up to the placeholder diacritics); a cell shape the images do not fill is cut to the nearest image."""
    if width < SPLIT_MIN_WIDTH:
        cols = min(BANNER_MAX_COLS, max(28, width))
        rows = max(1, round(cols * ratio / 4))
        if rows > REPORT_BANNER_MAX_ROWS:
            rows, cols = REPORT_BANNER_MAX_ROWS, min(cols, round(REPORT_BANNER_MAX_ROWS * 4 / ratio))
        return cols, rows, 4
    return fit_banner(min(len(DIAC), width - SPLIT_SIDE_COLS - SPLIT_GAP), REPORT_BANNER_MAX_ROWS, ratio)


def select_banner(width, height, ratio):
    """(cols, rows, k, left_pad) of the select screen's banner, as wide as the whole screen (up to the placeholder diacritics) and centered; None when it would leave the roster fewer than 8 rows."""
    cols, rows, k = fit_banner(min(len(DIAC), width), SELECT_BANNER_MAX_ROWS, ratio)
    layout = select_layout(height, rows)
    if not layout[2] or layout[3] < 8:
        return None
    return cols, rows, k, (width - cols) // 2


def portrait_cells(ratio):
    """(cols, rows) of the big portrait in the split layout, keeping the image's proportions."""
    cols = SPLIT_BIG_PORTRAIT_COLS
    return cols, max(1, round(cols * ratio * PORTRAIT_PX[1] / PORTRAIT_PX[0]))


def report_image_plan(a, has_report, art, width, banner, big, labels=()):
    """(id, cols, rows) of each image on the report page: the banner, then the big portrait (own id) and the heading labels the page shows (names) in the split layout, or the sidebar portrait otherwise."""
    bid = banner_id(a["status"], has_report, bool(a.get("summons")), *banner[2:])
    if width >= SPLIT_MIN_WIDTH:
        return [(bid, *banner[:2]), (big_portrait_id(a), *big), *((label_id(n), LABEL_COLS[n], 1) for n in labels)]
    img = portrait_id(a)
    return [(bid, *banner[:2]), (img, *art[img][1:])]


def report_images(a, has_report, art, width, banner, big, drawn=None, labels=(), sent=None):
    """Kitty sequences for the report page. drawn=None is a fresh page, judged against sent (id -> (cols, rows) this pane already sent, kept across pages): same cells are skipped, other cells are resent under the same id, an id never sent is deleted first (not the sidebar portrait) so a stale image in the terminal is replaced. With drawn (what the page has on screen) it is a redraw: an image whose cells are unchanged is skipped and a resized one is resent under the same id without a delete, so no placeholder is left without an image."""
    out = ""
    known = (sent or {}) if drawn is None else drawn
    for img_id, cols, rows in report_image_plan(a, has_report, art, width, banner, big, labels):
        if known.get(img_id) == (cols, rows):
            continue
        if drawn is None and img_id not in known and img_id != portrait_id(a):
            out += kitty_delete(img_id)
        out += send_image(art, img_id, cols, rows)
    return out


def report_first_deletes(a, has_report, art, width, banner, big, sent, labels=()):
    """Deletes for the images this pane has not sent yet (not the sidebar portrait), written with the page's first frame so an older image under the same id is gone before the placeholders appear."""
    return "".join(
        kitty_delete(img_id)
        for img_id, _, _ in report_image_plan(a, has_report, art, width, banner, big, labels)
        if img_id not in sent and img_id != portrait_id(a)
    )


RESIZE_INTERVAL = 0.05
RESIZE_SETTLE = 0.15
ANIM_TOTAL = 0.4


def report_resize_wait(last_draw, now):
    """Seconds to wait before the next resize redraw so that redraws are at least RESIZE_INTERVAL apart."""
    return max(0.0, last_draw + RESIZE_INTERVAL - now)


def report_anim_enabled(value):
    return value.strip() != "off"


FLASH_SECS = 4.0
FLASH_STEP = 0.5
LABEL_SECS = 10.0
FRAME_SECS = 0.5
DELTA_MIN = 5


def animate(anim, agents, now):
    """Pulse the card frame of a member that just became done or waiting, and show how far HP / SP just moved.
    anim: per-pane state kept across calls. Returns (agents to draw, panes lit this frame, whether more frames are due)."""
    shown, lit, busy = [], set(), False
    for a in agents:
        pane = a["pane"]
        cur = [a["hp"], sp_points(a)]
        s = anim.get(pane)
        if s is None:
            s = anim[pane] = {
                "last": cur,
                "delta": [None, None],
                "t0": [now, now],
                "status": a["status"],
                "flash": None,
            }
        for i in (0, 1):
            old, new = s["last"][i], cur[i]
            if old is not None and new is not None and abs(new - old) >= DELTA_MIN:
                s["delta"][i], s["t0"][i] = new - old, now
            elif s["delta"][i] is not None and now - s["t0"][i] >= LABEL_SECS:
                s["delta"][i] = None
        s["last"] = cur
        if a["status"] != s["status"]:
            s["status"] = a["status"]
            if a["status"] in ("done", "waiting"):
                s["flash"] = now
        if s["flash"] is not None:
            if now - s["flash"] >= FLASH_SECS:
                s["flash"] = None
            else:
                busy = True
                if int((now - s["flash"]) / FLASH_STEP) % 2 == 0:
                    lit.add(pane)
        if s["delta"] != [None, None]:
            a = dict(a, hp_delta=s["delta"][0], sp_delta=s["delta"][1])
        shown.append(a)
    for pane in anim.keys() - {a["pane"] for a in agents}:
        del anim[pane]
    return shown, lit, busy


def play_report_anim(rest, left, height, fd, wake_r, start):
    """Draw the frames after the first one, evenly over ANIM_TOTAL counted from start (when the first was drawn). True when input or a signal arrived first; it stays unread for the main loop."""
    for j, right in enumerate(rest, 1):
        if select.select([fd, wake_r], [], [], max(0.0, start + j * ANIM_TOTAL / len(rest) - time.monotonic()))[0]:
            return True
        draw_report(left, right, height, 0)
    return False


def report_peek(peeks, pane, report, fixture, grab):
    if report is not None or fixture:
        return []
    if pane not in peeks:
        peeks[pane] = grab(pane)
    return peeks[pane]


LIVE_REFRESH = 1.5


def refresh_live(queue, i):
    """Re-read the snapshot and the log of queue[i]'s member: its status decides whether this is still the turn in progress or already the finished report. None when the snapshot no longer lists the member."""
    pane = queue[i][1]["pane"]
    a = next((m for t in get_snapshot()["towns"] for m in t["agents"] if m["pane"] == pane), None)
    if a is None:
        return None
    queue[i] = (queue[i][0], a)
    return report_for(a)


def draw_report(left, right, height, offset, screen=None):
    """Writes the page and returns the rows written."""
    rows = screen or report_view(left, right, height, offset)[0]
    # no newline after the last row: it would scroll the pane
    sys.stdout.write("\033[H" + "\n".join(row + "\033[K" for row in rows) + "\033[J")
    sys.stdout.flush()
    return rows


def run_report(pane=None, fixture=None, back=False, images=None):
    """Report pane (prefix R, or r in the sidebar): draws one member's last report on the alternate screen and scrolls it itself
    (j/k, arrows, wheel, PgUp/PgDn, g/G): in the split page only the right column moves. Rows are overwritten in place, also on a
    resize (at most one redraw per RESIZE_INTERVAL), and never scroll the pane. Images follow a resize only once it has settled.
    With back (opened from the select screen) h ends it and returns the pane id of the member on screen; every other exit returns None."""
    here = os.environ.get("TMUX_PANE", "")
    window = tmux("display-message", "-p", "-t", here, "#{window_id}").strip() if here and not fixture else ""
    queue = report_queue(get_snapshot(fixture)["towns"], pane, window)
    art, sent = images or load_images(fixture)
    anim = not fixture and report_anim_enabled(tmux("show-option", "-gqv", "@party_anim"))
    reports, peeks, i = {}, {}, 0
    read_rounds: dict[str, int] = {}
    fresh, cut, helping = True, False, False
    drawn: dict[int, tuple[int, int]] | None = None
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    sys.stdout.write("\033[?1049h\033[?25l" + MOUSE_ON)
    offset = 0
    wake_r, wake_w = os.pipe()
    os.set_blocking(wake_r, False)
    os.set_blocking(wake_w, False)
    signal.signal(signal.SIGWINCH, lambda *_: None)
    signal.set_wakeup_fd(wake_w)
    resized, art_pending, last_winch = False, False, 0.0
    next_live, tick_at, cause = 0.0, None, ""
    written: list[str] | None = None
    after_live = False
    anim_start = 0.0
    resend: tuple[float, list[tuple[int, int, int]]] | None = None
    try:
        tty.setcbreak(fd)
        if not queue:
            size = os.get_terminal_size(sys.stdout.fileno())
            sys.stdout.write(render_no_report(size.columns - 1, size.lines) + "\n")
            sys.stdout.flush()
            os.read(fd, 1024)
            return
        while True:
            squad, a = queue[i]
            if a["pane"] not in reports:
                reports[a["pane"]] = None if fixture else report_for(a)
            report = reports[a["pane"]]
            if is_final(report) and read_rounds.get(a["pane"]) != a["round"]:
                read_rounds[a["pane"]] = a["round"]
                try:
                    mark_seen(a["pane"], a["round"])
                except OSError:
                    log_error()
            peek = report_peek(peeks, a["pane"], report, fixture, lambda p: capture(p, color=True))
            live = bool(report and report.get("live"))
            ticked = cause == "tick"
            if not ticked:
                next_live = time.monotonic() + LIVE_REFRESH
            cause = ""
            last_draw = time.monotonic()
            size = os.get_terminal_size(sys.stdout.fileno())
            width, ratio = size.columns - 1, cell_ratio()
            banner = banner_cells(width, ratio)
            big = portrait_cells(ratio)
            now = time.time()
            left, right = report_parts(
                a,
                squad,
                report,
                peek,
                width,
                i + 1,
                len(queue),
                art is not None,
                banner,
                big,
                size.lines,
                now,
                True,
                "report_back" if back else "report",
            )
            limit = max(0, len(right) - size.lines)
            offset = min(offset, limit)
            screen = (
                help_overlay(report_view(left, right, size.lines, offset)[0], "report", width, size.lines)
                if helping
                else None
            )
            frames = report_frames(right, size.lines, tail=0 if left else 2) if fresh and anim else [right]
            fresh = False
            names = side_labels(report, now)
            anchors = []
            if live and report.get("start"):
                anchors.append(time_anchor(report["start"], now))
            if left and report and report["end"]:
                anchors.append(time_anchor(report["end"], now))
            tick_at = now + tick_wait(now, anchors) if anchors else None
            if art and drawn is None:
                sys.stdout.write(report_first_deletes(a, is_final(report), art, width, banner, big, sent, names))
            steps = frames[1:]
            if steps:
                anim_start = time.monotonic()
                draw_report(left, frames[0], size.lines, 0)
                written = None
            else:
                rows = screen or report_view(left, right, size.lines, offset)[0]
                if not (ticked and rows == written):
                    written = draw_report(left, right, size.lines, offset, rows)
            art_pending = bool(art)
            while True:
                if art and art_pending and not resized and not cut:
                    out = report_images(a, is_final(report), art, width, banner, big, drawn, names, sent)
                    plan = report_image_plan(a, is_final(report), art, width, banner, big, names)
                    if out:
                        sys.stdout.write(out)
                        sys.stdout.flush()
                        if after_live:
                            resend = (time.monotonic() + ART_SETTLE, [p for p in plan if sent.get(p[0]) != p[1:]])
                    after_live = False
                    drawn = {k: (c, r) for k, c, r in plan}
                    sent.update(drawn)
                    art_pending = False
                if steps:
                    cut = play_report_anim(steps, left, size.lines, fd, wake_r, anim_start)
                    steps = []
                    if cut and os.get_terminal_size(sys.stdout.fileno()) == size:
                        written = draw_report(left, right, size.lines, offset, screen)
                timeout = max(0.0, RESIZE_SETTLE - (time.monotonic() - last_winch)) if art_pending else None
                dues = ([next_live - time.monotonic()] if live else []) + ([tick_at - time.time()] if tick_at else [])
                if resend:
                    dues.append(resend[0] - time.monotonic())
                if dues:
                    timeout = max(0.0, min(dues) if timeout is None else min(timeout, *dues))
                ready = select.select([fd, wake_r], [], [], timeout)[0]
                cut = False
                if wake_r in ready:
                    with contextlib.suppress(BlockingIOError):
                        os.read(wake_r, 1024)
                    last_winch = time.monotonic()
                if os.get_terminal_size(sys.stdout.fileno()) != size:
                    time.sleep(report_resize_wait(last_draw, time.monotonic()))
                    resized = True
                    break
                if art and resend and time.monotonic() >= resend[0]:
                    # tmux drops a pane's passthrough while it redraws a client, and nothing tells us
                    sys.stdout.write(
                        "".join(send_image(art, k, c, r) for k, c, r in resend[1] if sent.get(k) == (c, r))
                    )
                    sys.stdout.flush()
                    resend = None
                if live and time.monotonic() >= next_live:
                    new = refresh_live(queue, i)
                    if new is None:
                        live = False
                        continue
                    reports[a["pane"]] = new
                    if is_final(new):
                        drawn = None
                        after_live = True
                    cause = "live"
                    break
                if tick_at and time.time() >= tick_at:
                    cause = "tick"
                    break
                if art_pending and time.monotonic() - last_winch >= RESIZE_SETTLE:
                    resized = False
                    continue
                if fd not in ready:
                    continue
                data = os.read(fd, 1024)
                if not data:
                    return
                keys = [key for kind, key in parse_input(data.decode(errors="ignore")) if kind == "key"]
                was, rest = helping, []
                for key in keys:
                    helping, eaten = help_toggle(key, helping)
                    if not eaten:
                        rest.append(key)
                keys = rest
                if helping != was:
                    screen = (
                        help_overlay(report_view(left, right, size.lines, offset)[0], "report", width, size.lines)
                        if helping
                        else None
                    )
                    written = draw_report(left, right, size.lines, offset, screen)
                if "n" in keys or "N" in keys:
                    i = report_step("N" if "N" in keys and "n" not in keys else "n", i, len(queue))
                    peeks.pop(queue[i][1]["pane"], None)
                    reports.pop(queue[i][1]["pane"], None)
                    if not fixture:
                        cur = next(
                            (
                                m
                                for t in get_snapshot()["towns"]
                                for m in t["agents"]
                                if m["pane"] == queue[i][1]["pane"]
                            ),
                            None,
                        )
                        if cur is not None:
                            queue[i] = (queue[i][0], cur)
                    drawn = None
                    after_live = False
                    resized = False
                    fresh = True
                    offset = 0
                    break
                if "\r" in keys or "\n" in keys:
                    save_cursor({"focus": "party", "sel": a["pane"], "squad": None})
                    tmux("switch-client", "-t", a["pane"])
                    return
                if back and "h" in keys:
                    return a["pane"]
                if "q" in keys or "\x1b" in keys:
                    return
                new = offset
                for key in keys:
                    new = report_scroll(key, new, limit, size.lines)
                if new != offset:
                    offset = new
                    written = draw_report(left, right, size.lines, offset, screen)
    finally:
        signal.set_wakeup_fd(-1)
        signal.signal(signal.SIGWINCH, signal.SIG_DFL)
        os.close(wake_r)
        os.close(wake_w)
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write(MOUSE_OFF + "\033[?25h\033[?1049l")
        sys.stdout.flush()


HIDE_AFTER = 2.0
ART_SETTLE = 1.0


def run_ui(fixture=None):
    """Main loop of the sidebar: read the snapshot every second, redraw only on change."""
    me = os.environ.get("TMUX_PANE", "")
    if not fixture:
        # tmux-resurrect restores neither pane options nor hooks
        mark_sidebar(me)
        install_hooks()
    st = {"focus": "party", "sel": None, "squad": None, "peek": False}
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    # ?7l: no autowrap, so a squeezed pane clips lines instead of wrapping them
    sys.stdout.write("\033[?25l\033[?7l" + MOUSE_ON)
    last_frame, row_map, frame_lines = None, [], []
    pending, due = None, False
    last_here = None
    art = (
        load_art()
        if not fixture
        and art_supported(
            tmux("show-option", "-gqv", "@party_art").strip(),
            tmux("display-message", "-p", "#{client_termname}").strip(),
        )
        else None
    )
    sent, was_visible = set(), False
    anim = {}
    anim_on = not fixture and report_anim_enabled(tmux("show-option", "-gqv", "@party_anim"))
    flashing, busy = frozenset(), False
    hidden_since = shown_since = None
    resized = [False]
    helping = False
    signal.signal(signal.SIGWINCH, lambda *_: resized.__setitem__(0, True))
    try:
        tty.setcbreak(fd)
        while True:
            if resized[0]:
                resized[0], last_frame = False, None
            try:
                snap = get_snapshot(fixture)
            except Exception:  # noqa: BLE001 a crash would close the pane and its window would lose the sidebar; retry next second
                log_error()
                time.sleep(1)
                continue
            towns = snap["towns"]
            agents = [a for t in towns for a in t["agents"]]
            seen = cursor_mtime()
            load_cursor(st)
            here = snap.get("here")
            if here != last_here:
                if last_here is not None:
                    before = tuple(st[k] for k in CURSOR_KEYS)
                    follow_here(st, towns, here)
                    if tuple(st[k] for k in CURSOR_KEYS) != before:
                        save_cursor(st)
                        seen = cursor_mtime()
                last_here = here
            if st["sel"] not in [a["pane"] for a in agents]:
                st["sel"] = next((a["pane"] for a in agents if a["focus"]), agents[0]["pane"] if agents else None)
            if st["squad"] is not None and st["squad"] >= len(towns):
                st["squad"] = len(towns) - 1 if towns else None
            info = snap["panes"].get(me)
            if info and info["window_panes"] <= 1:
                tmux("kill-pane", "-t", me)  # under remain-on-exit, exiting alone would leave the pane
                break
            visible = info["visible"] if info else True
            if info and not visible:
                hidden_since = hidden_since or time.time()
                # the snapshot can be 2 s old: ask tmux before exiting, or nothing would wake this sidebar
                if time.time() - hidden_since > HIDE_AFTER:
                    active, _, attached = (
                        tmux("display-message", "-p", "-t", me, "#{window_active} #{session_attached}")
                        .strip()
                        .partition(" ")
                    )
                    if active == "1" and attached not in ("", "0"):
                        hidden_since = None
                        continue
                    break
            else:
                hidden_since = None
            # tmux drops passthrough without a trace while it redraws the client (split, switch, attach)
            shown_since = (shown_since or time.time()) if visible else None
            show_art = shown_since is not None and time.time() - shown_since >= ART_SETTLE
            if art and show_art:
                # just became visible (switched here, or attached from another terminal): resend all images
                if not was_visible:
                    sent.clear()
                need = set(crest_ids(t["name"] for t in towns).values()) | {portrait_id(a) for a in agents}
                for img in sorted(need - sent):
                    sys.stdout.write(send_image(art, img, *art[img][1:]))
                if need - sent:
                    sys.stdout.flush()  # without this flush the last chunk stays buffered when the frame is unchanged
                sent |= need
            was_visible = show_art
            try:  # ask the terminal: shutil.get_terminal_size trusts COLUMNS, which goes stale after a resize
                size = os.get_terminal_size(sys.stdout.fileno())
            except OSError:
                import shutil

                size = shutil.get_terminal_size()
            lines = (capture(st["sel"]) if not fixture else []) if st["peek"] and st["sel"] and visible else None
            busy = False
            try:
                if helping:
                    frame = "\n".join(help_screen("sidebar", size.columns - 1, size.lines))
                    row_map[:] = []
                else:
                    shown = towns
                    if anim_on and lines is None:
                        drawn, flashing, busy = animate(anim, agents, time.monotonic())
                        if busy or any("hp_delta" in a for a in drawn):
                            by_pane = {a["pane"]: a for a in drawn}
                            shown = [dict(t, agents=[by_pane[a["pane"]] for a in t["agents"]]) for t in towns]
                    frame = render(
                        shown,
                        size.columns - 1,
                        st["sel"],
                        lines,
                        "sidebar",
                        size.lines,
                        row_map,
                        st["focus"],
                        st["squad"],
                        int(time.time()),
                        art is not None,
                        snap["panes"].get(os.environ.get("TMUX_PANE", ""), {}).get("session")
                        or (here or {}).get("session"),
                        flashing,
                    )
            except Exception:  # noqa: BLE001 show the error instead of ending the sidebar
                log_error()
                frame = f" render error, see\n {ERROR_LOG}"
            if frame != last_frame:  # overwrite line by line without clearing, so the spinner does not flicker
                sys.stdout.write("\033[H" + "\033[K\n".join(frame.split("\n")) + "\033[K\033[J")
                sys.stdout.flush()
                last_frame, frame_lines = frame, frame.split("\n")
            deadline = time.time() + (FRAME_SECS if busy else 1)
            r = []
            while True:
                due = pending and time.time() >= pending[1] + HOVER_REST
                if due:
                    break
                wait = 0.1 if not pending else max(0.0, min(0.1, pending[1] + HOVER_REST - time.time()))
                r, _, _ = select.select([fd], [], [], wait)
                if r or resized[0] or time.time() >= deadline or cursor_mtime() != seen:
                    break
            if due and pending:
                point_at(pending[0], st, towns)
                save_cursor(st)
                pending = None
                continue
            if not r:
                continue
            prev, done = tuple(st[k] for k in CURSOR_KEYS), False
            for kind, value in parse_input(os.read(fd, 1024).decode(errors="ignore")):
                action = None
                if kind in ("click", "hover"):
                    target = row_map[value] if 0 <= value < len(row_map) else None
                    if kind == "click":
                        note_click(value, target, frame_lines)
                    if not target:
                        pending = None
                        continue
                    if kind == "hover" and target[0] == "squad":
                        pending = (target, time.time()) if current_squad(st, towns) != target[1] else None
                        continue
                    pending = None
                    point_at(target, st, towns)
                    if kind == "click":
                        action = "jump_squad" if target[0] == "squad" else "jump"
                else:
                    pending = None
                    helping, eaten = help_toggle(value, helping)
                    if eaten:
                        continue
                    action = handle_key(value, st, towns)
                if action in ("jump", "jump_squad"):
                    save_cursor(st)  # save first, so the destination sidebar wakes up with the same selection
                if action == "jump":
                    # a pane id target switches session, window and pane together
                    tmux("switch-client", "-t", st["sel"])
                elif action == "jump_squad":
                    tmux("switch-client", "-t", "=" + towns[st["squad"]]["name"])  # =: exact name match
                elif action == "report":
                    open_report(st["sel"])
                elif action == "back":
                    tmux("select-pane", "-l")
                elif action == "hide":
                    # let the server do it: killing panes from here would kill this sidebar first
                    tmux("run-shell", "-b", f"{EXE} --toggle")
                    done = True
                if done:
                    break
            if tuple(st[k] for k in CURSOR_KEYS) != prev:
                save_cursor(st)
            if done:
                break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        # no newline: the pane keeps this frame (remain-on-exit) and a newline on the last row would scroll it
        sys.stdout.write(MOUSE_OFF + "\033[?7h\033[?25h")
        sys.stdout.flush()


def note_click(row, target, frame_lines):
    line = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", frame_lines[row]) if 0 <= row < len(frame_lines) else ""
    try:
        with open(os.path.join(PARTY_DIR, "last-click"), "w") as f:
            f.write(f"{time.strftime('%F %T')} row={row} target={target} line={line}\n")
    except OSError:
        pass
