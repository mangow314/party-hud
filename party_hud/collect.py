"""Read tmux, agent session files, transcripts and rollouts into one snapshot shared by all sidebars."""

import fcntl
import glob
import json
import math
import os
import subprocess
import time
import zlib
from datetime import datetime, timedelta

from .common import (
    CLASSES,
    CLAUDE_PROJECTS,
    CLAUDE_SESSIONS,
    PARTY_DIR,
    ROOT,
    STATUS_ORDER,
    WORKMUX_ICONS,
    printable,
    spread,
    tmux,
    tmux_run,
)

CLAUDE_STATUS = {"busy": "working", "waiting": "waiting"}
TMUX_FIELDS = [
    "session_name",
    "window_index",
    "window_name",
    "window_active",
    "session_attached",
    "pane_id",
    "pane_active",
    "pane_current_command",
    "pane_current_path",
    "@workmux_pane_status",
    "window_id",
    "window_panes",
    "@party_sidebar",
    "@party_report",
    "pane_pid",
    "pane_dead",
    "pane_tty",
    "@party_lead",
    "@xv",
]
# wrappers hide the agent (codex under node, scripts that spawn an agent), so child processes are checked too
AGENT_CMDS = {"claude": "claude", "codex": "codex", "agy": "agy", "grok": "grok"}


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


CODEX_SESSIONS = os.path.expanduser("~/.codex/sessions")


def proc_tree(pane_pid):
    """The pane process and its descendants (4 levels), breadth first."""
    todo = [str(pane_pid)] if pane_pid else []
    for _ in range(4):
        yield from todo
        todo = [k for pid in todo for k in proc_children(pid)]


def find_codex(pane_pid):
    return next((pid for pid in proc_tree(pane_pid) if any("codex" in a for a in proc_args(pid) or [])), None)


def codex_rollout(pane_pid, cwd="", panes=()):
    """The pane's codex rollout file, or None: the one a process in the pane holds open, else the rollout paired with it.
    `panes` (tmux panes) lets codex processes in the same cwd each take a different rollout."""
    codex_pid = None
    for pid in proc_tree(pane_pid):
        if codex_pid is None and any("codex" in a for a in proc_args(pid) or []):
            codex_pid = pid
        for fd in glob.glob(
            f"/proc/{pid}/fd/*"
        ):  # open files are visible on Linux only; elsewhere the fallback below is used
            try:
                target = os.readlink(fd)
            except OSError:
                continue
            if target.startswith(CODEX_SESSIONS) and target.endswith(".jsonl"):
                return target
    # Newer codex builds write the rollout from a background app-server, not from a process in the pane: use the rollout written after this codex started whose cwd is the pane's
    start = proc_start(codex_pid) if codex_pid else None
    if not (start and cwd):
        return None
    peers = [
        proc_start(peer)
        for p in panes
        if p.get("pane_current_path") == cwd and str(p.get("pane_pid")) != str(pane_pid)
        if (peer := find_codex(p.get("pane_pid", "")))
    ]
    peers = [t for t in peers if t is not None]
    return paired_rollout(cwd, start, peers) if peers else newest_rollout(cwd, start)


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


_rollout_meta = {}  # session_meta is the first line and never changes


def rollouts_since(cwd, since, root=CODEX_SESSIONS):
    """[(session start or None, mtime, path)] of rollouts modified after `since` whose session_meta.cwd is cwd.
    Only the date folders (YYYY/MM/DD) from `since` to today are searched."""
    out, day = [], datetime.fromtimestamp(since).date()
    while day <= datetime.now().date():
        for path in glob.glob(os.path.join(root, f"{day:%Y}", f"{day:%m}", f"{day:%d}", "rollout-*.jsonl")):
            try:
                mtime = os.path.getmtime(path)
                if mtime < since:
                    continue
                if path not in _rollout_meta:
                    with open(path) as f:
                        payload = json.loads(f.readline()).get("payload", {})
                    try:
                        began = _epoch(payload.get("timestamp"))
                    except (ValueError, AttributeError, TypeError):
                        began = None
                    _rollout_meta[path] = (payload.get("cwd"), began)
            except (OSError, ValueError, AttributeError):
                continue
            if _rollout_meta[path][0] == cwd:
                out.append((_rollout_meta[path][1], mtime, path))
        day += timedelta(days=1)
    return out


