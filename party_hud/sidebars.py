"""Sidebar panes: open, close, restart, hooks, widths."""

import fcntl
import json
import math
import os
import re
import shlex
import shutil
import sys
import time
import zlib
from datetime import datetime, timezone

from .art import ART_MIN_WIDTH
from .collect import (
    AGENT_CMDS,
    FIELD_SEP,
    READ_ONLY_CMDS,
    agent_kind,
    get_snapshot,
    lonely_sidebars,
    read_seen,
    subagent_unanswered,
)
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
    """Mark a pane as the quest report. allow-passthrough, on this pane only, lets the images reach the outer terminal.
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


SELECT_PANE_COLS = 82  # run_select draws one column less, so the banner is the 10-row 4:1 image


def select_span(win_w):
    """(width, left column) of the select screen's floating pane: SELECT_PANE_COLS wide at most, centred."""
    cols = min(SELECT_PANE_COLS, win_w)
    return cols, (win_w - cols) // 2


def open_report_pane(target, pane, select=False):
    """Open the quest report (of pane, or of whoever waits first) as a floating pane on tmux 3.8+, else beside the pane in target's window. With select, the pane runs the select screen instead, narrower than the report."""
    cmd = f"{EXE} --select" if select else f"{EXE} --report {shlex.quote(pane)}" if pane else f"{EXE} --report"
    host = report_host(target)
    where = ("-t", host) if host else ()
    if has_new_pane():
        size = ("-x80%", "-X10%")
        if select:
            win_w = tmux("display-message", "-p", *where, "#{window_width}").strip()
            if win_w.isdigit() and int(win_w) > 0:
                cols, left = select_span(int(win_w))
                size = (f"-x{cols}", f"-X{left}")
        args = ["new-pane", size[0], "-y80%", size[1], "-Y10%", "-T", " Party " if select else " Report ", *where]
    else:
        args = ["split-window", "-h", "-l", "50%", *where]
    pid = tmux(*args, "-P", "-F", "#{pane_id}", cmd).strip()
    if pid:
        mark_report(pid)


