"""The interactive loop of the sidebar and the popup: input, cursor, redraws."""

import os
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import termios
import time
import tty

from .art import art_supported, crest_ids, kitty_image, load_art, portrait_id
from .collect import get_snapshot, report_for
from .common import CURSOR_KEYS, ERROR_LOG, PARTY_DIR, capture, cursor_mtime, load_cursor, log_error, save_cursor, tmux
from .render import render, render_no_report, render_report
from .sidebars import EXE, install_hooks, mark_sidebar


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
    """Split input into ("key", ch), ("click", row), ("hover", row). Wheel and arrows become k/j; a lone ESC is Esc."""
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


def handle_key(key, st, towns, mode):
    """Apply a key to the cursor st. Returns None, "jump", "jump_squad", "close", "back" or "hide"."""
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
    elif key == "r" and mode == "sidebar" and st["sel"]:
        return "report"
    elif key in ("\r", "\n"):
        if st["focus"] == "squad" and towns:
            return "jump_squad"
        if st["sel"]:
            return "jump"
    elif key in ("q", "\x1b", "P"):
        if mode == "popup":
            return "close"
        return "hide" if key == "q" else "back"
    return None


def next_waiting(agents, cur):
    """Next pane after cur (wrapping) that is waiting, else done; cur if only it matches; else None."""
    panes = [a["pane"] for a in agents]
    i = panes.index(cur) if cur in panes else -1
    status = {a["pane"]: a["status"] for a in agents}
    order = panes[i + 1 :] + panes[: i + 1]
    return next((p for s in ("waiting", "done") for p in order if status[p] == s), None)


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


def report_queue(towns, pane=None):
    """[(squad name, member)] to read: waiting first, then done; pane (any status) goes first when given."""
    members = [(t["name"], a) for t in towns for a in t["agents"]]
    queue = [m for s in ("waiting", "done") for m in members if m[1]["status"] == s]
    mine = [m for m in members if m[1]["pane"] == pane]
    return mine + [m for m in queue if m not in mine]


