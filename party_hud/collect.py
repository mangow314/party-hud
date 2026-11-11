"""Read tmux, agent session files, transcripts and rollouts into one snapshot shared by all sidebars."""

import fcntl
import glob
import json
import math
import os
import re
import subprocess
import time
import unicodedata
import zlib
from datetime import datetime, timedelta
from typing import Any

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
READ_ONLY_CMDS = {
    "claude": "claude --permission-mode plan",
    "codex": "codex -s read-only",
    "agy": "agy --mode plan",
    "grok": "grok --permission-mode plan",
}


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


def is_codex_proc(args):
    if not args:
        return False
    name = os.path.basename(args[0])
    if name in ("node", "bun", "deno") and len(args) > 1:
        return os.path.basename(args[1]) in ("codex", "codex.js")
    return name == "codex"


def find_codex(pane_pid):
    return next((pid for pid in proc_tree(pane_pid) if is_codex_proc(proc_args(pid))), None)


def codex_rollout(pane_pid, cwd="", panes=()):
    """The pane's codex rollout file, or None: the one a process in the pane holds open, else the rollout paired with it.
    `panes` (tmux panes) lets codex processes in the same cwd each take a different rollout."""
    codex_pid = None
    for pid in proc_tree(pane_pid):
        if codex_pid is None and is_codex_proc(proc_args(pid)):
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


def _tail_lines(path, size=256 * 1024):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - size))
            return f.read().splitlines()
    except OSError:
        return []


def codex_report(path):
    """Last finished turn of a rollout -> {"text", "start", "end"} (epoch seconds, start may be None), or None."""
    return _codex_answer(reversed(_tail_lines(path)))


def _codex_answer(lines):
    for raw in lines:
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


def codex_task(path):
    """Last finished turn of a rollout -> {"ask", "files", "cmds", "agents"}, or None when its task_started lies before the tail that is read. Codex runs edits through commands, so files and agents stay 0."""
    lines = _tail_lines(path)
    turn = None
    for raw in reversed(lines):
        if b'"task_complete"' not in raw:
            continue
        try:
            p = json.loads(raw)["payload"]
        except (ValueError, KeyError, TypeError):
            continue
        if p.get("type") == "task_complete":
            turn = p.get("turn_id")
            break
    ask, cmds, started = None, 0, False
    for raw in lines:
        if turn is None or (b'"item_completed"' not in raw and b'"task_started"' not in raw):
            continue
        try:
            p = json.loads(raw)["payload"]
        except (ValueError, KeyError, TypeError):
            continue
        if p.get("turn_id") != turn:
            continue
        if p.get("type") == "task_started":
            started = True
            continue
        item = p.get("item") or {}
        if not started:
            continue
        if item.get("type") == "UserMessage" and ask is None:
            parts = [
                c.get("text", "") for c in item.get("content") or [] if isinstance(c, dict) and c.get("type") == "text"
            ]
            ask = "\n".join(parts).strip() or None
        elif item.get("type") == "CommandExecution":
            cmds += 1
    return {"ask": ask, "files": 0, "cmds": cmds, "agents": 0} if started else None


def codex_live(path):
    """The turn in progress -> {"live": True, "task", "start", "end": None, "tool", "said", "prev"}, or None when the newest turn event is not a task_started.
    Same shape as claude_live: start = task_started's started_at, tool = newest tool call as one row, said = newest agent message, prev = codex_report-shaped answer of the turn before (or None).
    Only the last LIVE_TAIL bytes are read; a turn that began before that has no ask or start."""
    lines = _tail_lines(path, LIVE_TAIL)
    if not lines:
        return None
    turn, first = None, 0
    for i in range(len(lines) - 1, -1, -1):
        raw = lines[i]
        if b'"task_complete"' not in raw and b'"task_started"' not in raw:
            continue
        try:
            p = json.loads(raw)["payload"]
        except (ValueError, KeyError, TypeError):
            continue
        if p.get("type") == "task_complete":
            return None
        if p.get("type") == "task_started":
            turn, first = p, i
            break
    ask, cmds, tool, said = None, 0, None, None
    for raw in lines[first:]:
        try:
            rec = json.loads(raw)
            p = rec["payload"]
            item = p.get("item") or {}
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        if rec.get("type") == "response_item" and p.get("type") in (
            "function_call",
            "custom_tool_call",
            "local_shell_call",
        ):
            tool = tool_row(p)
        elif item.get("type") == "UserMessage" and ask is None and turn:
            ask = "\n".join(_codex_text(item)).strip() or None
        elif item.get("type") == "CommandExecution" and turn:
            cmds += 1
        elif item.get("type") == "AgentMessage":
            said = "\n".join(_codex_text(item)).strip() or said
    prev = _codex_answer(reversed(lines[:first]))
    start = turn.get("started_at") if turn else None
    task = {"ask": ask, "files": 0, "cmds": cmds, "agents": 0} if turn else {}
    return {"live": True, "task": task, "start": start, "end": None, "tool": tool, "said": said, "prev": prev}


