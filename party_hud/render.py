"""Draw the squad list and member cards from a snapshot (pure functions; ANSI strings)."""

import re

from .art import ART_MIN_WIDTH, CREST_CELLS, PORTRAIT_CELLS, banner_id, crest_ids, image_row, portrait_id
from .common import BUILDINGS, CLASS_NAMES, RESET, STATUS_TAG, SUMMON_ICON, C, bg, class_icon, clip, cw, fg, printable

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_tick = 0


def status_icon(status):
    icon = STATUS_TAG[status][0]
    return SPINNER[_tick % len(SPINNER)] if icon is None else icon


def status_label(status):
    _, word, color = STATUS_TAG[status]
    return f"{status_icon(status)} {word}", color


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
    rw = max(0, width - w - 1)

    def right(text, color):
        text = clip(text, rw)
        return " " * (width - w - cw(text)) + (fg(color) + text + RESET if text else "")

    n = len(a.get("summons", []))
    return (
        meter_row(HP_ICON + "HP", "hp", cur, num_col, tail, hp, hp_col, w) + right(model_badge(a, rw), "model"),
        meter_row(
            SP_ICON + "SP",
            "sp",
            str(pts) if pts is not None else "--",
            "fg",
            f"/{SP_MAX}m" if pts is not None else "",
            pts * 100 / SP_MAX if pts is not None else None,
            sp_col,
            w,
        )
        + right(f"{SUMMON_ICON}{n}" if n else "", "violet"),
    )


def fmt_left(sec):
    return f" {int(sec // 60):3d}m" if sec >= 60 else f" {int(sec):3d}s"


def highlight(line, color="sel"):
    return bg(color) + line.replace(RESET, RESET + bg(color)) + RESET


VIEW_BAR = "▌"
PIN_ICON = "\U000f034e"  # md-map-marker


def squad_alert(agents):
    return next((s for s in ("waiting", "done") if any(a["status"] == s for a in agents)), None)


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


def squad_line(i, t, width, lit, cursor=False, home=False):
    dots, right_w = squad_summary(t["agents"])
    if not t["agents"]:
        dots, right_w = fg("dim") + "(empty)", cw("(empty)")
    pin_w = 2 if home else 0
    name = clip(t["name"], width - 5 - right_w - 1 - pin_w)
    pad = width - 4 - cw(name) - right_w - pin_w
    pin = f" {fg('gold')}{PIN_ICON}" if home else ""
    mark, name_col = squad_marks(t, lit, cursor)
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
    label, lc = status_label(a["status"])
    job = CLASS_NAMES[a["cls"]]
    name = clip(a["name"], width - 4 - cw(job) - 1 - cw(label) - 1)
    pad = width - 3 - cw(name) - 1 - cw(job) - cw(label) - 1
    hp_row, sp_row = stat_rows(a, width - 2)
    return [
        (
            f" {fg('blue')}{class_icon(a)}{RESET} {fg('fg', True) if sel else fg('dim')}{name}{RESET} {fg('dim')}{job}{RESET}"
            f"{' ' * max(1, pad)}{fg(lc)}{label}{RESET} "
        ),
        f" {hp_row} ",
        f" {sp_row} ",
    ]


HINTS = {
    "popup": [("jk/JK", "nav"), ("⏎", "go"), ("n", "next"), ("q", "quit")],
    "sidebar": [("jk/JK", "nav"), ("⏎", "go"), ("n", "next"), ("q", "hide")],
    "report": [("⏎", "go"), ("n", "next"), ("q", "close")],
}


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


def fmt_took(sec):
    sec = max(0, round(sec))
    if sec >= 3600:
        return f"{sec // 3600}h {sec % 3600 // 60:02d}m"
    return f"{sec // 60}m {sec % 60:02d}s" if sec >= 60 else f"{sec}s"


def wrap(text, width):
    """Text -> rows of at most width columns, breaking anywhere (CJK has no spaces to break at)."""
    rows = []
    for line in text.expandtabs(4).split("\n"):
        row, used = "", 0
        for ch in printable(line):
            if used + cw(ch) > width:
                rows.append(row)
                row, used = "", 0
            row += ch
            used += cw(ch)
        rows.append(row)
    return rows


MD_INLINE = re.compile(
    r"`([^`]+)`|\*\*(.+?)\*\*|(?<!!)\[([^\]]+)\]\(([^)\s]+)\)|\*(?!\s)(.+?)(?<!\s)\*|(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)"
)
MD_HEADING = re.compile(r"#{1,6}\s+(.*)")
MD_RULE = re.compile(r"(-{3,}|\*{3,}|_{3,})\s*")
MD_ITEM = re.compile(r"(?:[-*]|\d+\.)\s+")
MD_RAW = re.compile(r"\s+(?:[-*]|\d+\.)\s|\s*(?:\||>|<)")


