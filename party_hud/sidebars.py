"""Sidebar panes: open, close, restart, hooks, widths."""

import os
import shlex
import sys

from .art import ART_MIN_WIDTH
from .collect import lonely_sidebars
from .common import CURSOR, PARTY_DIR, ROOT, tmux

SIDEBAR_WIDTH = 34
SIDEBAR_MIN = ART_MIN_WIDTH


EXE = shlex.join(
    [sys.executable, os.path.join(ROOT, "party.py")]
)  # run through python (no exec bit needed); quoted for paths with spaces


def mark_sidebar(pane):
    """Mark a pane as a sidebar. remain-on-exit keeps a stopped (hidden) sidebar's pane so wake can respawn it; the empty format hides "Pane is dead"."""
    tmux(
        "set-option",
        "-p",
        "-t",
        pane,
        "@party_sidebar",
        "1",
        ";",
        "set-option",
        "-p",
        "-t",
        pane,
        "remain-on-exit",
        "on",
        ";",
        "set-option",
        "-p",
        "-t",
        pane,
        "remain-on-exit-format",
        "",
    )


def install_hooks():
    hook = f'run-shell -b "{EXE} --ensure #{{window_id}}"'
    reflow_hook = f'run-shell -b "{EXE} --reflow #{{window_id}}"'
    nudge_hook = f'run-shell -b "{EXE} --nudge #{{window_id}}"'  # the hook expands to the window you switched to
    tidy_hook = f'run-shell -b "{EXE} --tidy"'
    tmux(
        "set-option",
        "-g",
        "@party_sidebar_on",
        "1",
        ";",
        "set-hook",
        "-g",
        "after-kill-pane[90]",
        tidy_hook,
        ";",
        "set-hook",
        "-g",
        "client-attached[90]",
        nudge_hook,
        ";",
        "set-hook",
        "-g",
        "after-new-window[90]",
        hook,
        ";",
        "set-hook",
        "-g",
        "after-new-session[90]",
        hook,
        ";",
        "set-hook",
        "-g",
        "window-resized[90]",
        reflow_hook,
        ";",
        "set-hook",
        "-g",
        "client-session-changed[90]",
        nudge_hook,
        ";",
        "set-hook",
        "-g",
        "session-window-changed[90]",
        nudge_hook,
    )


def nudge(window_id=""):
    """After a session/window switch: drop the snapshot, touch the cursor file so every sidebar wakes, restart this window's sidebar, fix its width
    (a window that was not resized gets no window-resized hook)."""
    window_id = window_id or tmux("display-message", "-p", "#{window_id}").strip()
    if window_id:
        wake(window_id)
        reflow(window_id)
    try:
        os.remove(os.path.join(PARTY_DIR, "snapshot.json"))
    except OSError:
        pass
    try:
        os.utime(CURSOR)
    except OSError:
        pass


def wake(window_id):
    for line in tmux("list-panes", "-t", window_id, "-F", "#{pane_id} #{@party_sidebar} #{pane_dead}").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] == "1" and parts[2] == "1":
            tmux("respawn-pane", "-t", parts[0], f"{EXE} --sidebar")


def tidy():
    """After kill-pane: close windows left with only a sidebar. Panes whose program exited are handled by the collector
    (pane-exited is a pane hook and cannot be set with -g)."""
    panes = {}
    for line in tmux("list-panes", "-a", "-F", "#{pane_id} #{window_id} #{@party_sidebar}").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            panes[parts[0]] = {"window": parts[1], "sidebar": len(parts) == 3 and parts[2] == "1"}
    for pane in lonely_sidebars(panes):
        tmux("kill-pane", "-t", pane)


def sidebar_widths():
    out = []
    for line in tmux("list-panes", "-a", "-F", "#{pane_id} #{@party_sidebar} #{pane_width}").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] == "1":
            out.append((parts[0], int(parts[2])))
    return out


def desired_width():
    return max(SIDEBAR_MIN, int(tmux("show-option", "-gqv", "@party_sidebar_width").strip() or SIDEBAR_WIDTH))


def reflow(window_id):
    """After a window resize (tmux scales every pane): put this window's sidebar back to its width."""
    want = desired_width()
    for line in tmux("list-panes", "-t", window_id, "-F", "#{pane_id} #{@party_sidebar} #{pane_width}").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] == "1" and int(parts[2]) != want:
            tmux("resize-pane", "-t", parts[0], "-x", str(want))


def remember_width():
    """After a border drag: the sidebar whose width differs from the setting was dragged; store its width and apply it to all."""
    want = desired_width()
    widths = sidebar_widths()
    dragged = next((w for _, w in widths if w != want), None)
    if dragged is None:
        return
    dragged = max(SIDEBAR_MIN, dragged)
    tmux("set-option", "-g", "@party_sidebar_width", str(dragged))
    for pane, w in widths:
        if w != dragged:
            tmux("resize-pane", "-t", pane, "-x", str(dragged))


def ensure(window_id):
    if "1" in tmux("list-panes", "-t", window_id, "-F", "#{@party_sidebar}").split():
        return
    pid = tmux(
        "split-window",
        "-hbf",
        "-d",
        "-l",
        str(desired_width()),
        "-t",
        window_id,
        "-P",
        "-F",
        "#{pane_id}",
        f"{EXE} --sidebar",
    ).strip()
    if pid:
        mark_sidebar(pid)


def toggle():
    panes = [l.split() for l in tmux("list-panes", "-a", "-F", "#{pane_id} #{@party_sidebar}").splitlines()]
    sidebars = [p[0] for p in panes if len(p) == 2 and p[1] == "1"]
    if tmux("show-option", "-gqv", "@party_sidebar_on").strip() == "1" or sidebars:
        tmux(
            "set-option",
            "-gu",
            "@party_sidebar_on",
            ";",
            "set-hook",
            "-gu",
            "after-new-window[90]",
            ";",
            "set-hook",
            "-gu",
            "after-new-session[90]",
            ";",
            "set-hook",
            "-gu",
            "window-resized[90]",
            ";",
            "set-hook",
            "-gu",
            "client-session-changed[90]",
            ";",
            "set-hook",
            "-gu",
            "session-window-changed[90]",
            ";",
            "set-hook",
            "-gu",
            "after-kill-pane[90]",
            ";",
            "set-hook",
            "-gu",
            "client-attached[90]",
        )
        for p in sidebars:
            tmux("kill-pane", "-t", p)
    else:
        install_hooks()
        for wid in sorted(set(tmux("list-windows", "-a", "-F", "#{window_id}").split())):
            ensure(wid)