def _codex_text(item):
    return [
        c.get("text", "")
        for c in item.get("content") or []
        if isinstance(c, dict) and str(c.get("type")).lower() == "text"
    ]


def tool_row(call):
    """One printable row for a Codex tool call: its name and the first line of its input."""
    raw = call.get("input") or call.get("arguments") or call.get("action") or ""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            pass
    if isinstance(raw, dict):
        raw = raw.get("cmd") or raw.get("command") or raw.get("query") or ""
    if isinstance(raw, list):
        raw = raw[-1] if raw else ""
    arg = next((ln.strip() for ln in str(raw).split("\n") if ln.strip()), "")[:300]
    return printable(
        f"{call.get('name') or call.get('type')}: {arg}" if arg else str(call.get("name") or call.get("type"))
    )


ACTIVE_WINDOW = 4.0  # screen changed this recently = working (spinners and timers keep changing)


def screen_changed(panes, now):
    """{pane: screen changed recently; (changed, True) while an agy permission menu is shown}, for agents without a status file.
    Only a CRC32 of each screen is kept, in activity.json."""
    path = os.path.join(PARTY_DIR, "activity.json")
    try:
        with open(path) as f:
            seen = json.load(f)
    except (OSError, ValueError):
        seen = {}
    out, keep = {}, {}
    for pid in panes:
        screen = tmux("capture-pane", "-p", "-t", pid)
        digest = zlib.crc32(screen.encode())
        old = seen.get(pid)
        changed_at = now if not old or old[0] != digest else old[1]
        keep[pid] = [digest, changed_at]
        out[pid] = bool(old) and now - changed_at < ACTIVE_WINDOW
        tail = [ln for ln in screen.splitlines() if ln.strip()][-15:]
        if any("Requesting permission for:" in ln for ln in tail):
            out[pid] = (out[pid], True)
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
        if len(args) > 1 and (names[0] in ("node", "bun", "deno") or names[0].lower().startswith("python")):
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
    """~/.claude/sessions/<pid>.json -> {pane_id: {pid, sid, name, status}}, live processes only."""
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
            "pid": str(pid),
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


def _records_backwards(f, limit=None):
    """Parsed (record, content) of a JSONL transcript from the end, at most limit bytes of it when given; lines that are not records are skipped."""
    pos, carry = f.seek(0, os.SEEK_END), b""
    floor = max(0, pos - limit) if limit else 0
    while pos > floor:
        start = max(floor, pos - 256 * 1024)
        f.seek(start)
        lines = (f.read(pos - start) + carry).split(b"\n")
        carry = lines.pop(0) if start else b""
        pos = start
        for raw in reversed(lines):
            try:
                rec = json.loads(raw)
                yield rec, rec["message"]["content"]
            except (ValueError, KeyError, TypeError):
                continue


def claude_report(path, sidechain=False):
    """Final answer of the last answered turn -> {"text", "start", "end"} (epoch seconds, start may be None), or None.
    The answer is the text after the turn's last tool call. A prompt nobody answered (a `!` command, /cost) is skipped.
    A subagent's own log is all sidechain records: pass sidechain=True to read it."""
    try:
        with open(path, "rb") as f:
            return _claude_answer(_records_backwards(f), sidechain)
    except OSError:
        return None