def fit_report_pane(pane, select):
    """Give a floating pane the select screen's size and place (select) or the report page's (80% of the window, from 10% / 10%). Anything else: nothing."""
    if not has_new_pane():
        return
    info = tmux("display-message", "-p", "-t", pane, "#{pane_floating_flag} #{window_width} #{window_height}").split()
    if len(info) != 3 or info[0] != "1" or not all(v.isdigit() for v in info[1:]):
        return
    win_w, win_h = int(info[1]), int(info[2])
    cols, left = select_span(win_w) if select else (win_w * 8 // 10, win_w // 10)
    tmux(
        "resize-pane", "-t", pane, "-x", str(cols), "-y", str(win_h * 8 // 10),
        ";", "move-pane", "-t", pane, "-X", str(left), "-Y", str(win_h // 10),
    )  # fmt: skip


SUMMON_POLL = 1.0


def summon(agent, cwd, window, timeout, read_only=False, here=False):
    """(rc, stdout, stderr) for party.py --summon. rc: 0 ready (stdout: pane id), 2 bad arguments or tmux failure, 3 timeout,
    6 the caller is crew of a lead whose pane still exists (it reports to the lead instead).
    Default: a window in the detached session crew-<caller pane number> (created at the caller's window size);
    window: a new window in the caller's session; here: a split beside the caller.
    Ready = the pane's agent is recognised, two polls in a row see the same screen (CRC32), and the snapshot lists the pane
    (so --ask and --report-text, which read the snapshot, accept it right away)."""
    if agent not in AGENT_CMDS:
        return 2, "", f"unknown agent: {agent} (one of {', '.join(AGENT_CMDS)})\n"
    if read_only and agent not in READ_ONLY_CMDS:
        return 2, "", f"{agent} has no enforced read-only mode (only: {', '.join(READ_ONLY_CMDS)})\n"
    if window and here:
        return 2, "", "--window and --here are mutually exclusive\n"
    caller = os.environ.get("TMUX_PANE", "")
    if not caller:
        return 2, "", "not inside tmux ($TMUX_PANE is not set)\n"
    if not math.isfinite(timeout):
        return 2, "", f"bad timeout: {timeout}\n"
    cwd = os.path.abspath(cwd or os.getcwd())
    if not os.path.isdir(cwd):
        return 2, "", f"not a directory: {cwd}\n"
    rc, out, err = tmux_run(["display-message", "-p", "-t", caller, "#{@party_lead}"])
    if rc != 0:
        return 2, "", err or f"no such pane: {caller}\n"
    lead = out.rstrip("\n")
    if lead and tmux_run(["display-message", "-p", "-t", lead, "#{pane_id}"])[0] == 0:
        return 6, "", f"{caller} is crew of {lead}: report to your lead instead of summoning\n"
    cmd = (READ_ONLY_CMDS if read_only else AGENT_CMDS)[agent]
    if window:
        where = ["new-window"]
    elif here:
        where = ["split-window", "-t", caller]
    else:
        crew = f"crew-{caller[1:]}"
        if tmux_run(["has-session", "-t", f"={crew}"])[0] == 0:
            where = ["new-window", "-d", "-t", f"{crew}:"]
        else:
            rc, out, err = tmux_run(
                ["display-message", "-p", "-t", caller, FIELD_SEP.join(["#{window_width}", "#{window_height}"])]
            )
            size = out.strip().split(FIELD_SEP)
            if rc != 0 or len(size) != 2:
                return 2, "", err or f"cannot read the window size of {caller}\n"
            where = ["new-session", "-d", "-s", crew, "-x", size[0], "-y", size[1]]
    # tmux expands formats in -c, and ## is a literal #
    rc, out, err = tmux_run([*where, "-P", "-F", "#{pane_id}", "-c", cwd.replace("#", "##"), cmd])
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
        if (
            digest is not None
            and digest == last
            and any(a["pane"] == pane for t in get_snapshot()["towns"] for a in t["agents"])
        ):
            return 0, pane + "\n", ""
        last = digest
        left = deadline - time.monotonic()
        if left <= 0:
            return 3, "", f"timed out waiting for {pane}\n"
        time.sleep(min(SUMMON_POLL, left))


def dismiss(pane):
    """(rc, stdout, stderr) for party.py --dismiss. rc: 0 pane closed, 2 not in tmux, bad or missing pane, 4 not an agent,
    6 not allowed (not summoned by the caller, still working, waiting for input, or its report is not read yet)."""
    caller = os.environ.get("TMUX_PANE", "")
    if not caller:
        return 2, "", "not inside tmux ($TMUX_PANE is not set)\n"
    if not pane.startswith("%") or not pane[1:].isdigit():
        return 2, "", f"not a pane id: {pane}\n"
    rc, out, err = tmux_run(["display-message", "-p", "-t", pane, "#{@party_lead}"])
    if rc != 0:
        return 2, "", err or f"no such pane: {pane}\n"
    lead = out.rstrip("\n")
    agent = next((a for t in get_snapshot()["towns"] for a in t["agents"] if a["pane"] == pane), None)
    if agent is None:
        return 4, "", f"not a known agent: {pane}\n"
    if lead != caller:
        return 6, "", f"{pane}: not summoned by you\n"
    if agent["status"] == "working" or agent.get("summons") or subagent_unanswered(agent):
        return 6, "", f"{pane}: still working\n"
    if agent["status"] == "waiting":
        return 6, "", f"{pane}: waiting for input, not dismissed\n"
    if agent["status"] == "done" and read_seen().get(pane, -1) < agent.get("round", 0):
        return 6, "", f"{pane}: report not read yet; run --report-text first\n"
    rc, _, err = tmux_run(["kill-pane", "-t", pane])
    if rc != 0:
        return 2, "", err or f"tmux could not close {pane}\n"
    return 0, "", ""


CREW_KEEP_DAYS = 14


def _utc(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _crew_root():
    return os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "party-hud", "crew")


def _crew_session(pane, now):
    root = _crew_root()
    os.makedirs(root, exist_ok=True)
    mine = sorted(
        d for d in os.listdir(root) if d.partition("-")[2] == pane[1:] and os.path.isdir(os.path.join(root, d))
    )
    if mine:
        return os.path.join(root, mine[-1])
    return _crew_new_session(pane, now)


def _crew_new_session(pane, now):
    path = os.path.join(_crew_root(), f"{_utc(now)}-{pane[1:]}")
    os.makedirs(path, exist_ok=True)
    return path


def _crew_rounds(session):
    return sorted(d for d in os.listdir(session) if re.fullmatch(r"round-\d{3,}", d))


def _crew_write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _crew_run(fn, *args):
    """ "" when saved, else the message for stderr."""
    try:
        fn(*args)
    except OSError as e:
        return f"could not save to {_crew_root()}: {e}\n"
    return ""


def _crew_summoned(pane):
    root = _crew_root()
    cutoff = time.time() - CREW_KEEP_DAYS * 86400
    if os.path.isdir(root):
        for d in os.listdir(root):
            path = os.path.join(root, d)
            if os.path.isdir(path) and not os.path.islink(path) and os.path.getmtime(path) < cutoff:
                shutil.rmtree(path)
    _crew_new_session(pane, time.time())


def _crew_asked(pane, text, sent, agent, cwd):
    session = _crew_session(pane, sent)
    rounds = _crew_rounds(session)
    path = os.path.join(session, f"round-{int(rounds[-1][6:]) + 1 if rounds else 1:03d}")
    os.mkdir(path)
    _crew_write(os.path.join(path, "question.md"), text)
    meta = {"asked_at": _utc(sent), "pane": pane, "agent": agent, "cwd": cwd}
    _crew_write(os.path.join(path, "meta.json"), json.dumps(meta, ensure_ascii=False, indent=2) + "\n")


def _crew_replied(pane, reply, rc):
    now = time.time()
    session = _crew_session(pane, now)
    rounds = _crew_rounds(session)
    if rounds:
        path = os.path.join(session, rounds[-1])
    else:
        path = os.path.join(session, "round-001")
        os.mkdir(path)
    try:
        with open(os.path.join(path, "meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
    except FileNotFoundError:
        meta = {"pane": pane}
    meta.update(replied_at=_utc(now), rc=rc)
    _crew_write(os.path.join(path, "reply.md"), reply)
    _crew_write(os.path.join(path, "meta.json"), json.dumps(meta, ensure_ascii=False, indent=2) + "\n")


def crew_summoned(pane):
    """Start the pane's session directory and drop sessions older than CREW_KEEP_DAYS. Returns "" or an error message."""
    return _crew_run(_crew_summoned, pane)


def crew_asked(pane, text, sent, agent, cwd):
    """Save a sent question as the next round. Returns "" or an error message."""
    return _crew_run(_crew_asked, pane, text, sent, agent, cwd)


def mark_seen(pane, rnd):
    """Record in seen.json that the report of round rnd of pane was read; never lowers a value. Raises OSError."""
    os.makedirs(PARTY_DIR, exist_ok=True)
    path = os.path.join(PARTY_DIR, "seen.json")
    fd = os.open(os.path.join(PARTY_DIR, "seen.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        seen = read_seen()
        if seen.get(pane, -1) >= rnd:
            return
        seen[pane] = rnd
        with open(f"{path}.{os.getpid()}", "w") as f:
            json.dump(seen, f)
        os.replace(f"{path}.{os.getpid()}", path)
    finally:
        os.close(fd)


def crew_replied(pane, reply, rc):
    """Save a fetched reply into the pane's latest round. Returns "" or an error message."""
    return _crew_run(_crew_replied, pane, reply, rc)


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
    if tmux("display-message", "-p", "-t", window_id, "#{session_name}").strip().startswith("crew-"):
        return
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
