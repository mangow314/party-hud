"""Read Claude Code session files, transcripts and subagent logs."""

import glob
import json
import os
import re
from datetime import datetime
from itertools import takewhile

from . import processes
from .common import (
    CLAUDE_PROJECTS,
    CLAUDE_SESSIONS,
    LIVE_TAIL,
    iso_epoch,
    printable,
)

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
        if not pid or "%" not in where or not processes.proc_alive(pid):
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


def _lines_backwards(f, lo, hi, complete=False):
    """(offset, raw line) of a JSONL file in [lo, hi), newest first; a line cut by lo is skipped.
    With complete, hi may fall inside a line: the rest of that line is read too."""
    carry = b""
    if complete:
        f.seek(hi)
        while chunk := f.read(64 * 1024):
            end = chunk.find(b"\n")
            carry += chunk if end < 0 else chunk[:end]
            if end >= 0:
                break
    pos = hi
    while pos > lo:
        start = max(lo, pos - 256 * 1024)
        f.seek(start)
        lines = (f.read(pos - start) + carry).split(b"\n")
        offsets, off = [], start
        for line in lines:
            offsets.append(off)
            off += len(line) + 1
        carry = lines.pop(0) if start else b""
        if start:
            offsets.pop(0)
        pos = start
        yield from reversed(list(zip(offsets, lines)))


def _parsed(lines):
    for _, raw in lines:
        try:
            rec = json.loads(raw)
            yield rec, rec["message"]["content"]
        except (ValueError, KeyError, TypeError):
            continue


def _records_backwards(f, limit=None):
    """Parsed (record, content) of a JSONL transcript from the end, at most limit bytes of it when given; lines that are not records are skipped."""
    end = f.seek(0, os.SEEK_END)
    return _parsed(_lines_backwards(f, max(0, end - limit) if limit else 0, end))


def claude_report(path, sidechain=False):
    """Final answer (text after the last tool call) of the last answered turn -> {"text", "start", "end"} (epoch seconds,
    start may be None), or None. Pass sidechain=True to read a subagent's own log."""
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
                    end = iso_epoch(rec.get("timestamp"))
                collecting = False
            elif collecting:
                said = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
                if said:
                    texts.insert(0, said)
                    end = end or iso_epoch(rec.get("timestamp"))
        elif rec.get("type") == "user":
            if "tool_result" in kinds:
                if not texts and not sidechain:
                    return None
                collecting = False
            elif replied:
                if not texts:
                    return None
                return {"text": "\n\n".join(texts), "start": iso_epoch(rec.get("timestamp")), "end": end}
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
    """The text the user typed in a type-user record, or None when Claude Code injected it or nothing is left after
    removing system reminders. A slash command comes back as "/name args"."""
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
    """(task, start, tool, said) of the turn from the user's last typed prompt on; records stays positioned just before
    it. task = {"ask", "files", "cmds", "agents"}, start = the prompt's epoch seconds, tool = newest tool call summary,
    said = newest assistant text. Without live a prompt counts only once something answered it."""
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
                start = iso_epoch(rec.get("timestamp"))
                break
    files = list(dict.fromkeys(p for edited in reversed(steps) for p in edited))
    return {"ask": ask, "files": files, "cmds": cmds, "agents": agents}, start, tool, said


def claude_task(path):
    """Turn of the last answer -> {"ask", "files", "cmds", "agents"}; files = distinct file_path of edit tools, in the
    order first edited."""
    try:
        with open(path, "rb") as f:
            return _claude_turn(_records_backwards(f))[0]
    except OSError:
        return {"ask": None, "files": [], "cmds": 0, "agents": 0}


LONG_TURN_LOOKBACK = 32 * 1024 * 1024


LONG_TURN_PREV = 2 * 1024 * 1024


LONG_TURN_CACHE = 16


HEAD_BYTES = 512


USER_LINE = re.compile(rb'"type"\s*:\s*"user"')


_long_turns: dict[str, tuple] = {}


def _search_long_turn(f, lo):
    """((start, ask, prev), anchor offset) of the prompt of the turn that began before byte lo, or (None, 0) when it is
    not within LONG_TURN_LOOKBACK."""
    floor = max(0, lo - LONG_TURN_LOOKBACK)
    lines = _lines_backwards(f, floor, lo, complete=True)
    at = [0]

    def prompts():
        for off, raw in lines:
            if USER_LINE.search(raw):
                try:
                    rec = json.loads(raw)
                    content = rec["message"]["content"]
                except (ValueError, KeyError, TypeError):
                    continue
                at[0] = off
                yield rec, content

    task, start, _, _ = _claude_turn(prompts(), live=True)
    if not task["ask"]:
        return None, 0
    stop = at[0] - LONG_TURN_PREV
    prev = _claude_answer(_parsed(takewhile(lambda ol: ol[0] >= stop, lines)))
    return (start, task["ask"], prev), at[0]


def _complete_end(f, end):
    pos = end
    while pos > 0:
        start = max(0, pos - 4096)
        f.seek(start)
        cut = f.read(pos - start).rfind(b"\n")
        if cut >= 0:
            return start + cut + 1
        pos = start
    return 0


def _long_turn(f, path, end, lo):
    """(start, ask, prev) of a turn that began before the LIVE_TAIL window, or None; remembered per log."""
    st = os.fstat(f.fileno())
    hit = _long_turns.pop(path, None)
    if hit:
        dev, ino, seen, anchor, head, found = hit
        f.seek(anchor)
        if (dev, ino) == (st.st_dev, st.st_ino) and lo < seen <= end and f.read(len(head)) == head:
            _long_turns[path] = (dev, ino, _complete_end(f, end), anchor, head, found)
            return found
    found, anchor = _search_long_turn(f, lo)
    f.seek(anchor)
    head = f.read(HEAD_BYTES)
    _long_turns[path] = (st.st_dev, st.st_ino, _complete_end(f, end), anchor, head, found)
    if len(_long_turns) > LONG_TURN_CACHE:
        del _long_turns[next(iter(_long_turns))]
    return found


def claude_live(path):
    """The turn in progress -> {"live": True, "task", "start", "end": None, "tool", "said", "prev"}, or None when the log
    is unreadable. start = the prompt's epoch seconds, tool = newest tool call row, said = newest assistant text, prev =
    the turn before's claude_report or None; task is {} when no prompt is found. Turns older than LIVE_TAIL:
    docs/integrations.md."""
    try:
        with open(path, "rb") as f:
            end = f.seek(0, os.SEEK_END)
            lo = max(0, end - LIVE_TAIL)
            records = _parsed(_lines_backwards(f, lo, end))
            task, start, tool, said = _claude_turn(records, live=True)
            prev = _claude_answer(records) if task["ask"] else None
            if not task["ask"] and lo:
                found = _long_turn(f, path, end, lo)
                if found:
                    start, ask, prev = found
                    task = {**task, "ask": ask}
            if not task["ask"]:
                task = {}
    except OSError:
        return None
    return {"live": True, "task": task, "start": start, "end": None, "tool": tool, "said": said, "prev": prev}


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
