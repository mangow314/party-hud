"""Child processes, command lines and start times of tmux panes, from /proc on Linux and ps elsewhere."""

import os
import subprocess
import time

HAVE_PROC = os.path.isdir("/proc/self")


def parse_ps(text):
    """Output of `ps -axo pid=,ppid=,lstart=,args=` (LC_ALL=C) -> {pid: (ppid, args, start epoch)}.
    lstart is always 5 fields, e.g. "Wed Nov  4 11:46:42 2026"."""
    out = {}
    for line in text.splitlines():
        f = line.split()
        if len(f) < 8:
            continue
        try:
            start = time.mktime(time.strptime(" ".join(f[2:7]), "%a %b %d %H:%M:%S %Y"))
        except ValueError:
            continue
        out[f[0]] = (f[1], f[7:], start)
    return out


_ps_memo = [0.0, {}]


def proc_table():
    """Process table from ps when there is no /proc; one ps call per second at most."""
    if time.time() - _ps_memo[0] > 1:
        try:
            text = subprocess.run(
                ["ps", "-axo", "pid=,ppid=,lstart=,args="],
                capture_output=True,
                text=True,
                timeout=3,
                env=dict(os.environ, LC_ALL="C"),
                check=False,
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            text = ""
        _ps_memo[:] = [time.time(), parse_ps(text)]
    return _ps_memo[1]


def proc_children(pid):
    if HAVE_PROC:
        try:
            with open(f"/proc/{pid}/task/{pid}/children") as f:
                return f.read().split()
        except OSError:
            return []
    return [k for k, v in proc_table().items() if v[0] == str(pid)]


def proc_args(pid):
    if HAVE_PROC:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                return [a.decode(errors="ignore") for a in f.read().split(b"\0") if a]
        except OSError:
            return None
    hit = proc_table().get(str(pid))
    return hit[1] if hit else None


def proc_alive(pid):
    try:
        os.kill(int(pid), 0)
    except PermissionError:
        return True  # exists, owned by another user
    except (OSError, ValueError):
        return False
    return True


def child_cmdlines(pid, depth=3):
    out = []
    for k in proc_children(pid):
        args = proc_args(k)
        if args is None:
            continue
        out.append(args)
        if depth > 1:
            out += child_cmdlines(k, depth - 1)
    return out


def proc_tree(pane_pid):
    """The pane process and its descendants (4 levels), breadth first."""
    todo = [str(pane_pid)] if pane_pid else []
    for _ in range(4):
        yield from todo
        todo = [k for pid in todo for k in proc_children(pid)]


def proc_start(pid):
    """Start time in epoch seconds, or None. Field 22 of /proc/<pid>/stat is in clock ticks since boot."""
    if not HAVE_PROC:
        hit = proc_table().get(str(pid))
        return hit[2] if hit else None
    try:
        with open(f"/proc/{pid}/stat") as f:
            ticks = int(f.read().rsplit(")", 1)[1].split()[19])
        with open("/proc/stat") as f:
            btime = next(int(line.split()[1]) for line in f if line.startswith("btime "))
    except (OSError, ValueError, IndexError, StopIteration):
        return None
    return btime + ticks / os.sysconf("SC_CLK_TCK")