def _claude_answer(records, sidechain=False):
    texts, end, collecting, replied = [], None, True, False
    for rec, content in records:
        if (rec.get("isSidechain") and not sidechain) or rec.get("isMeta"):
            continue
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
        blocks = [b for b in blocks if isinstance(b, dict)]
        kinds = {b.get("type") for b in blocks}
        if rec.get("type") == "assistant":
            replied = True
            if "tool_use" in kinds:
                if not texts:
                    # Claude Code 2.1.x subagents deliver their report via a SubagentHandback tool call
                    handed = sidechain and next(
                        (
                            (b.get("input") or {}).get("message")
                            for b in blocks
                            if b.get("type") == "tool_use" and b.get("name") == "SubagentHandback"
                        ),
                        None,
                    )
                    if not isinstance(handed, str) or not handed.strip():
                        return None
                    texts.append(handed.strip())
                    end = _epoch(rec.get("timestamp"))
                collecting = False
            elif collecting:
                said = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
                if said:
                    texts.insert(0, said)
                    end = end or _epoch(rec.get("timestamp"))
        elif rec.get("type") == "user":
            if "tool_result" in kinds:
                if not texts and not sidechain:
                    return None
                collecting = False
            elif replied:
                if not texts:
                    return None
                return {"text": "\n\n".join(texts), "start": _epoch(rec.get("timestamp")), "end": end}
    return {"text": "\n\n".join(texts), "start": None, "end": end} if texts else None


FILE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
INJECTED_PREFIXES = (
    "<task-notification>",
    "<local-command-",
    "<bash-input>",
    "<bash-stdout>",
    "<bash-stderr>",
    "[Request interrupted",
)
SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
COMMAND_TAG = re.compile(r"<command-(name|args)>(.*?)</command-\1>", re.DOTALL)
# Claude Code wraps pasted text as <pasted_content id="x">...</pasted_content id="x">
PASTED_BLOCK = re.compile(r'<pasted_content id="([^"]*)">(.*?)</pasted_content id="\1">', re.DOTALL)
PASTED_OPEN = re.compile(r"<pasted_content\b[^>]*>[ \t]*\n?")


def claude_typed(rec, text):
    """The text the user typed in a type-user record, or None when Claude Code injected it (task notification, peer or plugin message, hook output, ! command, interrupt marker, compact summary) or nothing is left after removing system reminders.
    A slash command comes back as "/name args"."""
    origin = rec.get("origin")
    if (isinstance(origin, dict) and origin.get("kind") != "human") or rec.get("isCompactSummary"):
        return None
    text = SYSTEM_REMINDER.sub("", text).strip()
    if text.startswith(INJECTED_PREFIXES):
        return None
    tags = {k: v.strip() for k, v in COMMAND_TAG.findall(text)}
    if "name" in tags:
        return " ".join(t for t in (tags["name"], tags.get("args")) if t)
    parts = PASTED_BLOCK.split(text)
    outside = [PASTED_OPEN.sub("", p).strip() for p in parts[::3]]
    typed = "\n".join(p for p in outside if p)
    text = typed or "\n".join(p for p in (p.strip() for p in parts[2::3]) if p)
    return text or None


def tool_summary(name, args):
    """One printable row for a tool call: "Edit path" for file tools, "Name: main argument" otherwise."""
    if name in FILE_TOOLS or name == "Read":
        arg = args.get("file_path") or args.get("notebook_path")
    else:
        arg = next(
            (args[k] for k in ("command", "description", "pattern", "url", "query", "prompt") if args.get(k)), None
        )
    arg = printable(arg.strip().split("\n")[0][:300]) if isinstance(arg, str) else ""
    sep = " " if name in FILE_TOOLS or name == "Read" else ": "
    return printable(f"{name}{sep}{arg}") if arg else printable(str(name))


def _claude_turn(records, live=False):
    """Walk records (newest first) back to the user's last typed prompt and stop there; records stays positioned just before it.
    -> ({"ask", "files", "cmds", "agents"}, start, tool, said): start = the prompt's epoch seconds, tool = summary of the newest tool call, said = the newest assistant text.
    Without live a prompt counts only once something answered it."""
    steps, cmds, agents, replied = [], 0, 0, False
    ask = start = tool = said = None
    for rec, content in records:
        if rec.get("isSidechain") or rec.get("isMeta"):
            continue
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
        blocks = [b for b in blocks if isinstance(b, dict)]
        if rec.get("type") == "assistant":
            replied = True
            edited = []
            for b in blocks:
                if b.get("type") != "tool_use":
                    continue
                name, args = b.get("name"), b.get("input") or {}
                if name in FILE_TOOLS and (args.get("file_path") or args.get("notebook_path")):
                    edited.append(args.get("file_path") or args.get("notebook_path"))
                elif name == "Bash":
                    cmds += 1
                elif name in ("Agent", "Task"):
                    agents += 1
            steps.append(edited)
            if live:
                calls = [b for b in blocks if b.get("type") == "tool_use"]
                if tool is None and calls:
                    tool = tool_summary(calls[-1].get("name"), calls[-1].get("input") or {})
                if said is None:
                    said = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip() or None
        elif (
            rec.get("type") == "user" and (replied or live) and not any(b.get("type") == "tool_result" for b in blocks)
        ):
            ask = claude_typed(rec, "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text"))
            if ask:
                start = _epoch(rec.get("timestamp"))
                break
    files = list(dict.fromkeys(p for edited in reversed(steps) for p in edited))
    return {"ask": ask, "files": files, "cmds": cmds, "agents": agents}, start, tool, said


