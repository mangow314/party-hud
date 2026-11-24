"""Draw the squad list and member cards from a snapshot (pure functions; ANSI strings)."""

import re

from .art import (
    ART_MIN_WIDTH,
    CREST_CELLS,
    LABEL_COLS,
    PORTRAIT_CELLS,
    SPLIT_GAP,
    SPLIT_MIN_WIDTH,
    SPLIT_PORTRAIT_COLS,
    SPLIT_SIDE_COLS,
    banner_id,
    big_portrait_id,
    crest_ids,
    image_row,
    label_id,
    portrait_id,
)
from .collect import alerts
from .common import BUILDINGS, CLASS_NAMES, RESET, STATUS_TAG, SUMMON_ICON, C, bg, class_icon, clip, cw, fg, printable
from .markdown import ESCAPE, printable_lines, render_markdown, wrap, wrap_sgr

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_tick = 0


def set_tick(tick):
    global _tick
    _tick = tick


def status_icon(status):
    icon = STATUS_TAG[status][0]
    return SPINNER[_tick % len(SPINNER)] if icon is None else icon


def status_label(a):
    _, word, color = STATUS_TAG[a["status"]]
    return f"{status_icon(a['status'])} {'limit' if a.get('reason') == 'limited' else word}", color


def hp_color(pct):
    return "hp" if pct > 50 else "gold" if pct >= 25 else "red"


def sp_color(pct):
    return "sp" if pct >= 15 else "violet"


def ul(name):
    """Underline with a color (SGR 4 + 58). tmux forwards the color only with terminal-features usstyle."""
    r, g, b = C[name]
    return f"\033[4m\033[58;2;{r};{g};{b}m"


def meter_row(label, label_col, cur, cur_col, tail, pct, bar_col, width):
    """One HP/SP row: colored label, right-aligned value and max, underlined pct% as the bar.
    Drops the max when the row is too narrow; pct None draws an empty bar."""
    full = round(max(0.0, min(100.0, pct)) * width / 100) if pct is not None else 0
    if width - len(label) - len(cur) - len(tail) < 1:
        tail = ""
    pad = width - len(label) - len(cur) - len(tail)
    text = (
        [(c, fg(label_col)) for c in label]
        + [(" ", "")] * pad
        + [(c, fg(cur_col, True)) for c in cur]
        + [(c, fg("dim")) for c in tail]
    )
    return "".join(RESET + ul(bar_col if k < full else "line") + style + c for k, (c, style) in enumerate(text)) + RESET


STAT_W = 14
METER_MIN = 8
# md-heart, md-book-open-page-variant, fa-microchip
HP_ICON, SP_ICON, MODEL_ICON = "\U000f02d1", "\U000f05da", ""


def model_badge(a, width):
    """Chip icon, a space, the model's first word. The icon draws wider than one cell, so the space is needed. Only the name if it does not fit."""
    words = a.get("model", "").split()
    if not words:
        return ""
    spaced = f"{MODEL_ICON} {words[0]}"
    return spaced if cw(spaced) <= width else words[0]


def stat_rows(a, width):
    hp, left, top, pts = a["hp"], a.get("hp_left"), a.get("hp_max"), sp_points(a)
    hp_col = hp_color(hp) if hp is not None else "dim"
    if hp is not None and hp <= 10 and _tick % 2:
        hp_col = "dim"
    cur = fmt_tokens(left) if left is not None else f"{hp}%" if hp is not None else "--"
    tail = f"/{fmt_tokens(top)}" if left is not None and top else ""
    num_col = hp_col if hp is not None and hp < 50 else "fg"
    sp_col = sp_color(pts * 100 / SP_MAX) if pts is not None else "dim"
    w = min(width, STAT_W, max(METER_MIN, width - cw(model_badge(a, width)) - 1))
    w = min(width, max(w, len(HP_ICON + "HP") + len(cur) + len(tail) + 1))
    rw = max(0, width - w - 1)

    def right(text, color, delta=None, unit=""):
        text = clip(text, rw)
        tag = f"{delta:+d}{unit}" if delta else ""
        if tag and cw(tag) + cw(text) + (1 if text else 0) > rw:
            text = ""
        if delta and tag and cw(tag) + cw(text) + (1 if text else 0) <= rw:
            pad = " " * (rw - cw(tag) - cw(text))
            return (
                " "
                + fg("green" if delta > 0 else "red")
                + tag
                + RESET
                + pad
                + (fg(color) + text + RESET if text else "")
            )
        return " " * (width - w - cw(text)) + (fg(color) + text + RESET if text else "")

    n = len(a.get("summons", []))
    badge = model_badge(a, rw)
    hp_row = meter_row(HP_ICON + "HP", "hp", cur, num_col, tail, hp, hp_col, w) + right(
        badge if cw(badge) <= rw else "", "model", a.get("hp_delta"), "%"
    )
    if pts is None:
        return [hp_row]
    sp_row = meter_row(SP_ICON + "SP", "sp", str(pts), "fg", f"/{SP_MAX}m", pts * 100 / SP_MAX, sp_col, w)
    return [hp_row, sp_row + right(f"{SUMMON_ICON}{n}" if n else "", "violet", a.get("sp_delta"))]


def fmt_left(sec):
    return f" {int(sec // 60):3d}m" if sec >= 60 else f" {int(sec):3d}s"


def highlight(line, color="sel"):
    return bg(color) + line.replace(RESET, RESET + bg(color)) + RESET


VIEW_BAR = "▌"
PIN_ICON = "\U000f034e"  # md-map-marker


def squad_alert(agents):
    return next((s for s in ("waiting", "done") if any(alerts(a, s) for a in agents)), None)


def squad_marks(t, lit, cursor):
    alert = squad_alert(t["agents"])
    color = STATUS_TAG[alert][2] if alert else "gold"
    if cursor or lit:
        mark = fg("gold", True) + VIEW_BAR
    else:
        mark = fg(color, True) + STATUS_TAG[alert][0] if alert else " "
    name_col = fg(color, True) if alert or cursor or lit else fg("fg") if t["agents"] else fg("dim")
    return mark, name_col


def squad_summary(agents):
    segs = []
    for status in ("waiting", "working", "done", "idle", "sleep"):
        n = sum(a["status"] == status for a in agents)
        if n:
            icon = "zzz " if status == "sleep" else status_icon(status)
            segs.append((fg(STATUS_TAG[status][2]) + icon + str(n), cw(icon) + len(str(n))))
    return " ".join(s for s, _ in segs) + (RESET if segs else ""), sum(w for _, w in segs) + max(0, len(segs) - 1)