def open_report(pane):
    # tmux display-popup returns only when the popup closes; waiting would freeze this sidebar
    subprocess.Popen(
        [
            "tmux",
            "display-popup",
            "-E",
            "-w",
            "80%",
            "-h",
            "80%",
            "-T",
            " Report ",
            f"{EXE} --report {shlex.quote(pane)}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def run_report(pane=None, fixture=None):
    """Report popup (prefix R, or r in the sidebar): one member's last report at a time."""
    queue = report_queue(get_snapshot(fixture)["towns"], pane)
    reports, i, scroll, top = {}, 0, 0, 0
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    dirty = [True]
    signal.signal(signal.SIGWINCH, lambda *_: dirty.__setitem__(0, True))
    sys.stdout.write("\033[?25l\033[?7l" + MOUSE_ON)
    try:
        tty.setcbreak(fd)
        while not queue:
            if dirty[0]:
                dirty[0] = False
                size = os.get_terminal_size(sys.stdout.fileno())
                sys.stdout.write("\033[H" + render_no_report(size.columns - 1, size.lines) + "\033[J")
                sys.stdout.flush()
            # a popup that exits at once only flashes: stay until a key
            if select.select([fd], [], [], 0.5)[0]:
                return
        while True:
            squad, a = queue[i]
            if dirty[0]:
                dirty[0] = False
                if a["pane"] not in reports:
                    reports[a["pane"]] = None if fixture else report_for(a)
                report = reports[a["pane"]]
                peek = capture(a["pane"]) if report is None and not fixture else []
                size = os.get_terminal_size(sys.stdout.fileno())
                frame, top = render_report(
                    a, squad, report, peek, size.columns - 1, size.lines, scroll, i + 1, len(queue)
                )
                sys.stdout.write("\033[H" + "\033[K\n".join(frame.split("\n")) + "\033[K\033[J")
                sys.stdout.flush()
            # select retries after SIGWINCH (PEP 475), so wake up now and then to redraw after a resize
            r, _, _ = select.select([fd], [], [], 0.5)
            if not r:
                continue
            dirty[0] = True
            for kind, key in parse_input(os.read(fd, 1024).decode(errors="ignore")):
                if kind != "key":
                    continue
                if key in ("j", "k"):
                    scroll = max(0, min(top, scroll + (1 if key == "j" else -1)))
                elif key == "n":
                    i, scroll = (i + 1) % len(queue), 0
                elif key in ("\r", "\n"):
                    save_cursor({"focus": "party", "sel": a["pane"], "squad": None})
                    tmux("switch-client", "-t", a["pane"])
                    return
                elif key in ("q", "\x1b"):
                    return
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write(MOUSE_OFF + "\033[?7h\033[?25h\n")
        sys.stdout.flush()


HIDE_AFTER = 2.0
ART_SETTLE = 1.0


def run_ui(mode, fixture=None):
    """Main loop of the popup and the sidebar: read the snapshot every second, redraw only on change."""
    me = os.environ.get("TMUX_PANE", "")
    if mode == "sidebar" and not fixture:
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
    # a popup is not a pane: tmux 3.8 forwards its passthrough only when allow-passthrough is on globally (the user's tmux.conf)
    art = (
        load_art()
        if not fixture
        and art_supported(
            tmux("show-option", "-gqv", "@party_art").strip(),
            tmux("display-message", "-p", "#{client_termname}").strip(),
        )
        and (mode == "sidebar" or tmux("show-option", "-gqv", "allow-passthrough").strip() in ("on", "all"))
        else None
    )
    sent, was_visible = set(), False
    hidden_since = shown_since = None
    resized = [False]
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
            info = snap["panes"].get(me) if mode == "sidebar" else None
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
                    sys.stdout.write(kitty_image(img, *art[img]))
                if need - sent:
                    sys.stdout.flush()  # without this flush the last chunk stays buffered when the frame is unchanged
                sent |= need
            was_visible = show_art
            try:  # ask the terminal: shutil.get_terminal_size trusts COLUMNS, which goes stale after a resize
                size = os.get_terminal_size(sys.stdout.fileno())
            except OSError:
                size = shutil.get_terminal_size()
            lines = (capture(st["sel"]) if not fixture else []) if st["peek"] and st["sel"] and visible else None
            try:
                frame = render(
                    towns,
                    size.columns - 1,
                    st["sel"],
                    lines,
                    mode,
                    size.lines,
                    row_map,
                    st["focus"],
                    st["squad"],
                    int(time.time()),
                    art is not None,
                    snap["panes"].get(os.environ.get("TMUX_PANE", ""), {}).get("session")
                    or (here or {}).get("session"),
                )
            except Exception:  # noqa: BLE001 show the error instead of ending the sidebar
                log_error()
                frame = f" render error, see\n {ERROR_LOG}"
            if frame != last_frame:  # overwrite line by line without clearing, so the spinner does not flicker
                sys.stdout.write("\033[H" + "\033[K\n".join(frame.split("\n")) + "\033[K\033[J")
                sys.stdout.flush()
                last_frame, frame_lines = frame, frame.split("\n")
            deadline = time.time() + 1
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
                    action = handle_key(value, st, towns, mode)
                if action in ("jump", "jump_squad"):
                    save_cursor(st)  # save first, so the destination sidebar wakes up with the same selection
                if action == "jump":
                    # a pane id target switches session, window and pane together
                    tmux("switch-client", "-t", st["sel"])
                    done = mode == "popup"
                elif action == "jump_squad":
                    tmux("switch-client", "-t", "=" + towns[st["squad"]]["name"])  # =: exact name match
                    done = mode == "popup"
                elif action == "report":
                    open_report(st["sel"])
                elif action == "back":
                    tmux("select-pane", "-l")
                elif action == "hide":
                    # let the server do it: killing panes from here would kill this sidebar first
                    tmux("run-shell", "-b", f"{EXE} --toggle")
                    done = True
                elif action == "close":
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
        sys.stdout.write(MOUSE_OFF + "\033[?7h\033[?25h" + ("" if mode == "sidebar" else "\n"))
        sys.stdout.flush()


def note_click(row, target, frame_lines):
    line = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", frame_lines[row]) if 0 <= row < len(frame_lines) else ""
    try:
        with open(os.path.join(PARTY_DIR, "last-click"), "w") as f:
            f.write(f"{time.strftime('%F %T')} row={row} target={target} line={line}\n")
    except OSError:
        pass