def newest_rollout(cwd, since, root=CODEX_SESSIONS):
    """Newest rollout modified after `since` whose session_meta.cwd is cwd, or None."""
    return max(((m, p) for _, m, p in rollouts_since(cwd, since, root)), default=(0, None))[1]


def paired_rollout(cwd, start, peer_starts, root=CODEX_SESSIONS):
    """Codex processes in one cwd, ordered by start time, take rollouts ordered by session_meta.timestamp one to one;
    a rollout taken by an earlier process is not reused. The rollout for the process started at `start`, or None."""
    starts = sorted([start, *peer_starts])
    rolls = sorted((t, p) for t, _, p in rollouts_since(cwd, starts[0] - 1, root) if t is not None)
    taken = set()
    for s in starts:
        hit = next(((t, p) for t, p in rolls if p not in taken and t >= s - 1), None)
        if hit is None:
            return None
        taken.add(hit[1])
        if s == start:
            return hit[1]
    return None


def codex_usage(path):
    """Last token_count in a rollout -> (context tokens used, context window), or None."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 256 * 1024))
            lines = f.read().splitlines()
    except OSError:
        return None
    for raw in reversed(lines):
        if b'"token_count"' not in raw:
            continue
        try:
            info = json.loads(raw)["payload"]["info"]
            return info["last_token_usage"]["total_tokens"], info["model_context_window"]
        except (ValueError, KeyError, TypeError):
            continue
    return None


def codex_report(path):
    """Last finished turn of a rollout -> {"text", "start", "end"} (epoch seconds, start may be None), or None."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 256 * 1024))
            lines = f.read().splitlines()
    except OSError:
        return None
    for raw in reversed(lines):
        if b'"task_complete"' not in raw:
            continue
        try:
            p = json.loads(raw)["payload"]
        except (ValueError, KeyError, TypeError):
            continue
        if p.get("type") != "task_complete":
            continue
        text = (p.get("last_agent_message") or "").strip()
        return {"text": text, "start": p.get("started_at"), "end": p.get("completed_at")} if text else None
    return None


ACTIVE_WINDOW = 4.0  # screen changed this recently = working (spinners and timers keep changing)


def screen_changed(panes, now):
    """{pane: screen changed recently}, for agents without a status file.
    Only a CRC32 of each screen is kept, in activity.json."""
    path = os.path.join(PARTY_DIR, "activity.json")
    try:
        with open(path) as f:
            seen = json.load(f)
    except (OSError, ValueError):
        seen = {}
    out, keep = {}, {}
    for pid in panes:
        digest = zlib.crc32(tmux("capture-pane", "-p", "-t", pid).encode())
        old = seen.get(pid)
        changed_at = now if not old or old[0] != digest else old[1]
        keep[pid] = [digest, changed_at]
        out[pid] = bool(old) and now - changed_at < ACTIVE_WINDOW
    try:
        os.makedirs(PARTY_DIR, exist_ok=True)
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(keep, f)
        os.replace(tmp, path)
    except OSError:
        pass
    return out


def agent_kind(cmd, pane_pid, cmdlines=child_cmdlines):
    if cmd in AGENT_CMDS:
        return AGENT_CMDS[cmd]
    if not pane_pid:
        return None
    for args in cmdlines(pane_pid):
        if not args:
            continue
        names = [os.path.basename(args[0])]
        if len(args) > 1 and (names[0] in ("node", "bun", "deno") or names[0].startswith("python")):
            names.append(os.path.basename(args[1]))
        hit = next((AGENT_CMDS[n] for n in names if n in AGENT_CMDS), None)
        if hit:
            return hit
    return None


FIELD_SEP = "|@party@|"  # printable: tmux 3.5 escapes control characters in -F output (0x1f becomes "\037")


def parse_panes(text):
    """`list-panes -F` output -> one dict per pane; lines with the wrong number of fields are skipped."""
    rows = (line.split(FIELD_SEP) for line in text.splitlines())
    return [dict(zip(TMUX_FIELDS, map(printable, r))) for r in rows if len(r) == len(TMUX_FIELDS)]


def read_tmux():
    fmt = FIELD_SEP.join(f"#{{{f}}}" for f in TMUX_FIELDS)
    try:
        out = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", fmt], capture_output=True, text=True, timeout=3, check=False
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return parse_panes(out)