def claude_task(path):
    """Turn of the last answer, from the user's last typed prompt on -> {"ask", "files", "cmds", "agents"}: the prompt's text and what its tool calls did (files = distinct file_path of edit tools, in the order first edited)."""
    try:
        with open(path, "rb") as f:
            return _claude_turn(_records_backwards(f))[0]
    except OSError:
        return {"ask": None, "files": [], "cmds": 0, "agents": 0}


LIVE_TAIL = 1024 * 1024  # a working turn can be long: look further back than the 256 KB of a finished one


def claude_live(path):
    """The turn in progress -> {"live": True, "task", "start", "end": None, "tool", "said", "prev"}, or None when the log is unreadable.
    start = when the prompt was typed (epoch seconds), tool = newest tool call as one row, said = newest assistant text, prev = claude_report-shaped answer of the turn before (or None).
    Only the last LIVE_TAIL bytes are read, so a turn longer than that has no ask, start or prev."""
    try:
        with open(path, "rb") as f:
            records = _records_backwards(f, LIVE_TAIL)
            task, start, tool, said = _claude_turn(records, live=True)
            prev = _claude_answer(records) if task["ask"] else None
            if not task["ask"]:
                task = {}
    except OSError:
        return None
    return {"live": True, "task": task, "start": start, "end": None, "tool": tool, "said": said, "prev": prev}


def home_path(path):
    path = path.rstrip("/")
    home = os.path.expanduser("~").rstrip("/")
    if home and (path == home or path.startswith(home + "/")):
        return "~" + path[len(home) :]
    return path


def git_branch(path):
    """Branch name (short sha when detached) of the repo containing path, read from .git/HEAD files only; None outside a repo."""
    d = os.path.abspath(path)
    while True:
        dot = os.path.join(d, ".git")
        if os.path.exists(dot):
            break
        if os.path.dirname(d) == d:
            return None
        d = os.path.dirname(d)
    try:
        if os.path.isfile(dot):
            with open(dot) as f:
                line = f.read().strip()
            if not line.startswith("gitdir:"):
                return None
            dot = os.path.join(d, line[len("gitdir:") :].strip())
        with open(os.path.join(dot, "HEAD")) as f:
            head = f.read().strip()
    except OSError:
        return None
    head = printable(head)
    if head.startswith("ref: "):
        return head[len("ref: refs/heads/") :] or None if head.startswith("ref: refs/heads/") else None
    return head[:7] or None


def finished_subagents(transcript, since=None):
    """Subagents with `finished: true` in their meta -> [{"type", "desc", "text"}] (text is "" when the log has no final answer).
    With since (epoch seconds), only those whose report (or, without one, whose log) ends at or after it."""
    out = []
    for meta in sorted(glob.glob(os.path.join(transcript[: -len(".jsonl")], "subagents", "*.meta.json"))):
        try:
            with open(meta) as f:
                d = json.load(f)
            if not d.get("finished"):
                continue
            log = meta[: -len(".meta.json")] + ".jsonl"
            rep = claude_report(log, sidechain=True)
            if since is not None and ((rep and rep["end"]) or os.path.getmtime(log)) < since:
                continue
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


PROMPT_MARKS = ("> ", "\u276f ")
NOISE_MARKS = "\u26a0\u23bf"
THOUGHT_MARKS = ("\u25b8 ", "\u25c6 ")
BULLET = re.compile(r"(?:[\u2022*-]|\d+\.)\s")
GROK_TIME = re.compile(r"\s{2,}\d{1,2}:\d{2} [AP]M$")


