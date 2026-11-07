"""Sidebar panes: open, close, restart, hooks, widths."""

import math
import os
import re
import shlex
import sys
import time
import zlib

from .art import ART_MIN_WIDTH
from .collect import AGENT_CMDS, FIELD_SEP, agent_kind, lonely_sidebars
from .common import CURSOR, PARTY_DIR, ROOT, tmux, tmux_run

SIDEBAR_WIDTH = 34
SIDEBAR_MIN = ART_MIN_WIDTH


EXE = shlex.join(
    [sys.executable, os.path.join(ROOT, "party.py")]
)  # run through python (no exec bit needed); quoted for paths with spaces


def mark_sidebar(pane):
    """Mark a pane as a sidebar. remain-on-exit keeps a stopped (hidden) sidebar's pane so wake can respawn it; the empty format hides "Pane is dead".
    allow-passthrough lets the images reach the outer terminal; set on this pane only, a global setting would let any program bypass tmux."""
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
        "allow-passthrough",
        "on",
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


def mark_report(pane):
    """Mark a pane as the quest report. allow-passthrough, on this pane only, lets the portrait reach the outer terminal.
    No remain-on-exit: the pane closes when the report ends."""
    tmux(
        "set-option",
        "-p",
        "-t",
        pane,
        "@party_report",
        "1",
        ";",
        "set-option",
        "-p",
        "-t",
        pane,
        "allow-passthrough",
        "on",
    )


PANE_FLAGS = "s#{@party_sidebar} r#{@party_report}"  # always two words: s or s1, r or r1
_new_pane = None


def has_new_pane():
    """tmux 3.8 added new-pane (floating panes); it is told apart by the O flag in its usage, not by the version string."""
    global _new_pane
    if _new_pane is None:
        usage = re.search(r"\[-([A-Za-z]+)\]", tmux("list-commands", "new-pane"))
        _new_pane = bool(usage and "O" in usage[1])
    return _new_pane


def report_host(target):
    """The pane to open the report beside: the target window's active pane, unless that is a sidebar or a report."""
    rows = [
        l.split()
        for l in tmux(
            "list-panes", *(("-t", target) if target else ()), "-F", "#{pane_id} #{pane_active} " + PANE_FLAGS
        ).splitlines()
    ]
    plain = [r for r in rows if len(r) == 4 and r[2:] == ["s", "r"]]
    return next((r[0] for r in plain if r[1] == "1"), plain[0][0] if plain else target)


def open_report_pane(target, pane):
    """Open the quest report (of pane, or of whoever waits first) as a floating pane on tmux 3.8+, else beside the pane in target's window."""
    cmd = f"{EXE} --report {shlex.quote(pane)}" if pane else f"{EXE} --report"
    host = report_host(target)
    where = ("-t", host) if host else ()
    if has_new_pane():
        args = ["new-pane", "-x80%", "-y80%", "-X10%", "-Y10%", "-T", " Report ", *where]
    else:
        args = ["split-window", "-h", "-l", "50%", *where]
    pid = tmux(*args, "-P", "-F", "#{pane_id}", cmd).strip()
    if pid:
        mark_report(pid)


SUMMON_POLL = 1.0


def summon(agent, cwd, window, timeout):
    """(rc, stdout, stderr) for party.py --summon. rc: 0 ready (stdout: pane id), 2 bad arguments or tmux failure, 3 timeout.
    Ready = the pane's agent is recognised and two collections in a row see the same screen (CRC32)."""
    if agent not in AGENT_CMDS:
        return 2, "", f"unknown agent: {agent} (one of {', '.join(AGENT_CMDS)})\n"
    caller = os.environ.get("TMUX_PANE", "")
    if not caller:
        return 2, "", "not inside tmux ($TMUX_PANE is not set)\n"
    if not math.isfinite(timeout):
        return 2, "", f"bad timeout: {timeout}\n"
    cwd = os.path.abspath(cwd or os.getcwd())
    if not os.path.isdir(cwd):
        return 2, "", f"not a directory: {cwd}\n"
    where = ["new-window"] if window else ["split-window", "-t", caller]
    rc, out, err = tmux_run([*where, "-P", "-F", "#{pane_id}", "-c", cwd, AGENT_CMDS[agent]])
    pane = out.strip()
    if rc != 0 or not pane:
        return 2, "", err or "tmux could not open the pane\n"
    tmux("set-option", "-p", "-t", pane, "@party_lead", caller)
    deadline, last = time.monotonic() + timeout, None
    while True:
        rc, out, err = tmux_run(
            ["display-message", "-p", "-t", pane, FIELD_SEP.join(["#{pane_current_command}", "#{pane_pid}"])]
        )
        if rc != 0:
            return 2, "", err or f"no such pane: {pane}\n"
        cmd, _, pid = out.strip().partition(FIELD_SEP)
        digest = None
        if agent_kind(cmd, pid):
            digest = zlib.crc32(tmux("capture-pane", "-p", "-t", pane).encode())
        if digest is not None and digest == last:
            return 0, pane + "\n", ""
        last = digest
        left = deadline - time.monotonic()
        if left <= 0:
            return 3, "", f"timed out waiting for {pane}\n"
        time.sleep(min(SUMMON_POLL, left))


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
    for line in tmux("list-panes", "-a", "-F", "#{pane_id} #{window_id} " + PANE_FLAGS).splitlines():
        parts = line.split()
        if len(parts) == 4:
            panes[parts[0]] = {"window": parts[1], "sidebar": "s1" in parts[2:] or "r1" in parts[2:]}
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