def squad_line(i, t, width, lit, cursor=False, home=False, pulse=False):
    dots, right_w = squad_summary(t["agents"])
    if not t["agents"]:
        dots, right_w = fg("dim") + "(empty)", cw("(empty)")
    pin_w = 2 if home else 0
    name = clip(t["name"], width - 5 - right_w - 1 - pin_w)
    pad = width - 4 - cw(name) - right_w - pin_w
    pin = f" {fg('gold')}{PIN_ICON}" if home else ""
    mark, name_col = squad_marks(t, lit, cursor)
    if pulse:
        name_col = fg("fg")
    return (
        f"{mark}{RESET} {fg('gold')}{BUILDINGS[i % len(BUILDINGS)]}{RESET} {name_col}{name}{RESET}{pin}{RESET}"
        f"{' ' * max(1, pad)}{dots}{RESET}"
    )


SP_MAX = 60


def sp_points(a):
    """Cache minutes left (0-60), rounded up; 60 before any request; None if unknown."""
    if a["sp"]:
        return min(SP_MAX, -(-int(a["sp"][0]) // 60))
    return SP_MAX if a.get("fresh") else None


def fmt_tokens(n):
    return f"{n / 1_000_000:.1f}".removesuffix(".0") + "M" if n >= 1_000_000 else f"{round(n / 1000)}k"


def status_rows(a, width, sel=True):
    label, lc = status_label(a)
    job = CLASS_NAMES[a["cls"]]
    name = clip(a["name"], width - 4 - cw(job) - 1 - cw(label) - 1)
    pad = width - 3 - cw(name) - 1 - cw(job) - cw(label) - 1
    return [
        (
            f" {fg('blue')}{class_icon(a)}{RESET} {fg('fg', True) if sel else fg('dim')}{name}{RESET} {fg('dim')}{job}{RESET}"
            f"{' ' * max(1, pad)}{fg(lc)}{label}{RESET} "
        ),
        *(f" {r} " for r in stat_rows(a, width - 2)),
    ]


HINTS = {
    "sidebar": [("⏎", "go"), ("n", "next"), ("?", "keys"), ("q", "hide")],
    "report": [("⏎", "go"), ("n/N", "report"), ("?", "keys"), ("q", "close")],
    "report_back": [("⏎", "go"), ("n/N", "report"), ("h", "back"), ("?", "keys"), ("q", "close")],
    "help": [("?/Esc/q", "back")],
    "select": [("j/k", "move"), ("1-9", "open"), ("⏎", "report"), ("q", "close"), ("[/]", "round")],
    "saved": [("j/k", "scroll"), ("h", "back"), ("?", "keys"), ("q", "close")],
}

HELP = {
    "report": [
        ("n / N", "next / prev report"),
        ("j k ↑ ↓", "scroll"),
        ("wheel", "scroll"),
        ("PgUp PgDn", "page"),
        ("g / G", "top / bottom"),
        ("⏎", "go to agent"),
        ("h", "back (select screen only)"),
        ("q Esc", "close"),
        ("?", "this help"),
    ],
    "sidebar": [
        ("j k", "next / prev card"),
        ("J K", "next / prev squad"),
        ("1-9", "pick card"),
        ("n", "next waiting / done"),
        ("v", "peek output"),
        ("r", "open report"),
        ("⏎", "go to agent"),
        ("q", "hide sidebars"),
        ("Esc P", "back to pane"),
        ("?", "this help"),
    ],
    "select": [
        ("j k ↑ ↓", "move"),
        ("1-9", "open that member's report"),
        ("[ ]", "pick a past round of the lead"),
        ("⏎ l", "open the report or picked round"),
        ("q Esc", "close"),
        ("?", "this help"),
    ],
    "saved": [
        ("j k ↑ ↓", "scroll"),
        ("wheel", "scroll"),
        ("PgUp PgDn", "page"),
        ("g / G", "top / bottom"),
        ("h", "back to select"),
        ("q Esc", "close"),
        ("?", "this help"),
    ],
}


def help_box(mode, width, height):
    """(framed rows, left column, top row, box width) of the centered key help box."""
    width = max(28, width)
    keys = max(cw(k) for k, _ in HELP[mode]) + 1
    title = f"Keys · {mode}"
    boxw = min(width, max(5 + keys + max(cw(t) for _, t in HELP[mode]), cw(title) + 6))
    inner = boxw - 2
    rows = []
    for key, text in HELP[mode]:
        text = clip(text, inner - 3 - keys)
        pad = inner - 3 - keys - cw(text)
        rows.append(f" {fg('gold', True)}{key}{RESET}{' ' * (keys - cw(key))} {fg('dim')}{text}{RESET}{' ' * pad} ")
    framed = box(title, rows, boxw)
    return framed, (width - boxw) // 2, max(0, (height - 1 - len(framed)) // 2), boxw


def help_screen(mode, width, height):
    """Rows of the key help of a mode, exactly height rows of width cells: a framed list, blank rows, the hint on the last row."""
    width = max(28, width)
    framed, left, top, boxw = help_box(mode, width, height)
    out = [" " * width] * top + [" " * left + r + " " * (width - left - boxw) for r in framed]
    out = out[: height - 1]
    hint = hint_line("help", width)
    return out + [" " * width] * (height - 1 - len(out)) + [hint + " " * (width - cw(ESCAPE.sub("", hint)))]


SGR = re.compile(r"\x1b\[[0-9;:]*m")


def dim_row(row):
    """The row in faint text: SGR 2 again after every SGR, so colors (a Kitty placeholder's image id) stay."""
    return "\x1b[2m" + SGR.sub(lambda m: m.group(0) + "\x1b[2m", row) + RESET


def cols_of(row, start, end):
    """Columns [start, end) of a row as exactly end - start cells: SGR state carried in, a wide character cut in half becomes spaces, a combining mark follows its base."""
    carried, out, col, used, kept, i = "", "", 0, 0, False, 0
    while i < len(row):
        m = SGR.match(row, i)
        if m:
            if col < start:
                carried += m.group(0)
            elif col < end:
                out += m.group(0)
            i = m.end()
            continue
        ch = row[i]
        i += 1
        w = cw(ch)
        if w == 0:
            out += ch if kept else ""
            continue
        lo, hi = max(col, start), min(col + w, end)
        if hi > lo:
            full = hi - lo == w
            out += ch if full else " " * (hi - lo)
            used += hi - lo
            kept = full
        else:
            kept = False
        col += w
    return carried + out + " " * (end - start - used)


def help_overlay(rows, mode, width, height):
    """Exactly height rows: the page rows in faint text with the key help box laid over the middle; left and right of the box the page text stays."""
    framed, left, top, boxw = help_box(mode, width, height)
    width = max(28, width)
    out = [dim_row(r) for r in rows[:height]] + [""] * (height - len(rows))
    for k, r in enumerate(framed[: height - top]):
        base = out[top + k]
        out[top + k] = cols_of(base, 0, left) + RESET + r + RESET + cols_of(base, left + boxw, width)
    return out


def hint_line(mode, width):
    out, used = " ", 1
    for key, text in HINTS[mode]:
        w = cw(key) + 1 + cw(text) + 1
        if used + w - 1 > width:
            break
        out += f"{fg('gold', True)}{key}{RESET} {fg('dim')}{text}{RESET} "
        used += w
    return out


def peek_rows(lines, width, height):
    body = [l.rstrip() for l in lines]
    while body and not body[-1]:
        body.pop()
    rows = []
    for l in body[-height:]:
        text = clip(l.expandtabs(4), width)
        rows.append(fg("fg") + text + RESET + " " * (width - cw(text)))
    return rows


REPORT_TITLE = {"done": "Quest complete", "waiting": "Waiting for you"}


def report_state(a, report):
    """The state word the report page titles itself with."""
    return REPORT_TITLE.get(a["status"], "Report") if is_final(report) else "Working" if report else "Last output"


def fmt_took(sec):
    sec = max(0, round(sec))
    if sec >= 3600:
        return f"{sec // 3600}h {sec % 3600 // 60:02d}m"
    return f"{sec // 60}m {sec % 60:02d}s" if sec >= 60 else f"{sec}s"


LIVE_SAID_ROWS = 4


def is_final(report):
    return bool(report) and not report.get("live")


def live_rows(report, width, wide, now, status_row=True, limit=None):
    """Page of a member still working: status row (unless status_row is False) with the time so far, the "Now" block (newest tool call, tail of the newest text), then the previous round's report."""
    gold = fg("gold", True)
    status = "Working" + (f" · {fmt_took(now - report['start'])}" if now is not None and report.get("start") else "")
    rows = [gold + clip(status, width) + RESET, ""] if status_row else []
    rows.append(gold + "Now" + RESET)
    if report.get("tool"):
        rows.append(fg("fg", True) + clip(report["tool"], width) + RESET)
    said = [r for r in wrap_lines(report.get("said") or "", width) if r.strip()]
    rows += [fg("dim") + r + RESET for r in said[-LIVE_SAID_ROWS:]]
    if not report.get("tool") and not said:
        rows.append(fg("dim") + "…" + RESET)
    rows += ["", fg("line") + "─" * width + RESET, gold + "Previous report" + RESET, ""]
    prev = report.get("prev")
    if limit is not None:
        limit -= len(rows)
    rows += render_markdown(prev["text"], width, wide, limit) if prev else [fg("dim") + "no earlier report" + RESET]
    return rows


def running_title(n):
    return f"{n} subagent{'s' * (n != 1)} still running"


def wrap_lines(text, width):
    return [r for line in printable_lines(text) for r in wrap(line, width)]


def report_rows(report, peek, summons, width, wide=None, now=None, status_row=True, limit=None):
    """Report body rows: the Markdown (or the pane's last lines), running branch tasks, finished subagents; code and pane lines may use wide columns (default width). With limit, the Markdown is laid out only until the rows pass limit: the first rows of the full body, more than limit only when it goes on."""
    wide = wide or width
    rows = []
    if report and report.get("live"):
        rows += live_rows(report, width, wide, now, status_row, limit)
    elif report:
        rows += render_markdown(report["text"], width, wide, limit)
    else:
        lines = [l.rstrip() for l in peek]
        while lines and not ESCAPE.sub("", lines[-1]):
            lines.pop()
        rows += [r for l in lines for r in wrap_sgr(l, wide, True)] or [fg("dim") + "no report yet" + RESET]
    for s in summons:
        if limit is not None and len(rows) > limit:
            return rows
        rows += [
            "",
            fg("gold", True)
            + clip(f"{SUMMON_ICON} {s['desc'] or s['type']}", width - 7)
            + RESET
            + " "
            + fg("dim")
            + "running"
            + RESET,
        ]
    for s in (report or {}).get("subagents", []):
        if limit is not None and len(rows) > limit:
            return rows
        rows += ["", fg("gold", True) + clip(f"{SUMMON_ICON} {s['desc'] or s['type']}", width) + RESET]
        rows += (
            render_markdown(s["text"], width, wide, None if limit is None else limit - len(rows)) if s["text"] else []
        )
    return rows


FILE_ROWS = 6


def side_path(path, cwd, width):
    """Path relative to cwd when under it, else absolute; too wide -> cut from the left at a "/" so the file name stays (`…/party_hud/ui.py`)."""
    path = printable(path)
    if cwd and path.startswith(cwd.rstrip("/") + "/"):
        path = path[len(cwd.rstrip("/")) + 1 :]
    if cw(path) <= width:
        return path
    for i, ch in enumerate(path):
        if ch == "/" and cw("…" + path[i:]) <= width:
            return "…" + path[i:]
    tail = path.rsplit("/", 1)[-1]
    while cw("…" + tail) > width:
        tail = tail[1:]
    return "…" + tail


def where_rows(path, width):
    """Path in one row, else split at a "/" into two; still too wide -> drop leading segments and start with "…/"."""
    path = printable(path)
    segs = path.split("/")
    for i in range(len(segs)):
        text = path if i == 0 else "…/" + "/".join(segs[i:])
        if cw(text) <= width:
            return [text]
        for j in range(len(text) - 1, 0, -1):
            if text[j] == "/" and cw(text[:j]) <= width and cw(text[j:]) <= width:
                return [text[:j], text[j:]]
    return [clip("…/" + segs[-1], width)]


SIDE_STATUS = {"done": "Complete", "waiting": "Waiting"}
SIDE_FRAME = {"done": "gold", "waiting": "warn", "working": "sp"}
LABEL_COLOR = {
    "took": "code",
    "running": "code",
    "waited": "amber",
    "asked": "gold",
    "files": "green",
    "work": "green",
    "where": "violet",
}
LABEL_TEXT = {name: name.upper() for name in LABEL_COLS}
WAIT_BAND = "\033[48;2;56;38;22m"
BULLET = "•"


def side_labels(report, now):
    """Names of the heading labels the left column of this report shows, in order."""
    names = []
    if report and report["start"] and report["end"]:
        names.append("took")
    elif report and report.get("live") and report["start"] and now is not None:
        names.append("running")
    if report and report["end"] and now is not None:
        names.append("waited")
    task = (report or {}).get("task") or {}
    if task.get("ask"):
        names.append("asked")
    if task.get("files"):
        names.append("files")
    elif task.get("cmds") or task.get("agents"):
        names.append("work")
    if task.get("dir") or task.get("branch"):
        names.append("where")
    return names


def report_side_rows(
    a,
    squad,
    report,
    pos,
    total,
    portrait,
    rows_total=0,
    now=None,
    labels=False,
    fit=False,
    hints: str = "report",
):
    """Left column of the split report: rows SPLIT_SIDE_COLS wide, framed portrait (cols, rows) on top, key hints on the
    last row, the frame padded to rows_total rows. labels=True draws headings as images; with fit, taller content is cut
    from the bottom to a dim … row above the hint."""
    w = SPLIT_PORTRAIT_COLS
    hot = a["status"] == "waiting"

    def line(text="", width=0):
        return f"  {text}{' ' * (w - width)}  "

    def heading(name, value=""):
        if labels:
            head, hw = image_row(label_id(name), 0, LABEL_COLS[name]), LABEL_COLS[name]
        else:
            head, hw = fg(LABEL_COLOR[name], True) + LABEL_TEXT[name] + RESET, len(LABEL_TEXT[name])
        if not (hot and name == "waited"):
            val = fg("fg", True) + value + RESET if value else ""
            return line(head + " " * (w - hw - cw(value)) + val, w)
        val = fg("warn", True) + value + RESET
        row = head + " " * (w - hw - cw(value)) + val
        return " " + fg("warn", True) + "!" + RESET + WAIT_BAND + row.replace(RESET, RESET + WAIT_BAND) + RESET + "  "

    pc, pr = portrait
    pad = " " * ((w - pc) // 2)
    rows = [line(pad + image_row(big_portrait_id(a), r, pc), (w - pc) // 2 + pc) for r in range(pr)]
    rows.append(line())
    name, kind = clip(a["name"], w), clip(f"{a['kind']} · {squad}", w)
    rows.append(line(fg("gold", True) + name + RESET, cw(name)))
    if a["status"] in SIDE_STATUS:
        tag = f"{STATUS_TAG[a['status']][0]} {SIDE_STATUS[a['status']]}"
        rows.append(line(fg(STATUS_TAG[a["status"]][2]) + tag + RESET, cw(tag)))
    rows.append(line(fg("dim") + kind + RESET, cw(kind)))
    names = side_labels(report, now)
    if "took" in names:
        rows += [line(), heading("took", fmt_took(report["end"] - report["start"]))]
    if "running" in names:
        rows += [line(), heading("running", fmt_took(now - report["start"]))]
    if "waited" in names:
        rows += [line(), heading("waited", fmt_took(now - report["end"]))]
    task = (report or {}).get("task") or {}
    if "asked" in names:
        ask = [r for r in wrap(task["ask"], w) if r.strip()]
        if len(ask) > 3:
            ask = [*ask[:2], clip(ask[2] + "…", w)]
        rows += [line(), heading("asked")]
        rows += [line(fg("fg", True) + r + RESET, cw(r)) for r in ask]
    files = [side_path(f, task.get("cwd"), w - 2) for f in task.get("files") or []]
    if len(files) > FILE_ROWS:
        files = [*files[: FILE_ROWS - 1], f"+{len(files) - FILE_ROWS + 1} more"]
    counts = " · ".join(f"{task[k]} {k}" for k in ("cmds", "agents") if task.get(k))
    if "files" in names or "work" in names:
        rows += [line(), heading("files" if "files" in names else "work")]
        bullet = fg(LABEL_COLOR["files"], True) + BULLET + RESET + " "
        for t in files:
            more = t.startswith("+") and t.endswith(" more")
            rows.append(line(("" if more else bullet) + fg("fg", True) + t + RESET, cw(t) + (0 if more else 2)))
        if counts:
            rows.append(line(fg("fg", True) + counts + RESET, cw(counts)))
    where = [*where_rows(task["dir"], w)] if task.get("dir") else []
    if task.get("branch"):
        where.append(clip(f" {task['branch']}", w))
    if where:
        rows += [line(), heading("where")]
        rows += [line(fg("fg", True) + t + RESET, cw(t)) for t in where]
    if total > 1:
        text = f"report {pos}/{total}"
        rows += [line(), line(fg("dim") + text + RESET, len(text))]
    reserve = 3
    if fit and len(rows) > rows_total - reserve:
        keep = max(0, rows_total - reserve - 1)
        if keep < pr:
            rows = rows[pr:]
        more = "…"
        rows = [*rows[:keep], line(fg("dim") + more + RESET, cw(more))]
    rows += [line()] * (rows_total - reserve - len(rows))
    hint = hint_line(hints, w)
    rows.append(line(hint, cw(ESCAPE.sub("", hint))))
    return box(None, rows, SPLIT_SIDE_COLS, SIDE_FRAME.get(a["status"], "blue"), heavy=True)


def report_split_parts(
    a, squad, report, peek, width, pos, total, banner, portrait, height, now=None, fixed=False, hints="report"
):
    rw = width - SPLIT_SIDE_COLS - SPLIT_GAP
    summons = a.get("summons", [])
    bid = banner_id(a["status"], is_final(report), bool(summons), *banner[2:])
    pad = " " * ((rw - min(banner[0], rw)) // 2)
    right = ["", *(pad + image_row(bid, r, min(banner[0], rw)) for r in range(banner[1]))]
    if is_final(report) and summons:
        title = f"{STATUS_TAG[a['status']][0] or '·'} {running_title(len(summons))}"
        right.append(fg(STATUS_TAG[a["status"]][2], True) + clip(title, min(banner[0], rw)) + RESET)
    bw = min(banner[0], rw)
    right += ["", *report_rows(report, peek, summons, bw, rw, now)]
    rows_total = height if fixed else max(len(right) + 2, height - 1)
    return report_side_rows(a, squad, report, pos, total, portrait, rows_total, now, True, fixed, hints), right


def report_join(left, right):
    """Put the right column beside the left one; no left column (narrow page) means right is the whole page."""
    if not left:
        return list(right)
    blank = " " * SPLIT_SIDE_COLS
    rows = []
    for i in range(max(len(left), len(right))):
        side = left[i] if i < len(left) else blank
        rows.append(side + (" " * SPLIT_GAP + right[i] if i < len(right) else ""))
    return rows


def report_view(left, right, height, offset):
    """The screen rows (at most height) and the clamped offset: the left column stays at its first rows, the right column (the whole page when left is empty) scrolls from offset."""
    offset = max(0, min(offset, len(right) - height))
    rows = report_join(left, right[offset : offset + height])
    return rows[:height], offset


CODE_ROW = fg("green")


def report_frames(right, height, steps=5, tail=0):
    """Opening animation of a fresh page: successive versions of right, the last one right itself ([right] when nothing
    animates). Rows before the first paragraph and the last `tail` rows are in every frame; paragraphs that start in the
    first `height` rows appear in at most `steps` groups."""
    n = len(right) - tail
    cuts = [0]
    for i in range(1, n):
        if right[i] or not right[i - 1]:
            continue
        j = i
        while j < n and not right[j]:
            j += 1
        # a blank row between two code rows is inside the block
        if not (right[i - 1].startswith(CODE_ROW) and j < n and right[j].startswith(CODE_ROW)):
            cuts.append(i)
    cuts = [c for c in cuts if c < height or c == 0]
    body = len(cuts) - 1
    if body < 2:
        return [right]
    ends = cuts[1:] + [n]
    k = min(steps, body)
    frames = []
    for s in range(1, k):
        end = ends[-(-s * body // k)]
        f = right[:end] + [""] * (n - end) + right[n:]
        if not frames or f[:height] != frames[-1][:height]:
            frames.append(f)
    if frames and frames[-1][:height] == right[:height]:
        frames.pop()
    return frames + [right] if frames else [right]


def render_report(*args, **kwargs):
    return "\n".join(report_join(*report_parts(*args, **kwargs)))


def report_parts(
    a,
    squad,
    report,
    peek,
    width,
    pos=1,
    total=1,
    art=False,
    banner=(80, 10),
    portrait=(20, 10),
    height=0,
    now=None,
    fixed=False,
    hints="report",
):
    """(left, right) rows of the report page; left is empty unless the page splits (art and width >= SPLIT_MIN_WIDTH).
    With fixed the left frame is exactly height rows. banner = (cols, rows[, k of the k:1 image]), portrait = (cols, rows)."""
    width = max(28, width)
    if art and width >= SPLIT_MIN_WIDTH:
        return report_split_parts(
            a, squad, report, peek, width, pos, total, banner, portrait, height, now, fixed, hints
        )
    facts = []
    if report and report["start"] and report["end"]:
        facts.append(f"took {fmt_took(report['end'] - report['start'])}")
    if a.get("hp_left") is not None:
        facts.append(f"HP {fmt_tokens(a['hp_left'])}" + (f"/{fmt_tokens(a['hp_max'])}" if a.get("hp_max") else ""))
    elif a.get("hp") is not None:
        facts.append(f"HP {a['hp']}%")
    if total > 1:
        facts.append(f"report {pos}/{total}")
    summons = a.get("summons", [])
    title = report_state(a, report)
    if is_final(report) and summons:
        title = running_title(len(summons))
    pid = portrait_id(a)
    text_w = width - PORTRAIT_CELLS[0] - 1 if art else width
    show_title = not art or bool(is_final(report) and summons)
    head = [
        (f"{STATUS_TAG[a['status']][0] or '·'} {title}" if show_title else "", fg(STATUS_TAG[a["status"]][2], True)),
        (f"{class_icon(a)} {a['name']}  {a['kind']} · {squad}", fg("fg", True)),
        ("  ".join(facts), fg("dim")),
    ]
    rows = []
    if art:
        bid = banner_id(a["status"], is_final(report), bool(summons), *banner[2:])
        rows += [image_row(bid, r, min(banner[0], width)) for r in range(banner[1])]
    for r, (text, style) in enumerate(head):
        line = style + clip(text, text_w) + RESET
        rows.append(f"{image_row(pid, r, PORTRAIT_CELLS[0])} {line}" if art else line)
    rows.append("")
    rows += report_rows(report, peek, summons, width, None, now)
    return [], rows + ["", hint_line(hints, width)]


def saved_round_rows(r, question, reply, width):
    """Page of a saved crew round r (as crew_history gives it): title with the agent and the time asked (UTC), the task, how long it took and its exit code, ASKED with the question, then the reply (None: none saved) laid out as a report, hint."""
    width = max(28, width)
    t = r["asked"]
    when = f"{t[:4]}-{t[4:6]}-{t[6:8]} {t[9:11]}:{t[11:13]} UTC"
    facts = [f"took {fmt_took(r['replied_at'] - r['asked_at'])}"] if r["replied_at"] is not None else ["no reply"]
    if r["rc"] is not None:
        facts.append(f"exit {r['rc']}")
    rows = [
        fg("gold", True) + clip(f"Saved round · {printable(r['agent'])} · asked {when}", width) + RESET,
        fg("fg", True) + clip(printable(r["task"]), width) + RESET,
        fg("dim") + clip("  ".join(facts), width) + RESET,
        "",
        fg(LABEL_COLOR["asked"], True) + LABEL_TEXT["asked"] + RESET,
        *(f"  {fg('fg', True)}{l}{RESET}" for l in wrap_lines(question, width - 2)),
        "",
        fg("line") + "─" * width + RESET,
        "",
    ]
    rows += report_rows({"text": reply}, [], [], width) if reply is not None else [fg("dim") + "no reply saved" + RESET]
    return rows + ["", hint_line("saved", width)]


def render_no_report(width, height):
    width = max(28, width)
    text = clip("No party members.", width - 4)
    out = box("Quest reports", [f" {fg('dim')}{text}{RESET}{' ' * (width - 4 - cw(text))} "], width)
    out += [""] * (height - 1 - len(out))
    out.append(f" {fg('gold', True)}q{RESET} {fg('dim')}close{RESET}")
    return "\n".join(out)


def box(title, rows, width, color="line", double=False, title_color="gold", heavy=False):
    """Rounded frame (heavy: bold square ┏━┓ lines) with the title in the top border (title None: plain border). Every row must be exactly width - 2 wide."""
    tl, h, tr, v, bl, br = "┏━┓┃┗┛" if heavy else "╔═╗║╚╝" if double else "╭─╮│╰╯"
    edge = fg(color, heavy)
    if title is None:
        out = [edge + tl + h * (width - 2) + tr + RESET]
    else:
        t = f" {clip(title, width - 6)} "
        out = [edge + tl + h + fg(title_color, True) + t + RESET + edge + h * (width - 3 - cw(t)) + tr + RESET]
    out += [f"{edge}{v}{RESET}{r}{edge}{v}{RESET}" for r in rows]
    out.append(edge + bl + h * (width - 2) + br + RESET)
    return out


def seg_row(segs, width):
    """Lay out (text, color) segments in exactly `width` cells, dropping segments that do not fit."""
    out, used = " ", 1
    for text, color in segs:
        w = cw(text) + 1
        if used + w > width:
            break
        out += f"{fg(color)}{text}{RESET} "
        used += w
    return out + " " * (width - used)


SELECT_ORDER = ["waiting", "done", "working", "idle", "sleep"]
SELECT_CARD = 33
SELECT_KEYS = 3
SELECT_LIST = SELECT_KEYS + SELECT_CARD
SELECT_CARD_ROWS = 5
SELECT_PREVIEW_MIN = 40
SELECT_ASK_ROWS = 3
CREW_MARK = "└"


def pad_to(row, width):
    return row + " " * (width - cw(ESCAPE.sub("", row)))


def select_roster(towns):
    """[(squad name, member, is_crew)]: leads by SELECT_ORDER, each followed by its waiting crew. A lead with waiting crew ranks as waiting."""
    members = [(t["name"], a) for t in towns for a in t["agents"]]
    leads = {a["pane"] for _, a in members if not a.get("lead")}
    crew = {}
    for squad, a in members:
        if a.get("lead") in leads and a["status"] == "waiting":
            crew.setdefault(a["lead"], []).append((squad, a))
    rank = lambda m: 0 if m[1]["pane"] in crew else SELECT_ORDER.index(m[1]["status"])
    out = []
    for squad, a in sorted((m for m in members if not m[1].get("lead")), key=rank):
        out.append((squad, a, False))
        out += [(s, c, True) for s, c in crew.get(a["pane"], [])]
    return out


def select_crew_line(member, towns, width):
    """The name and status of every crew of this lead, whatever its status; None when it has none."""
    crew = [a for t in towns for a in t["agents"] if a.get("lead") == member["pane"] and a["pane"] != member["pane"]]
    if member.get("lead") or not crew:
        return None
    out, used = f"{fg('dim')}crew{RESET}", 4
    for a in crew:
        w = 2 + cw(a["name"]) + 1 + cw(a["status"])
        if used + w > width:
            break
        out += f"  {fg('fg')}{a['name']}{RESET} {fg(STATUS_TAG[a['status']][2])}{a['status']}{RESET}"
        used += w
    return out + " " * (width - used)


def select_history_row(r, width, lit):
    """One saved round of a lead as "task · agent · took" ("no reply" without one), exactly width cells."""
    end = fmt_took(r["replied_at"] - r["asked_at"]) if r["replied_at"] is not None else "no reply"
    agent = clip(printable(r["agent"]), max(0, width - cw(end) - 6))
    task = clip(printable(r["task"]), max(0, width - cw(agent) - cw(end) - 6))
    dot = fg("dim") + " · " + RESET
    row = f"{fg('fg')}{task}{RESET}{dot}{fg('fg')}{agent}{RESET}{dot}{fg('fg' if r['replied_at'] is not None else 'dim')}{end}{RESET}"
    row = pad_to(row, width)
    return highlight(row) if lit else row


def select_history(history, width, at):
    """Rows of a lead's saved rounds (history as crew_history gives it), the one whose dir is at highlighted, then its worktrees left; [] without rounds."""
    rounds, left = history
    if not rounds and not left:
        return []
    rows = [fg("dim") + "past rounds" + RESET]
    rows += [select_history_row(r, width, r["dir"] == at) for r in rounds]
    rows += [
        pad_to(fg("dim") + "wt left: " + RESET + fg("fg") + clip(printable(t), width - 9) + RESET, width)
        for t, _ in left
    ]
    return rows


def select_summary(roster, towns, width):
    leads = [a for t in towns for a in t["agents"] if not a.get("lead")]
    crew = sum(is_crew for _, _, is_crew in roster)
    need = sum(a["status"] in ("waiting", "done") for a in leads) + crew
    n = len(leads)
    segs = [
        (f"{n} lead{'s' if n != 1 else ''}", "fg"),
        (f"{need} need you", "warn"),
        (f"{crew} crew waiting", "warn"),
    ]
    return seg_row([s for s, k in zip(segs, (n, need, crew)) if k], width)


def select_layout(height, head_rows):
    """(show_hint, show_sum, show_title, body_h) of the select screen: blocks drop in the order title, summary, hint when the height is short; the list keeps at least one row."""
    room = height - 1
    show_hint = room >= 1
    room -= show_hint
    show_sum = room >= 1
    room -= show_sum
    show_title = room >= head_rows
    room -= head_rows if show_title else 0
    return show_hint, show_sum, show_title, room + 1


def select_widths(width):
    """(list width, preview width): the preview is 0 when it would be narrower than SELECT_PREVIEW_MIN; the list then takes the whole width when that is narrower than a card."""
    preview = width - SELECT_LIST - SPLIT_GAP
    if preview >= SELECT_PREVIEW_MIN:
        return SELECT_LIST, preview
    return min(width, SELECT_LIST), 0


def select_view(roster, sel, lw, body_h, art=False):
    """(compact, spans, top, shown, cards) of the list: spans[i] = (start, end) row of roster[i]; rows from top on are on
    screen (whole items, the cursor's included), shown = their indexes; cards[i] = roster[i]'s card rows, None for a
    one-row item (every item when compact)."""
    compact = lw < SELECT_LIST or body_h < SELECT_CARD_ROWS
    spans, cards, n = [], [], 0
    for _, a, is_crew in roster:
        rows = None if compact or is_crew else card(a, SELECT_CARD, a["pane"] == sel, art)
        cards.append(rows)
        n += rows is not None and n > 0
        spans.append((n, n + (len(rows) if rows is not None else 1)))
        n = spans[-1][1]
    at = next((i for i, (_, a, _) in enumerate(roster) if a["pane"] == sel), 0)
    top = min((s for s, _ in spans if s >= spans[at][1] - body_h), default=0)
    cut = max((e for _, e in spans if e <= top + body_h), default=top)
    return compact, spans, top, [i for i, (s, e) in enumerate(spans) if s >= top and e <= cut], cards


def select_cards(roster, view):
    """Members whose card is on screen, for the select_view of the same frame."""
    compact, _, _, shown, _ = view
    return [] if compact else [roster[i][1] for i in shown if not roster[i][2]]


def select_key_cell(n, cursor):
    """The SELECT_KEYS-wide cell with the key of the n-th item (1-9; blank after the ninth)."""
    if n > 9:
        return " " * SELECT_KEYS
    return f" {fg('gold', True) if cursor else fg('dim')}{n}{RESET} "


SELECT_WAIT_TEXT = "waiting for you"
SELECT_WAIT_NAME = 4


def select_row(n, a, is_crew, sel, width):
    """One-row item, exactly width cells: key, status icon, crew connector, name. A crew row is all in the waiting color, bold, with "waiting for you" at the right end when the width allows."""
    key = select_key_cell(n, a["pane"] == sel)
    icon = status_icon(a["status"])
    indent = f"  {CREW_MARK} " if is_crew else ""
    room = width - SELECT_KEYS - 2 - cw(indent)
    if is_crew:
        tail = room - cw(a["name"]) - 1 >= len(SELECT_WAIT_TEXT) + 1
        shrunk = clip(a["name"], room - len(SELECT_WAIT_TEXT) - 2)
        if not tail and cw(shrunk) >= min(SELECT_WAIT_NAME, cw(a["name"])):
            name, tail = shrunk, True
        else:
            name = clip(a["name"], max(0, room))
        body = f"{icon} {indent}{name}"
        gap = width - SELECT_KEYS - cw(body) - len(SELECT_WAIT_TEXT) - 1
        row = key + fg(STATUS_TAG[a["status"]][2], True) + body + (" " * gap + SELECT_WAIT_TEXT if tail else "") + RESET
    else:
        name = clip(a["name"], max(0, room))
        row = f"{key}{fg(STATUS_TAG[a['status']][2])}{icon}{RESET} {fg('dim')}{indent}{RESET}{fg('fg')}{name}{RESET}"
    row = pad_to(row, width)
    return highlight(row) if a["pane"] == sel else row


def select_card(n, rows, cursor):
    """A member's side-bar card rows with its key in the column on the left of the first row."""
    return [(select_key_cell(n, cursor) if r == 0 else " " * SELECT_KEYS) + l for r, l in enumerate(rows)]


def select_preview(roster, towns, at, width, height, report, now, peek=(), history=None, hist_at=None):
    """Exactly height rows of width cells for roster[at]: time and directory, its lead's crew, a lead's past rounds
    (scrolled so that hist_at shows), the question, then the report as the report page draws it (peek without a report),
    cut to a dim "… more" row."""
    _, a, _ = roster[at]
    task = (report or {}).get("task") or {}
    rows = []
    stamp = None
    if a["status"] == "waiting" and report and report.get("end") and now is not None:
        stamp = ("waited", fmt_took(now - report["end"]))
    elif a["status"] == "working" and report and report.get("live") and report.get("start") and now is not None:
        stamp = ("running", fmt_took(now - report["start"]))
    elif report and report.get("start") and report.get("end"):
        stamp = ("took", fmt_took(report["end"] - report["start"]))
    where = clip(printable(task["dir"]), width) if task.get("dir") else ""
    if stamp:
        label, value = stamp
        row = fg(LABEL_COLOR[label], True) + LABEL_TEXT[label] + RESET + " " + fg("fg", True) + value + RESET
        left = cw(LABEL_TEXT[label]) + 1 + cw(value)
        if where and left + 3 < width:
            row += fg("dim") + " · " + RESET + fg("fg") + clip(where, width - left - 3) + RESET
        rows.append(row)
    elif where:
        rows.append(fg("fg") + where + RESET)
    lead = a if not a.get("lead") else next((m for _, m, _ in roster if m["pane"] == a["lead"]), None)
    crew = select_crew_line(lead, towns, width) if lead else None
    if crew:
        rows.append(crew)
    if history and not a.get("lead"):
        dirs = [r["dir"] for r in history[0]]
        lit = len(rows) + 1 + dirs.index(hist_at) if hist_at in dirs else -1
        rows += select_history(history, width, hist_at)
        if lit >= height:
            rows = rows[lit - height + 1 :]
    ask = [r for r in wrap(task["ask"], width - 2) if r.strip()] if task.get("ask") else []
    if ask:
        if len(ask) > SELECT_ASK_ROWS:
            ask = [*ask[: SELECT_ASK_ROWS - 1], clip(ask[SELECT_ASK_ROWS - 1] + "…", width - 2)]
        rows += ["", fg(LABEL_COLOR["asked"], True) + LABEL_TEXT["asked"] + RESET]
        rows += [f"  {fg('fg', True)}{r}{RESET}" for r in ask]
    state = clip(report_state(a, report), width)
    tail = clip("  preview" + " · unread" * (a["status"] == "done"), width - cw(state))
    rows += [
        "",
        fg("gold", True) + state + RESET + fg("dim") + tail + RESET,
        fg("line") + "─" * width + RESET,
    ]
    room = height - len(rows)
    body = report_rows(report, peek, a.get("summons", []), width, width, now, False, max(room, 0))
    if len(body) > room > 0:
        body = [*body[: room - 1], fg("dim") + "… more · ⏎ to read" + RESET]
    return [pad_to(r, width) for r in (rows + body)[:height]] + [" " * width] * (height - len(rows) - len(body))


def render_select(
    roster,
    towns,
    sel,
    width,
    height,
    report=None,
    now=None,
    title=None,
    art=False,
    peek=(),
    view=None,
    history=None,
    hist_at=None,
):
    """Exactly height rows of width cells: title, summary, the member cards with the preview of the cursor's member beside
    them when the width allows, hint; blocks that do not fit are left out. view: this frame's select_view when already
    built. history, hist_at: see select_preview."""
    if height <= 0:
        return []
    head = (
        title
        if title is not None
        else [fg("gold", True) + " " * ((width - 12) // 2) + clip("PARTY SELECT", width) + RESET]
    )
    show_hint, show_sum, show_title, body_h = select_layout(height, len(head))
    lw, rw = select_widths(width)
    _, spans, top, shown, cards = view or select_view(roster, sel, lw, body_h, art)
    whole = [" " * lw] * (spans[-1][1] if spans else 0)
    for i in shown:
        _, a, is_crew = roster[i]
        s, e = spans[i]
        whole[s:e] = (
            [select_row(i + 1, a, is_crew, sel, lw)]
            if cards[i] is None
            else select_card(i + 1, cards[i], a["pane"] == sel)
        )
    left = whole[top : top + body_h]
    left += [" " * lw] * (body_h - len(left))
    if not roster:
        empty = clip("no party members", lw)
        left[body_h // 2] = pad_to(" " * ((lw - cw(empty)) // 2) + fg("dim") + empty + RESET, lw)
    if rw and roster:
        at = next((i for i, (_, a, _) in enumerate(roster) if a["pane"] == sel), 0)
        right = select_preview(roster, towns, at, rw, body_h, report, now, peek, history, hist_at)
        left = [left[j] + " " * SPLIT_GAP + right[j] for j in range(body_h)]
    out = [pad_to(t, width) for t in head] if show_title else []
    if show_sum:
        out.append(select_summary(roster, towns, width))
    out += [pad_to(l, width) for l in left]
    if show_hint:
        out.append(pad_to(hint_line("select", width - 1), width))
    return out


def squad_rows_art(t, pid, width, lit, cursor=False, home=False, pulse=False):
    tw = width - 2 - CREST_CELLS[0]
    agents = t["agents"]
    dots, dots_w = squad_summary(agents)
    name = clip(t["name"], tw - dots_w - 1)
    mark, name_col = squad_marks(t, lit, cursor)
    if pulse:
        name_col = fg("fg")
    alert = squad_alert(agents)
    asleep = sum(a["status"] == "sleep" for a in agents)
    counts = f" · {sum(alerts(a, alert) for a in agents)} {alert}" if alert else f" · {asleep} asleep" if asleep else ""
    sub_col = STATUS_TAG[alert][2] if alert else STATUS_TAG["sleep"][2] if asleep else "dim"
    members = f"{len(agents)} member{'s' if len(agents) != 1 else ''}"
    pin = 2 if home else 0
    sub = clip(members + counts if agents else "(empty)", tw - pin)
    bar = fg("gold", True) + VIEW_BAR if lit or cursor else " "
    return [
        (
            f"{mark}{RESET}{image_row(pid, 0, CREST_CELLS[0])} {name_col}{name}{RESET}"
            f"{' ' * (tw - cw(name) - dots_w)}{dots}{RESET}"
        ),
        (
            f"{bar}{RESET}{image_row(pid, 1, CREST_CELLS[0])} {fg(sub_col)}{sub}{RESET}"
            f"{' ' * (tw - cw(sub) - pin)}{(' ' + fg('gold') + PIN_ICON + RESET) if pin else ''}"
        ),
    ]


def art_rows(a, width, sel):
    pid = portrait_id(a)
    tw = width - PORTRAIT_CELLS[0] - 3
    label, lc = status_label(a)
    name = clip(a["name"], tw - 2 - cw(label) - 1)
    text = [
        (
            f"{fg('blue')}{class_icon(a)}{RESET} {fg('gold', True) if sel else fg('dim')}{name}{RESET}"
            f"{' ' * (tw - 2 - cw(name) - cw(label))}{fg(lc)}{label}{RESET}"
        ),
        *stat_rows(a, tw),
    ]
    text += [" " * tw] * (PORTRAIT_CELLS[1] - len(text))
    return [f" {image_row(pid, r, PORTRAIT_CELLS[0])} {t} " for r, t in enumerate(text)]


def card(a, width, sel, art=False, lit=False):
    """One member card. Selected: gold double frame and ❯ (☞ has ambiguous width and breaks some terminals). lit: frame in the flash color."""
    pad = "  " if a.get("lead") else ""
    width -= len(pad)
    if art:
        rows = art_rows(a, width - 2, sel)
    else:
        rows = status_rows(a, width - 2, sel)
    if sel:
        rows[0] = fg("gold", True) + "❯" + RESET + rows[0][1:]
        lines = box(a.get("kind", "claude"), rows, width, "fg" if lit else "gold", double=True)
    else:
        lines = box(
            a.get("kind", "claude"),
            rows,
            width,
            "fg" if lit else "warn" if a["status"] == "waiting" else "line",
            title_color="dim",
        )
    return [pad + l for l in lines]


def render(
    towns,
    width,
    selected=None,
    peek=None,
    hints=None,
    height=40,
    row_map=None,
    focus="party",
    squad=None,
    tick=0,
    art=False,
    here=None,
    flash=(),
):
    """Squad list on top, then one card per member of the viewed squad.
    selected: pane id (None = your current Claude pane). peek: output lines that replace the cards.
    flash: pane ids whose card frame is in the flash color this frame; their squad's name row is too.
    row_map: if a list is given, filled with screen row -> ("squad", i) / ("agent", pane) / None, for the mouse."""
    global _tick
    _tick = tick
    width = max(28, width)
    art = art and width >= ART_MIN_WIDTH
    inner = width - 2
    agents = [a for t in towns for a in t["agents"]]
    if selected is None:
        selected = next((a["pane"] for a in agents if a["focus"]), None)
    sel = next((a for a in agents if a["pane"] == selected), None)
    on_squad = focus == "squad" and squad is not None and 0 <= squad < len(towns)
    home = next((i for i, t in enumerate(towns) if sel in t["agents"]), None)
    view = squad if on_squad else home if home is not None else 0 if towns else None
    vt = towns[view] if view is not None else None
    w = inner - 1
    units, center = [], 0
    crests = crest_ids(t["name"] for t in towns)
    if here is None:
        here = next((t["name"] for t in towns if any(a["focus"] for a in t["agents"])), None)
    fold = [not t["agents"] and i != view and not (on_squad and squad == i) for i, t in enumerate(towns)]
    for i, t in enumerate(towns):
        cur = on_squad and squad == i
        if fold[i]:
            if i and fold[i - 1]:
                continue
            n = 1
            while i + n < len(towns) and fold[i + n]:
                n += 1
            if n > 1:
                indent = 2 + CREST_CELLS[0] if art else 4
                text = f"+{n} empty"
                line = " " * indent + fg("dim") + text + RESET + " " * (w - indent - len(text))
                units.append(([line + " "], [("squad", i)], n))
                continue
        mine = t["name"] == here
        pulse = bool(flash) and any(a["pane"] in flash for a in t["agents"])
        lines = (
            squad_rows_art(t, crests[t["name"]], w, i == view, cur, mine, pulse)
            if art
            else [squad_line(i, t, w, i == view, cur, mine, pulse)]
        )
        if i == view:
            center = len(units)
        units.append(
            ([highlight(l + " ", "view") if i == view else l + " " for l in lines], [("squad", i)] * len(lines), 1)
        )

    members = vt["agents"] if vt else []
    peeking = peek is not None and sel is not None and not on_squad
    cards = [card(a, width, a is sel and not on_squad, art, a["pane"] in flash) for a in members] if not peeking else []
    i = next((k for k, a in enumerate(members) if a is sel), 0)
    hint_h = 1 if hints else 0
    below = len(cards[i]) if cards else 3
    more = lambda arrow, n: f"{fg('dim')}{f'{arrow} {n} more'.center(width)}{RESET}"

    def fit_squads(room):
        """Squad units that fit in `room` rows, growing both ways from the viewed one -> [lo, hi)."""
        lo, hi, used = center, center + 1, len(units[center][0])
        while True:
            grew = False
            for k in (hi, lo - 1):
                if 0 <= k < len(units) and not lo <= k < hi and used + len(units[k][0]) <= room:
                    used += len(units[k][0])
                    lo, hi, grew = min(lo, k), max(hi, k + 1), True
            if not grew:
                return lo, hi

    squad_rows, targets = [], [None]
    if units:
        room = height - hint_h - below - 2
        lo, hi = fit_squads(room)
        if lo > 0 or hi < len(units):
            lo, hi = fit_squads(room - 2)
        if lo > 0:
            squad_rows.append(more("▲", sum(u[2] for u in units[:lo])))
            targets.append(None)
        for rows, tgt, _ in units[lo:hi]:
            squad_rows += rows
            targets += tgt
        if hi < len(units):
            squad_rows.append(more("▼", sum(u[2] for u in units[hi:])))
            targets.append(None)
    out = box(f"Squads {len(towns)}", squad_rows, width)
    targets.append(None)

    avail = height - len(out) - hint_h
    low, low_targets = [], []
    if peeking and sel is not None:
        low = box(
            f"Peek · {sel['name']}", peek_rows(peek, inner, max(1, avail - 2)), width, STATUS_TAG[sel["status"]][2]
        )
        low_targets = [None] * len(low)
    elif cards:

        def fit(room):
            """Cards that fit in `room` rows, growing both ways from the selected one -> [lo, hi)."""
            lo, hi, used = i, i + 1, len(cards[i])
            while True:
                grew = False
                for k in (hi, lo - 1):
                    if 0 <= k < len(cards) and not lo <= k < hi and used + len(cards[k]) <= room:
                        used += len(cards[k])
                        lo, hi, grew = min(lo, k), max(hi, k + 1), True
                if not grew:
                    return lo, hi

        lo, hi = fit(avail)
        if lo > 0 or hi < len(cards):
            lo, hi = fit(avail - 2)
        if lo > 0:
            low.append(more("▲", lo))
            low_targets.append(None)
        for a, c in zip(members[lo:hi], cards[lo:hi]):
            low += c
            low_targets += [("agent", a["pane"])] * len(c)
        if hi < len(cards):
            low.append(more("▼", len(cards) - hi))
            low_targets.append(None)
    elif vt:
        low = box(vt["name"], [seg_row([("no agents", "dim"), ("⏎", "gold"), ("open session", "dim")], inner)], width)
        low_targets = [("squad", view)] * len(low)
    out = (out + low)[: height - hint_h]
    if row_map is not None:
        row_map[:] = (targets + low_targets)[: len(out)]
    if hints:
        out += [""] * (height - 1 - len(out))
        out.append(hint_line(hints, width))
    return "\n".join(out)