def join_wrapped(prev, nxt):
    if prev.endswith("-"):
        return prev + nxt
    a, b = prev[-1], nxt[0]

    def alnum(c):
        return c.isascii() and c.isalnum()

    def fullwidth_punct(c):
        return unicodedata.category(c).startswith("P") and unicodedata.east_asian_width(c) in "FW"

    if (alnum(a) and not fullwidth_punct(b)) or (alnum(b) and not fullwidth_punct(a)):
        return prev + " " + nxt
    return prev + nxt


def unwrap(para):
    """agy and grok wrap their own lines (indented); bullets start a new line, anything else continues the previous one."""
    indent = min(len(ln) - len(ln.lstrip()) for ln in para)
    out = []
    for ln in (ln[indent:] for ln in para):
        if out and not BULLET.match(ln):
            out[-1] = join_wrapped(out[-1], ln)
        else:
            out.append(ln)
    return "\n".join(out)


def screen_report(pane):
    """Whole last reply of the screen, without the input box and status bar below it (agy, grok write no log).
    The bottom block is cut from the lowest border line (a line starting with a box-drawing corner or rule) up through the lines directly above it that also start with a box-drawing character, or up to the previous plain rule.
    The reply starts after the last prompt line (agy "> ", grok "\u276f "); grok replies are indented as far as the prompt and its notices less."""
    lines = [
        GROK_TIME.sub("", ln.replace("\u2588", "").rstrip())
        for ln in tmux("capture-pane", "-p", "-J", "-S", "-200", "-t", pane).split("\n")
    ]
    border = [i for i, ln in enumerate(lines) if ln.strip() and ln.lstrip()[0] in BORDER_START]
    if border:
        top = border[-1]
        if lines[top].lstrip()[:1] == "\u2500" and len(border) > 1 and "" not in lines[border[-2] : top]:
            top = border[-2]
        while top > 0 and lines[top - 1].strip() and lines[top - 1].lstrip()[0] in BOX_CHARS:
            top -= 1
        lines = lines[:top]
    prompts = [i for i, ln in enumerate(lines) if ln.lstrip().startswith(PROMPT_MARKS)]
    if prompts:
        start = prompts[-1]
        indent = len(lines[start]) - len(lines[start].lstrip())
        while start < len(lines) and lines[start]:
            start += 1
        lines = [ln for ln in lines[start:] if not ln or len(ln) - len(ln.lstrip()) >= indent]
    worked = [i for i, ln in enumerate(lines) if ln.lstrip().startswith("Worked for ")]
    if worked:
        lines = lines[: worked[-1]]
    lines = [ln for ln in lines if not ln.lstrip().startswith(THOUGHT_MARKS)]
    paras, cur = [], []
    for ln in lines + [""]:
        if ln:
            cur.append(ln)
        elif cur:
            if cur[0].lstrip()[0] not in NOISE_MARKS:
                paras.append(unwrap(cur))
            cur = []
    if not prompts:
        paras = paras[-1:]
    return {"text": "\n\n".join(paras), "start": None, "end": None} if paras else None


def report_for(a) -> dict[str, Any] | None:
    """The member's last report (shape of claude_report, Claude Code's with "subagents" added), or None. Claude Code and Codex write one; agy and grok are read off the screen.
    Claude Code and Codex reports also carry "task": {"ask", "files" (list of paths; Codex has none), "cmds", "agents", "dir", "branch", "cwd"} for the left column.
    A Claude Code or Codex member whose status is "working" gets the turn in progress instead (claude_live shape, "live": True, "prev" = the report above or None), when its log shows one."""
    rep, path, cwd = None, None, ""
    working = a.get("status") == "working"
    if a["kind"] == "claude":
        if working and a.get("transcript"):
            rep = claude_live(a["transcript"])
        if not rep:
            rep = claude_report(a["transcript"]) if a.get("transcript") else None
            if rep:
                rep = dict(
                    rep, subagents=finished_subagents(a["transcript"], rep["start"]), task=claude_task(a["transcript"])
                )
        cwd = a.get("cwd", "")
    elif a["kind"] == "codex":
        panes = read_tmux()
        p = next((p for p in panes if p["pane_id"] == a["pane"]), None)
        cwd = p.get("pane_current_path", "") if p else ""
        path = codex_rollout(p.get("pane_pid", ""), cwd, panes) if p else None
        if working and path:
            rep = codex_live(path)
        if not rep:
            rep = codex_report(path) if path else None
            if rep:
                rep["task"] = codex_task(path) or {}
    elif a["kind"] in ("agy", "grok"):
        return screen_report(a["pane"])
    if rep:
        rep["task"] = dict(rep["task"], dir=home_path(cwd) or None, branch=git_branch(cwd) if cwd else None, cwd=cwd)
    return rep


