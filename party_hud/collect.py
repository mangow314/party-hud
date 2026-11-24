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

from . import claude_log, codex_log, processes
from .common import (
    CLASSES,
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


# codex asks at startup whether to update itself when a newer version is out, and the Enter of --ask picks "Update now"
SUMMON_CMDS = {**AGENT_CMDS, "codex": "codex -c check_for_update_on_startup=false"}


READ_ONLY_CMDS = {
    "claude": "claude --permission-mode plan",
    "codex": SUMMON_CMDS["codex"] + " -s read-only",
    "agy": "agy --mode plan",
    "grok": "grok --permission-mode plan",
}


ACTIVE_WINDOW = 4.0  # screen changed this recently = working (spinners and timers keep changing)


# a line each agent draws near the bottom of its screen while it asks the user to allow something
PERMISSION_MARKS = {"agy": "Requesting permission for:", "codex": "Press enter to confirm or esc to cancel"}


def screen_changed(panes, now):
    """{pane: screen changed recently, or (changed, {agent kinds whose permission prompt is on the screen}) when there
    is one}, for agents without a status file."""
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
        asking = {kind for kind, mark in PERMISSION_MARKS.items() if any(mark in ln for ln in tail)}
        if asking:
            out[pid] = (out[pid], asking)
    try:
        os.makedirs(PARTY_DIR, exist_ok=True)
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(keep, f)
        os.replace(tmp, path)
    except OSError:
        pass
    return out


def agent_kind(cmd, pane_pid, cmdlines=processes.child_cmdlines):
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


def pane_values(pane, *formats):
    """(the pane's values for the tmux formats, "") or, when the pane does not exist, (None, the message for stderr)."""
    rc, out, err = tmux_run(["display-message", "-p", "-t", pane, FIELD_SEP.join(["#{pane_id}", *formats])])
    got = out.rstrip("\n").split(FIELD_SEP)
    # tmux display-message exits 0 when the target pane does not exist, so the pane id it prints is compared instead
    if rc != 0 or got[0] != pane:
        return None, err or f"no such pane: {pane}\n"
    return got[1:], ""


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
    """{"text", "start": None, "end": None} of the last reply on an agy or grok screen (they write no log), without the
    input box and status bar below it, or None."""
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


def report_for(a) -> dict | None:
    """The member's last report (claude_report shape, plus "subagents" for Claude Code), or None; agy and grok are read off
    the screen. Claude Code and Codex reports carry "task" ({"ask", "files", "cmds", "agents", "dir", "branch", "cwd"});
    a working one gets its turn in progress instead (claude_live shape, "prev" = the report)."""
    rep, path, cwd = None, None, ""
    working = a.get("status") == "working"
    if a["kind"] == "claude":
        if working and a.get("transcript"):
            rep = claude_log.claude_live(a["transcript"])
        if not rep:
            rep = claude_log.claude_report(a["transcript"]) if a.get("transcript") else None
            if rep:
                rep = dict(
                    rep,
                    subagents=claude_log.finished_subagents(a["transcript"], rep["start"]),
                    task=claude_log.claude_task(a["transcript"]),
                )
        cwd = a.get("cwd", "")
    elif a["kind"] == "codex":
        panes = read_tmux()
        p = next((p for p in panes if p["pane_id"] == a["pane"]), None)
        cwd = p.get("pane_current_path", "") if p else ""
        path = codex_log.codex_rollout(p.get("pane_pid", ""), cwd, panes) if p else None
        if working and path:
            rep = codex_log.codex_live(path)
        if not rep:
            rep = codex_log.codex_report(path) if path else None
            if rep:
                rep["task"] = codex_log.codex_task(path) or {}
    elif a["kind"] in ("agy", "grok"):
        return screen_report(a["pane"])
    if rep:
        rep["task"] = dict(rep["task"], dir=home_path(cwd) or None, branch=git_branch(cwd) if cwd else None, cwd=cwd)
    return rep


def wait_channel(pane):
    return "party-" + pane.lstrip("%")


def report_text(pane, wait=False, timeout=600, after=None, read=None):
    """(rc, stdout, stderr) for party.py --report-text; rc 0 ok, 2 bad or missing pane, 3 timeout, 4 not an agent, 7
    waiting for input, 8 hit a usage limit (wait and after: docs/crew.md). A dict passed as read gets read["round"] =
    the round of the returned report."""
    if not pane.startswith("%") or not pane[1:].isdigit():
        return 2, "", f"not a pane id: {pane}\n"
    if not math.isfinite(timeout):
        return 2, "", f"bad timeout: {timeout}\n"
    if after is not None and (not wait or not math.isfinite(after)):
        return 2, "", "--after needs --wait and a finite epoch\n"
    found, err = pane_values(pane)
    if found is None:
        return 2, "", err
    deadline = time.monotonic() + timeout
    while True:
        snap = get_snapshot()
        a = next((a for t in snap["towns"] for a in t["agents"] if a["pane"] == pane), None)
        if a is None:
            found, err = pane_values(pane)
            if found is None:
                return 2, "", err
            return 4, "", f"not a known agent: {pane}\n"
        limit = a.get("limit") if wait else None
        if limit and (after is None or (limit["end"] or 0) > after):
            return 8, limit["text"] + "\n", f"{pane} hit a usage limit\n"
        busy = wait and (a["status"] == "working" or a.get("summons") or claude_log.subagent_unanswered(a))
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
        get_codex = lambda pane, pid, cwd: (
            tuple(data["codex"][pane]) if pane in data.get("codex", {}) else None,
            pane in data.get("codex_done", []),
            None,
        )
    else:
        get_cmdlines, get_changed = processes.child_cmdlines, screen_changed

        def get_codex(pane, pid, cwd):
            path = codex_log.codex_rollout(pid, cwd, panes)
            lines = codex_log._tail_lines(path) if path else []
            return codex_log._codex_usage(lines), *codex_log._turn_state(lines)

        panes = read_tmux()
        pane_pids = {p["pane_id"]: p["pane_pid"] for p in panes}
        sessions = {
            k: v
            for k, v in claude_log.read_claude_sessions().items()
            if v["pid"] in processes.proc_tree(pane_pids.get(k))
        }
        get_party, get_cache, get_transcript, get_summons = (
            read_party,
            claude_log.cache_info,
            claude_log.transcript_for,
            claude_log.summons_for,
        )

    towns, meta, here, owners, finished = {}, {}, None, {}, set()
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
        info = get_party(p["pane_id"]) if kind == "claude" else {}
        sid = sess.get("sid") or info.get("session_id") or ""
        if info.get("session_id") and sid and info["session_id"] != sid:
            info = {}
        tx = info.get("transcript") or (get_transcript(sid) if sid else None)
        ci = get_cache(tx) if tx else None
        hp, sp, limit = info.get("ctx_left"), None, None
        hp_max = info.get("ctx_size")
        left = round(hp * hp_max / 100) if hp is not None and hp_max else None
        if ci:
            last, ttl = ci[0], ci[1]
            sp = (max(0.0, ttl - (now - last)), ttl)
            if sp[0] == 0 and status == "idle":
                status = "sleep"
            used = ci[2] if len(ci) > 2 else None
            limit = ci[3] if len(ci) > 3 else None
            if hp is None and used:
                window = 1_000_000 if used > 200_000 else 200_000
                hp = max(0, round(100 - used * 100 / window))
                left, hp_max = max(0, window - used), window
        fresh = kind == "claude" and not ci
        if fresh and hp is None:
            hp = 100
        if kind == "codex":
            usage, done, limit = get_codex(p["pane_id"], p.get("pane_pid", ""), p.get("pane_current_path", ""))
            if done:
                finished.add(p["pane_id"])
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
        if limit:
            t["agents"][-1].update(status="waiting", reason="limited", limit=limit)

    others = [a for t in towns.values() for a in t["agents"] if a["kind"] != "claude" and a["status"] == "idle"]
    if others:
        changed = get_changed([a["pane"] for a in others], now)
        for a in others:
            c = changed.get(a["pane"])
            if isinstance(c, tuple):
                c, asking = c
                if a["kind"] in asking and a["pane"] not in finished:
                    a["status"] = "waiting"
                    continue
            # codex redraws its screen after task_complete; that is not a new turn
            if c and a["pane"] not in finished:
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
    """Mark members "done" when they stop working while you are not looking, until you look or read that round's report.
    state = last round's {pane: {"status", "unseen", "round"}}; seen = {pane: round}. Changes towns in place; returns the
    new state."""
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
    """Members that just started waiting or finished, out of sight -> (panes to ring, new state); prev None = first round,
    no bells."""
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