def md_inline(text, style=""):
    """Inline Markdown -> [(char, sgr)] cells."""
    cells, pos = [], 0
    for m in MD_INLINE.finditer(text):
        cells += [(ch, style) for ch in text[pos : m.start()]]
        code, bold, label, url, em, em2 = m.groups()
        if code is not None:
            cells += [(ch, style + fg("amber")) for ch in code]
        elif bold is not None:
            cells += md_inline(bold, style + "\033[1m")
        elif label is not None:
            cells += md_inline(label, style + fg("blue") + "\033[4m")
            cells += [(ch, style + fg("dim")) for ch in f" ({url})"]
        else:
            cells += md_inline(em or em2, style + "\033[3m")
        pos = m.end()
    return cells + [(ch, style) for ch in text[pos:]]


def md_rows(cells, width, indent=0):
    """Cells -> rows of at most width columns, continuation rows indented; each styled run ends with RESET."""
    lines, row, used, room = [], [], 0, width
    for cell in cells:
        w = cw(cell[0])
        if w > width - indent:
            continue
        if used + w > room:
            lines.append(row)
            row, used, room = [], 0, width - indent
        row.append(cell)
        used += w
    lines.append(row)
    rows = []
    for n, row in enumerate(lines):
        out, prev = " " * indent if n else "", ""
        for ch, st in row:
            if st != prev:
                out += (RESET if prev else "") + st
                prev = st
            out += ch
        rows.append(out + (RESET if prev else ""))
    return rows


def render_markdown(text, width):
    """Markdown subset -> rows of at most width columns with SGR styles. Nested lists, tables, images, HTML and quotes stay raw."""
    rows, code = [], False
    for line in printable_lines(text):
        if line.startswith("```"):
            code = not code
        elif code:
            rows += md_rows([(ch, fg("green")) for ch in line], width)
        elif m := MD_HEADING.fullmatch(line):
            rows += md_rows(md_inline(m[1], fg("gold", True)), width)
        elif MD_RULE.fullmatch(line):
            rows.append(fg("dim") + "─" * width + RESET)
        elif MD_RAW.match(line) or line.lstrip().startswith("!["):
            rows += md_rows([(ch, "") for ch in line], width)
        elif m := MD_ITEM.match(line):
            mark = "•" if m[0][0] in "-*" else m[0].split()[0]
            body = md_inline(line[m.end() :])
            rows += md_rows([(ch, "") for ch in mark + " "] + body, width, cw(mark) + 1)
        else:
            rows += md_rows(md_inline(line), width)
    return rows


def printable_lines(text):
    return [printable(line) for line in text.replace("\r", "").expandtabs(4).split("\n")]


def render_report(a, squad, report, peek, width, pos=1, total=1, art=False, banner=(80, 10)):
    """Report pane text: who, how long, HP, then the whole report as Markdown, or the pane's last lines (peek) when there is no report.
    With art a banner (banner = cols, rows) opens the page in place of the title row, and the portrait stands left of the first three rows."""
    width = max(28, width)
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
    title = REPORT_TITLE.get(a["status"], "Report") if report else "Last output"
    if report and summons:
        title = f"還有 {len(summons)} 個分支任務進行中"
    pid = portrait_id(a)
    text_w = width - PORTRAIT_CELLS[0] - 1 if art else width
    show_title = not art or bool(report and summons)
    head = [
        (f"{STATUS_TAG[a['status']][0] or '·'} {title}" if show_title else "", fg(STATUS_TAG[a["status"]][2], True)),
        (f"{class_icon(a)} {a['name']}  {a['kind']} · {squad}", fg("fg", True)),
        ("  ".join(facts), fg("dim")),
    ]
    rows = []
    if art:
        bid = banner_id(a["status"], bool(report), bool(summons))
        rows += [image_row(bid, r, min(banner[0], width)) for r in range(banner[1])]
    for r, (text, style) in enumerate(head):
        line = style + clip(text, text_w) + RESET
        rows.append(f"{image_row(pid, r, PORTRAIT_CELLS[0])} {line}" if art else line)
    rows.append("")
    if report:
        rows += render_markdown(report["text"], width)
    else:
        lines = [l.rstrip() for l in peek]
        while lines and not lines[-1]:
            lines.pop()
        rows += [fg("dim") + r + RESET for l in lines for r in wrap(l, width)] or [fg("dim") + "no report yet" + RESET]
    for s in summons:
        rows += [
            "",
            fg("gold", True)
            + clip(f"{SUMMON_ICON} {s['desc'] or s['type']}", width - 7)
            + RESET
            + " "
            + fg("dim")
            + "進行中"
            + RESET,
        ]
    for s in (report or {}).get("subagents", []):
        rows += ["", fg("gold", True) + clip(f"{SUMMON_ICON} {s['desc'] or s['type']}", width) + RESET]
        rows += render_markdown(s["text"], width) if s["text"] else []
    return "\n".join(rows + ["", hint_line("report", width)])


