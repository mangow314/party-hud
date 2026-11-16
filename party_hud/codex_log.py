"""Find the Codex rollout of a pane and read usage, turns and reports from it."""

import glob
import json
import os
from datetime import datetime, timedelta

from . import processes
from .common import (
    LIVE_TAIL,
    iso_epoch,
    printable,
)

CODEX_SESSIONS = os.path.expanduser("~/.codex/sessions")


def is_codex_proc(args):
    if not args:
        return False
    name = os.path.basename(args[0])
    if name in ("node", "bun", "deno") and len(args) > 1:
        return os.path.basename(args[1]) in ("codex", "codex.js")
    return name == "codex"


def find_codex(pane_pid):
    return next((pid for pid in processes.proc_tree(pane_pid) if is_codex_proc(processes.proc_args(pid))), None)


def codex_rollout(pane_pid, cwd="", panes=()):
    """The pane's codex rollout file, or None. `panes` (tmux panes) lets codex processes in the same cwd each take a
    different rollout."""
    codex_pid = None
    for pid in processes.proc_tree(pane_pid):
        if codex_pid is None and is_codex_proc(processes.proc_args(pid)):
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
    start = processes.proc_start(codex_pid) if codex_pid else None
    if not (start and cwd):
        return None
    peers = [
        processes.proc_start(peer)
        for p in panes
        if p.get("pane_current_path") == cwd and str(p.get("pane_pid")) != str(pane_pid)
        if (peer := find_codex(p.get("pane_pid", "")))
    ]
    peers = [t for t in peers if t is not None]
    return paired_rollout(cwd, start, peers) if peers else newest_rollout(cwd, start)


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
                        began = iso_epoch(payload.get("timestamp"))
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
    """The rollout for the codex process started at `start`, or None: codex processes in one cwd, by start time, take
    rollouts by session_meta.timestamp one to one."""
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
    return _codex_usage(_tail_lines(path))


def _codex_usage(lines):
    for raw in reversed(lines):
        if b'"token_count"' not in raw:
            continue
        try:
            info = json.loads(raw)["payload"]["info"]
            return info["last_token_usage"]["total_tokens"], info["model_context_window"]
        except (ValueError, KeyError, TypeError):
            continue
    return None


def codex_turn_done(path):
    """True when the newest turn event in a rollout's tail is task_complete (no task_started after it)."""
    return _turn_done(_tail_lines(path))


def _turn_done(lines):
    for raw in reversed(lines):
        if b'"task_complete"' not in raw and b'"task_started"' not in raw:
            continue
        try:
            kind = json.loads(raw)["payload"].get("type")
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        if kind in ("task_complete", "task_started"):
            return kind == "task_complete"
    return False


TAIL_MEMO_MAX = 16  # (path, size) entries; when full the entry stored longest ago goes


_tail_memo = {}


def _tail_lines(path, size=256 * 1024):
    try:
        st = os.stat(path)
        sig = (st.st_mtime_ns, st.st_size, st.st_ino)
        memo = _tail_memo.get((path, size))
        if memo and memo[0] == sig:
            return list(memo[1])
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - size))
            lines = f.read().splitlines()
    except OSError:
        _tail_memo.pop((path, size), None)
        return []
    _tail_memo.pop((path, size), None)
    if len(_tail_memo) >= TAIL_MEMO_MAX:
        del _tail_memo[next(iter(_tail_memo))]
    _tail_memo[path, size] = (sig, tuple(lines))
    return lines


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
    """The turn in progress, shaped like claude_live (start = task_started's started_at, said = newest agent message), or
    None when the newest turn event is not a task_started. A turn that began before the last LIVE_TAIL bytes has no ask
    or start."""
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