def read_party(pane_id):
    try:
        with open(os.path.join(PARTY_DIR, pane_id.lstrip("%") + ".json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


_cache_memo = {}


def read_claude_sessions():
    """~/.claude/sessions/<pid>.json -> {pane_id: {sid, name, status}}, live processes only."""
    out = {}
    for path in glob.glob(os.path.join(CLAUDE_SESSIONS, "*.json")):
        try:
            with open(path) as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        pid, where = d.get("pid"), d.get("tmux") or ""
        if not pid or "%" not in where or not proc_alive(pid):
            continue
        out["%" + where.rsplit("%", 1)[1]] = {
            "sid": d.get("sessionId", ""),
            "name": printable(d.get("name") or ""),
            "status": d.get("status", ""),
        }
    return out


_transcript_memo = {}


def transcript_for(sid):
    if sid not in _transcript_memo:
        hits = glob.glob(os.path.join(CLAUDE_PROJECTS, "*", f"{glob.escape(sid)}.jsonl"))
        _transcript_memo[sid] = hits[0] if hits else None
    return _transcript_memo[sid]


def summons_for(transcript, now):
    """Subagents in flight: subagents/*.meta.json not finished, log touched in the last 15 min."""
    out = []
    for meta in glob.glob(os.path.join(transcript[: -len(".jsonl")], "subagents", "*.meta.json")):
        log = meta[: -len(".meta.json")] + ".jsonl"
        try:
            with open(meta) as f:
                d = json.load(f)
            if d.get("finished") or now - os.stat(log).st_mtime > 900:
                continue
        except (OSError, ValueError):
            continue
        out.append({"type": d.get("agentType", "agent"), "desc": d.get("description", "")})
    return out


def cache_info(path):
    """(epoch of the last API call, cache TTL seconds, context tokens sent), from the transcript tail; cached while the file is unchanged."""
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return None
    memo = _cache_memo.get(path)
    if memo and memo[0] == mtime:
        return memo[1]
    last, ttl, used = None, None, None
    try:
        with open(path, "rb") as f:
            end, carry = f.seek(0, os.SEEK_END), b""
            # attachments after a resume or compaction can push the last usage entry out of the tail: read further back
            while end and last is None:
                start = max(0, end - 256 * 1024)
                f.seek(start)
                lines = (f.read(end - start) + carry).split(b"\n")
                carry = lines.pop(0) if start else b""
                end = start
                last, ttl, used = _scan_usage(lines)
    except OSError:
        return None
    result = (last, ttl or 300, used) if last else None  # TTL unknown: assume the 5-minute default
    _cache_memo[path] = (mtime, result)
    return result


def _scan_usage(lines):
    """(time of the last main-thread usage entry, TTL seen from there back, its context tokens) in these lines."""
    last, ttl, used = None, None, None
    for raw in reversed(lines):
        if b'"usage"' not in raw:
            continue
        try:
            rec = json.loads(raw)
            usage = rec["message"]["usage"]
        except (ValueError, KeyError, TypeError):
            continue
        if rec.get("isSidechain"):
            continue
        if last is None and rec.get("timestamp"):
            # Python 3.10 fromisoformat does not accept a trailing Z
            last = datetime.fromisoformat(rec["timestamp"].replace("Z", "+00:00")).timestamp()
            used = sum(
                usage.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
            )
        cc = usage.get("cache_creation") or {}
        if cc.get("ephemeral_1h_input_tokens"):
            ttl = 3600
        elif cc.get("ephemeral_5m_input_tokens"):
            ttl = 300
        if last is not None and ttl:
            break
    return last, ttl, used


def _epoch(ts):
    # Python 3.10 fromisoformat does not accept a trailing Z
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() if ts else None


def claude_report(path, sidechain=False):
    """Final answer of the last answered turn -> {"text", "start", "end"} (epoch seconds, start may be None), or None.
    The answer is the text after the turn's last tool call. A prompt nobody answered (a `!` command, /cost) is skipped.
    A subagent's own log is all sidechain records: pass sidechain=True to read it."""
    texts, end, collecting, replied = [], None, True, False
    try:
        with open(path, "rb") as f:
            pos, carry = f.seek(0, os.SEEK_END), b""
            while pos:
                start = max(0, pos - 256 * 1024)
                f.seek(start)
                lines = (f.read(pos - start) + carry).split(b"\n")
                carry = lines.pop(0) if start else b""
                pos = start
                for raw in reversed(lines):
                    try:
                        rec = json.loads(raw)
                        content = rec["message"]["content"]
                    except (ValueError, KeyError, TypeError):
                        continue
                    if (rec.get("isSidechain") and not sidechain) or rec.get("isMeta"):
                        continue
                    blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
                    blocks = [b for b in blocks if isinstance(b, dict)]
                    kinds = {b.get("type") for b in blocks}
                    if rec.get("type") == "assistant":
                        replied = True
                        if "tool_use" in kinds:
                            if not texts:
                                return None
                            collecting = False
                        elif collecting:
                            said = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
                            if said:
                                texts.insert(0, said)
                                end = end or _epoch(rec.get("timestamp"))
                    elif rec.get("type") == "user":
                        if "tool_result" in kinds:
                            if not texts:
                                return None
                            collecting = False
                        elif replied:
                            if not texts:
                                return None
                            return {"text": "\n\n".join(texts), "start": _epoch(rec.get("timestamp")), "end": end}
    except OSError:
        return None
    return {"text": "\n\n".join(texts), "start": None, "end": end} if texts else None


def finished_subagents(transcript):
    """Subagents with `finished: true` in their meta -> [{"type", "desc", "text"}] (text is "" when the log has no final answer)."""
    out = []
    for meta in sorted(glob.glob(os.path.join(transcript[: -len(".jsonl")], "subagents", "*.meta.json"))):
        try:
            with open(meta) as f:
                d = json.load(f)
            if not d.get("finished"):
                continue
            rep = claude_report(meta[: -len(".meta.json")] + ".jsonl", sidechain=True)
            out.append(
                {
                    "type": d.get("agentType", "agent"),
                    "desc": d.get("description", ""),
                    "text": rep["text"] if rep else "",
                }
            )
        except (OSError, ValueError, AttributeError):
            continue
    return out


BORDER_START = "\u256d\u2570\u250c\u2514\u2500"
BOX_CHARS = BORDER_START + "\u2502\u256e\u256f\u2510\u2518\u2503"


def screen_report(pane):
    """Last paragraph of the screen, without the input box and status bar below it (agy, grok write no log).
    The bottom block is cut from the lowest border line (a line starting with a box-drawing corner or rule) up through the lines directly above it that also start with a box-drawing character, or up to the previous plain rule."""
    lines = [ln.rstrip() for ln in tmux("capture-pane", "-p", "-J", "-t", pane).split("\n")]
    border = [i for i, ln in enumerate(lines) if ln.strip() and ln.lstrip()[0] in BORDER_START]
    if border:
        top = border[-1]
        if lines[top].lstrip()[:1] == "\u2500" and len(border) > 1 and "" not in lines[border[-2] : top]:
            top = border[-2]
        while top > 0 and lines[top - 1].strip() and lines[top - 1].lstrip()[0] in BOX_CHARS:
            top -= 1
        lines = lines[:top]
    paras, cur = [], []
    for ln in lines + [""]:
        if ln:
            cur.append(ln)
        elif cur:
            paras.append("\n".join(cur))
            cur = []
    return {"text": paras[-1], "start": None, "end": None} if paras else None


def report_for(a):
    """The member's last report (shape of claude_report, Claude Code's with "subagents" added), or None. Claude Code and Codex write one; agy and grok are read off the screen."""
    if a["kind"] == "claude":
        rep = claude_report(a["transcript"]) if a.get("transcript") else None
        return dict(rep, subagents=finished_subagents(a["transcript"])) if rep else None
    if a["kind"] == "codex":
        panes = read_tmux()
        p = next((p for p in panes if p["pane_id"] == a["pane"]), None)
        path = codex_rollout(p.get("pane_pid", ""), p.get("pane_current_path", ""), panes) if p else None
        return codex_report(path) if path else None
    if a["kind"] in ("agy", "grok"):
        return screen_report(a["pane"])
    return None


def wait_channel(pane):
    return "party-" + pane.lstrip("%")


def report_text(pane, wait=False, timeout=600):
    """(rc, stdout, stderr) for party.py --report-text. rc: 0 ok, 2 bad or missing pane, 3 timeout, 4 not an agent.
    While the member works, sleep in tmux wait-for (woken by the collector) for up to 2 s, then read the snapshot again."""
    if not pane.startswith("%") or not pane[1:].isdigit():
        return 2, "", f"not a pane id: {pane}\n"
    if not math.isfinite(timeout):
        return 2, "", f"bad timeout: {timeout}\n"
    rc, _, err = tmux_run(["display-message", "-p", "-t", pane, "#{pane_id}"])
    if rc != 0:
        return 2, "", err or f"no such pane: {pane}\n"
    deadline = time.monotonic() + timeout
    while True:
        a = next((a for t in get_snapshot()["towns"] for a in t["agents"] if a["pane"] == pane), None)
        if a is None:
            rc, _, err = tmux_run(["display-message", "-p", "-t", pane, "#{pane_id}"])
            if rc != 0:
                return 2, "", err or f"no such pane: {pane}\n"
            return 4, "", f"not a known agent: {pane}\n"
        if not wait or a["status"] != "working":
            rep = report_for(a)
            return 0, (str(rep["text"]) + "\n") if rep else "", "" if rep else f"no report for {pane}\n"
        left = deadline - time.monotonic()
        if left <= 0:
            return 3, "", f"timed out waiting for {pane}\n"
        rc, _, err = tmux_run(["wait-for", wait_channel(pane)], timeout=min(SNAP_MAX_AGE, left))
        if rc not in (0, None):
            return 2, "", err


def group_under_leads(agents, owners):
    """Put each summoned member right after its lead and mark it with a["lead"] (the lead's pane); one level only.
    @party_lead names the lead; an xv pane goes under the only Claude of its window, else stays an ordinary member."""
    panes = {a["pane"]: a for a in agents}
    claudes = {}
    for a in agents:
        if a["kind"] == "claude" and not owners.get(a["pane"], ("", False, ""))[1]:
            claudes.setdefault(a["window"], []).append(a["pane"])
    lead_of = {}
    for a in agents:
        lead, xv, window = owners.get(a["pane"], ("", False, ""))
        if not lead and xv and len(claudes.get(window, [])) == 1:
            lead = claudes[window][0]
        if lead in panes and lead != a["pane"]:
            lead_of[a["pane"]] = lead
    lead_of = {k: v for k, v in lead_of.items() if v not in lead_of}
    out = []
    for a in agents:
        if a["pane"] not in lead_of:
            out.append(a)
            for b in agents:
                if lead_of.get(b["pane"]) == a["pane"]:
                    b["lead"] = a["pane"]
                    out.append(b)
    return out


def collect(fixture=None, now=None):
    """Snapshot: {"t": time, "towns": squads with their members, "panes": {pane_id: window info}}."""
    now = now or time.time()
    if fixture:
        with open(fixture) as f:
            data = json.load(f)
        panes = data["panes"]
        party, caches = data.get("party", {}), data.get("cache", {})
        now = data.get("now", now)
        sessions, transcripts, summons = data.get("sessions", {}), data.get("transcripts", {}), data.get("summons", {})
        get_party = lambda pid: party.get(pid, {})
        get_cache = lambda tx: tuple(caches[tx]) if tx in caches else None
        get_transcript = lambda sid: transcripts.get(sid)
        get_summons = lambda tx, now: summons.get(tx, [])
        children = data.get("children", {})
        get_cmdlines = lambda pid: children.get(pid, [])
        get_changed = lambda ps, now: {p: p in data.get("screen_changed", []) for p in ps}
        get_codex = lambda pane, pid, cwd: tuple(data["codex"][pane]) if pane in data.get("codex", {}) else None
    else:
        get_cmdlines, get_changed = child_cmdlines, screen_changed

        def get_codex(pane, pid, cwd):
            path = codex_rollout(pid, cwd, panes)
            return codex_usage(path) if path else None

        panes = read_tmux()
        sessions = read_claude_sessions()
        get_party, get_cache, get_transcript, get_summons = read_party, cache_info, transcript_for, summons_for

    towns, meta, here, owners = {}, {}, None, {}
    for p in panes:
        attached = p["session_attached"] not in ("", "0")
        if here is None and attached and p["window_active"] == "1":
            here = {"session": p["session_name"], "window": p.get("window_id", "")}
        aux = p.get("@party_sidebar") == "1" or p.get("@party_report") == "1"
        meta[p["pane_id"]] = {
            "visible": p["window_active"] == "1" and attached,
            "window": p.get("window_id", ""),
            "session": p["session_name"],
            "window_panes": int(p.get("window_panes") or 0),
            "sidebar": aux,
            "dead": p.get("pane_dead") == "1",
            "tty": p.get("pane_tty", ""),
        }
        owners[p["pane_id"]] = (p.get("@party_lead", ""), p.get("@xv") == "1", p.get("window_id", ""))
        if aux:
            continue
        t = towns.setdefault(p["session_name"], {"name": p["session_name"], "attached": attached, "agents": []})
        icon = p.get("@workmux_pane_status", "")
        sess = sessions.get(p["pane_id"], {})
        kind = "claude" if sess else agent_kind(p["pane_current_command"], p.get("pane_pid", ""), get_cmdlines)
        if not kind and not icon:
            continue
        kind = kind or "claude"
        native = CLAUDE_STATUS.get(sess.get("status"), "idle")
        status = WORKMUX_ICONS.get(icon) or native
        # workmux keeps 🤖 until Claude's notification hook fires, seconds after Claude itself reports waiting
        if status == "working" and native == "waiting":
            status = "waiting"
        info = get_party(p["pane_id"])
        sid = sess.get("sid") or info.get("session_id") or ""
        if info.get("session_id") and sid and info["session_id"] != sid:
            info = {}
        tx = info.get("transcript") or (get_transcript(sid) if sid else None)
        ci = get_cache(tx) if tx else None
        hp, sp = info.get("ctx_left"), None
        hp_max = info.get("ctx_size")
        left = round(hp * hp_max / 100) if hp is not None and hp_max else None
        if ci:
            last, ttl = ci[0], ci[1]
            sp = (max(0.0, ttl - (now - last)), ttl)
            if sp[0] == 0 and status == "idle":
                status = "sleep"
            used = ci[2] if len(ci) > 2 else None
            if hp is None and used:
                window = 1_000_000 if used > 200_000 else 200_000
                hp = max(0, round(100 - used * 100 / window))
                left, hp_max = max(0, window - used), window
        fresh = kind == "claude" and not ci
        if fresh and hp is None:
            hp = 100
        if kind == "codex":
            usage = get_codex(p["pane_id"], p.get("pane_pid", ""), p.get("pane_current_path", ""))
            if usage and usage[1]:
                hp = max(0, round(100 - usage[0] * 100 / usage[1]))
                left, hp_max = max(0, usage[1] - usage[0]), usage[1]
        t["agents"].append(
            {
                "name": sess.get("name") or (p["window_name"] if kind == "claude" else kind),
                "kind": kind,
                "pane": p["pane_id"],
                "window": p.get("window_id", ""),
                "status": status,
                "id": sid or p["pane_id"],
                "hp": hp,
                "hp_left": left,
                "hp_max": hp_max,
                "sp": sp,
                "fresh": fresh,
                "model": printable(info.get("model", "")),
                "summons": get_summons(tx, now) if tx else [],
                "transcript": tx,
                "focus": p["window_active"] == "1" and p["pane_active"] == "1" and t["attached"],
            }
        )

    others = [a for t in towns.values() for a in t["agents"] if a["kind"] != "claude" and a["status"] == "idle"]
    if others:
        changed = get_changed([a["pane"] for a in others], now)
        for a in others:
            if changed.get(a["pane"]):
                a["status"] = "working"
    for t in towns.values():
        t["agents"].sort(key=lambda a: STATUS_ORDER.index(a["status"]))
        t["agents"] = group_under_leads(t["agents"], owners)
        cls = spread([a["id"] for a in t["agents"]], len(CLASSES))
        for a in t["agents"]:
            a["cls"] = cls[a["id"]]
    return {"t": time.time(), "towns": list(towns.values()), "panes": meta, "here": here}


SNAP_MAX_AGE = 2.0
SNAP_VERSION = int(max(os.stat(p).st_mtime for p in glob.glob(os.path.join(ROOT, "party_hud", "*.py"))))


def mark_unseen(towns, state):
    """Mark members "done" when they stop working while you are not looking, until you look.
    state = last round's {pane: {"status", "unseen"}}. Changes towns in place; returns the new state."""
    out = {}
    for t in towns:
        for a in t["agents"]:
            prev = state.get(a["pane"], {})
            raw = a["status"]
            settled = raw in ("idle", "sleep")
            unseen = settled and not a["focus"] and (prev.get("unseen") or prev.get("status") == "working")
            out[a["pane"]] = {"status": raw, "unseen": unseen}
            if unseen:
                a["status"] = "done"
        t["agents"].sort(key=lambda a: STATUS_ORDER.index(a["status"]))
    return out


def bell_panes(prev, agents, panes):
    """Members that just started waiting or finished, out of sight -> (panes to ring, new state).
    prev None = first round, no bells. The collector rings for all: hidden windows have no sidebar process."""
    cur = {a["pane"]: a["status"] for a in agents}
    alert = ("waiting", "done")
    if prev is None:
        return [], cur
    ring = [
        p for p, s in cur.items() if s in alert and prev.get(p) not in alert and not panes.get(p, {}).get("visible")
    ]
    return ring, cur


def status_changed(prev, cur):
    """Members whose status differs from last round's (prev None = first round, none)."""
    if prev is None:
        return []
    return [p for p, s in cur.items() if p in prev and prev[p] != s]


def lonely_sidebars(panes):
    """Sidebar panes left alone in their window (the main pane exited)."""
    by_window = {}
    for pid, info in panes.items():
        by_window.setdefault(info["window"], []).append((pid, info["sidebar"]))
    return sorted(pid for ps in by_window.values() if all(sb for _, sb in ps) for pid, _ in ps)


def get_snapshot(fixture=None):
    """Read the shared snapshot. When older than 2 s, whoever gets snapshot.lock collects again; the others use the old one."""
    if fixture:
        return collect(fixture)
    path = os.path.join(PARTY_DIR, "snapshot.json")

    def load():
        try:
            with open(path) as f:
                snap = json.load(f)
        except (OSError, ValueError):
            return None
        # a snapshot from an older party.py may lack fields and crash this one
        return snap if snap.get("v") == SNAP_VERSION else None

    snap = load()
    if snap and time.time() - snap["t"] < SNAP_MAX_AGE:
        return snap
    os.makedirs(PARTY_DIR, exist_ok=True)
    fd = os.open(os.path.join(PARTY_DIR, "snapshot.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if snap:
                return snap
            fcntl.flock(fd, fcntl.LOCK_EX)
        again = load()
        if again and time.time() - again["t"] < SNAP_MAX_AGE:
            return again
        new = collect()
        # kept outside the snapshot: nudge deletes the snapshot on every window switch
        seen_path = os.path.join(PARTY_DIR, "unseen.json")
        try:
            with open(seen_path) as f:
                state = json.load(f)
        except (OSError, ValueError):
            state = {}
        state = mark_unseen(new["towns"], state)
        with open(f"{seen_path}.{os.getpid()}", "w") as f:
            json.dump(state, f)
        os.replace(f"{seen_path}.{os.getpid()}", seen_path)
        for pane in lonely_sidebars(new["panes"]):
            tmux("kill-pane", "-t", pane)
        bell_path = os.path.join(PARTY_DIR, "bells.json")
        try:
            with open(bell_path) as f:
                prev = json.load(f)
        except (OSError, ValueError):
            prev = None
        ring, cur = bell_panes(prev, [a for t in new["towns"] for a in t["agents"]], new["panes"])
        for pane in ring:
            try:  # O_NOCTTY: do not make this tty our controlling terminal
                fd_tty = os.open(new["panes"][pane]["tty"], os.O_WRONLY | os.O_NOCTTY)
                try:
                    os.write(fd_tty, b"\a")
                finally:
                    os.close(fd_tty)
            except (OSError, KeyError):
                pass
        for pane in status_changed(prev, cur):
            tmux("wait-for", "-S", wait_channel(pane))
        unread = sum(s in ("waiting", "done") for s in cur.values())
        if prev is None or unread != sum(s in ("waiting", "done") for s in prev.values()):
            tmux("set-option", "-g", "@party_reports", str(unread))
        with open(f"{bell_path}.{os.getpid()}", "w") as f:
            json.dump(cur, f)
        os.replace(f"{bell_path}.{os.getpid()}", bell_path)
        # collection count (read by tests and bench/live.sh), kept outside the snapshot for the same reason
        seq_path = os.path.join(PARTY_DIR, "collections")
        try:
            with open(seq_path) as f:
                seq = int(f.read() or 0) + 1
        except (OSError, ValueError):
            seq = 1
        with open(f"{seq_path}.{os.getpid()}", "w") as f:
            f.write(str(seq))
        os.replace(f"{seq_path}.{os.getpid()}", seq_path)
        new["seq"] = seq
        new["v"] = SNAP_VERSION
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(new, f)
        os.replace(tmp, path)
        return new
    finally:
        os.close(fd)