def render_no_report(width, height):
    width = max(28, width)
    text = clip("Nobody is waiting or done.", width - 4)
    out = box("Quest reports", [f" {fg('dim')}{text}{RESET}{' ' * (width - 4 - cw(text))} "], width)
    out += [""] * (height - 1 - len(out))
    out.append(f" {fg('gold', True)}q{RESET} {fg('dim')}close{RESET}")
    return "\n".join(out)


def box(title, rows, width, color="line", double=False, title_color="gold"):
    """Rounded frame with the title in the top border. Every row must be exactly width - 2 wide."""
    tl, h, tr, v, bl, br = "╔═╗║╚╝" if double else "╭─╮│╰╯"
    t = f" {clip(title, width - 6)} "
    out = [fg(color) + tl + h + fg(title_color, True) + t + RESET + fg(color) + h * (width - 3 - cw(t)) + tr + RESET]
    out += [f"{fg(color)}{v}{RESET}{r}{fg(color)}{v}{RESET}" for r in rows]
    out.append(fg(color) + bl + h * (width - 2) + br + RESET)
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


def squad_rows_art(t, pid, width, lit, cursor=False, home=False):
    tw = width - 2 - CREST_CELLS[0]
    agents = t["agents"]
    dots, dots_w = squad_summary(agents)
    name = clip(t["name"], tw - dots_w - 1)
    mark, name_col = squad_marks(t, lit, cursor)
    alert = squad_alert(agents)
    asleep = sum(a["status"] == "sleep" for a in agents)
    counts = (
        f" · {sum(a['status'] == alert for a in agents)} {alert}" if alert else f" · {asleep} asleep" if asleep else ""
    )
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
    label, lc = status_label(a["status"])
    name = clip(a["name"], tw - 2 - cw(label) - 1)
    text = [
        (
            f"{fg('blue')}{class_icon(a)}{RESET} {fg('gold', True) if sel else fg('dim')}{name}{RESET}"
            f"{' ' * (tw - 2 - cw(name) - cw(label))}{fg(lc)}{label}{RESET}"
        ),
        *stat_rows(a, tw),
    ]
    return [f" {image_row(pid, r, PORTRAIT_CELLS[0])} {t} " for r, t in enumerate(text)]


def card(a, width, sel, art=False):
    """One member card. Selected: gold double frame and ❯ (☞ has ambiguous width and breaks some terminals)."""
    pad = "  " if a.get("lead") else ""
    width -= len(pad)
    if art:
        rows = art_rows(a, width - 2, sel)
    else:
        rows = status_rows(a, width - 2, sel)
    if sel:
        rows[0] = fg("gold", True) + "❯" + RESET + rows[0][1:]
        lines = box(a.get("kind", "claude"), rows, width, "gold", double=True)
    else:
        lines = box(
            a.get("kind", "claude"), rows, width, "warn" if a["status"] == "waiting" else "line", title_color="dim"
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
):
    """Squad list on top, then one card per member of the viewed squad.
    selected: pane id (None = your current Claude pane). peek: output lines that replace the cards.
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
    squad_rows, targets = [], [None]
    crests = crest_ids(t["name"] for t in towns)
    if here is None:
        here = next((t["name"] for t in towns if any(a["focus"] for a in t["agents"])), None)
    for i, t in enumerate(towns):
        cur = on_squad and squad == i
        mine = t["name"] == here
        lines = (
            squad_rows_art(t, crests[t["name"]], w, i == view, cur, mine)
            if art
            else [squad_line(i, t, w, i == view, cur, mine)]
        )
        squad_rows += [highlight(l + " ", "view") if i == view else l + " " for l in lines]
        targets += [("squad", i)] * len(lines)
    out = box(f"Squads {len(towns)}", squad_rows, width)
    targets.append(None)

    members = vt["agents"] if vt else []
    hint_h = 1 if hints else 0
    avail = height - len(out) - hint_h
    low, low_targets = [], []
    if peek is not None and sel is not None and not on_squad:
        low = box(
            f"Peek · {sel['name']}", peek_rows(peek, inner, max(1, avail - 2)), width, STATUS_TAG[sel["status"]][2]
        )
        low_targets = [None] * len(low)
    elif members:
        cards = [card(a, width, a is sel and not on_squad, art) for a in members]
        i = next((k for k, a in enumerate(members) if a is sel), 0)

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
        more = lambda arrow, n: f"{fg('dim')}{f'{arrow} {n} more'.center(width)}{RESET}"
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