def subagent_unanswered(a):
    """True when a finished subagent's log is newer than the main report's end: the main conversation has not answered it yet."""
    if a["kind"] != "claude" or not a.get("transcript"):
        return False
    rep = claude_report(a["transcript"])
    if not rep or not rep["end"]:
        return False
    for meta in glob.glob(os.path.join(a["transcript"][: -len(".jsonl")], "subagents", "*.meta.json")):
        try:
            with open(meta) as f:
                if not json.load(f).get("finished"):
                    continue
            if os.path.getmtime(meta[: -len(".meta.json")] + ".jsonl") > rep["end"]:
                return True
        except (OSError, ValueError, AttributeError):
            continue
    return False


def wait_channel(pane):
    return "party-" + pane.lstrip("%")


def report_text(pane, wait=False, timeout=600, after=None, read=None):
    """(rc, stdout, stderr) for party.py --report-text. rc: 0 ok, 2 bad or missing pane, 3 timeout, 4 not an agent, 7 waiting for input.
    While the member works, sleep in tmux wait-for (woken by the collector) for up to 2 s, then read the snapshot again.
    With after (epoch seconds, from --ask) it also keeps waiting until the snapshot is newer than after + SNAP_MAX_AGE
    and, for Claude and Codex, the report ends after after. If the member is waiting for input by then and has no such
    report (agy and grok never have one), it returns 7 at once with the last 20 non-empty lines of its screen.
    A dict passed as read gets read["round"] = the round of the member data the returned report came from."""
    if not pane.startswith("%") or not pane[1:].isdigit():
        return 2, "", f"not a pane id: {pane}\n"
    if not math.isfinite(timeout):
        return 2, "", f"bad timeout: {timeout}\n"
    if after is not None and (not wait or not math.isfinite(after)):
        return 2, "", "--after needs --wait and a finite epoch\n"
    rc, _, err = tmux_run(["display-message", "-p", "-t", pane, "#{pane_id}"])
    if rc != 0:
        return 2, "", err or f"no such pane: {pane}\n"
    deadline = time.monotonic() + timeout
    while True:
        snap = get_snapshot()
        a = next((a for t in snap["towns"] for a in t["agents"] if a["pane"] == pane), None)
        if a is None:
            rc, _, err = tmux_run(["display-message", "-p", "-t", pane, "#{pane_id}"])
            if rc != 0:
                return 2, "", err or f"no such pane: {pane}\n"
            return 4, "", f"not a known agent: {pane}\n"
        busy = wait and (a["status"] == "working" or a.get("summons") or subagent_unanswered(a))
        rep = None if busy else report_for(a)
        if rep and rep.get("live"):
            rep = rep["prev"]
        if after is not None and not busy:
            stale = snap["t"] <= after + SNAP_MAX_AGE
            timed = a["kind"] in ("claude", "codex")
            unreported = timed and (not rep or not rep["end"] or rep["end"] <= after)
            if a["status"] == "waiting" and not stale and (unreported or not timed):
                rc, screen, err = tmux_run(["capture-pane", "-p", "-t", pane])
                if rc != 0:
                    return 2, "", err or f"cannot read the screen of {pane}\n"
                tail = [ln for ln in screen.splitlines() if ln.strip()][-20:]
                return 7, "".join(ln + "\n" for ln in tail), f"{pane} is waiting for input\n"
            busy = stale or unreported
        if not busy:
            if rep and read is not None:
                read["round"] = a["round"]
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
    if not any(lead or xv for lead, xv, _ in owners.values()):
        return agents
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


def adopt_crews(towns, owners):
    """Move members whose @party_lead is a live agent of another squad into the lead's squad; drop squads that empties."""
    home = {a["pane"]: t for t in towns.values() for a in t["agents"]}
    emptied = []
    for t in towns.values():
        for a in list(t["agents"]):
            dest = home.get(owners.get(a["pane"], ("", False, ""))[0])
            if dest is not None and dest is not t:
                t["agents"].remove(a)
                dest["agents"].append(a)
                emptied.append(t["name"])
    for name in emptied:
        if name in towns and not towns[name]["agents"]:
            del towns[name]


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
        pane_pids = {p["pane_id"]: p["pane_pid"] for p in panes}
        sessions = {k: v for k, v in read_claude_sessions().items() if v["pid"] in proc_tree(pane_pids.get(k))}
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
                "cwd": p.get("pane_current_path", ""),
                "focus": p["window_active"] == "1" and p["pane_active"] == "1" and t["attached"],
                "round": 0,
            }
        )

    others = [a for t in towns.values() for a in t["agents"] if a["kind"] != "claude" and a["status"] == "idle"]
    if others:
        changed = get_changed([a["pane"] for a in others], now)
        for a in others:
            c = changed.get(a["pane"])
            if isinstance(c, tuple):
                c, menu = c
                if menu and a["kind"] == "agy":
                    a["status"] = "waiting"
                    continue
            if c:
                a["status"] = "working"
    adopt_crews(towns, owners)
    for t in towns.values():
        t["agents"].sort(key=lambda a: STATUS_ORDER.index(a["status"]))
        t["agents"] = group_under_leads(t["agents"], owners)
        cls = spread([a["id"] for a in t["agents"]], len(CLASSES))
        for a in t["agents"]:
            a["cls"] = cls[a["id"]]
    return {"t": time.time(), "towns": list(towns.values()), "panes": meta, "here": here}


SNAP_MAX_AGE = 2.0
SNAP_VERSION = int(max(os.stat(p).st_mtime for p in glob.glob(os.path.join(ROOT, "party_hud", "*.py"))))


def read_seen():
    """{pane: round} of the last report read, from seen.json (written by mark_seen); empty when missing or broken."""
    try:
        with open(os.path.join(PARTY_DIR, "seen.json")) as f:
            seen = json.load(f)
    except (OSError, ValueError):
        return {}
    return seen if isinstance(seen, dict) else {}


def mark_unseen(towns, state, seen=None):
    """Mark members "done" when they stop working while you are not looking, until you look or read the report of that round.
    state = last round's {pane: {"status", "unseen", "round"}} (older files lack round: 0); seen = {pane: round}. Changes towns in place; returns the new state."""
    seen = seen or {}
    out = {}
    for t in towns:
        for a in t["agents"]:
            prev = state.get(a["pane"], {})
            raw = a["status"]
            settled = raw in ("idle", "sleep")
            rnd = prev.get("round", 0) + (settled and prev.get("status") == "working")
            unseen = (
                settled
                and not a["focus"]
                and (prev.get("unseen") or prev.get("status") == "working")
                and seen.get(a["pane"], -1) < rnd
            )
            out[a["pane"]] = {"status": raw, "unseen": unseen, "round": rnd}
            a["round"] = rnd
            if unseen:
                a["status"] = "done"
        order = {a["pane"]: STATUS_ORDER.index(a["status"]) for a in t["agents"]}
        t["agents"].sort(key=lambda a: order[a.get("lead") or a["pane"]])
    for pane, prev in state.items():
        out.setdefault(pane, {"status": "", "unseen": False, "round": prev.get("round", 0)})
    return out


def alerts(a, status):
    return a["status"] == status and (status == "waiting" or not a.get("lead"))


def unread_count(statuses, quiet):
    return sum(s == "waiting" or (s == "done" and p not in quiet) for p, s in statuses.items())


def bell_panes(prev, agents, panes):
    """Members that just started waiting or finished, out of sight -> (panes to ring, new state).
    prev None = first round, no bells. The collector rings for all: hidden windows have no sidebar process."""
    cur = {a["pane"]: a["status"] for a in agents}
    alert = ("waiting", "done")
    quiet = {a["pane"] for a in agents if a["status"] == "done" and a.get("lead")}
    if prev is None:
        return [], cur
    ring = [
        p
        for p, s in cur.items()
        if s in alert and prev.get(p) not in alert and not panes.get(p, {}).get("visible") and p not in quiet
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
        state = mark_unseen(new["towns"], state, read_seen())
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
        members = [a for t in new["towns"] for a in t["agents"]]
        quiet = {a["pane"] for a in members if a.get("lead")}
        ring, cur = bell_panes(prev, members, new["panes"])
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
        unread = unread_count(cur, quiet)
        if unread != (prev or {}).get("reports"):
            tmux("set-option", "-g", "@party_reports", str(unread))
        with open(f"{bell_path}.{os.getpid()}", "w") as f:
            json.dump({**cur, "reports": unread}, f)
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
