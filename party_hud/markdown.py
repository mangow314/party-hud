"""Wrap text and lay out a Markdown subset into rows of a given width (pure functions; ANSI strings)."""

import re
from functools import lru_cache

from .common import RESET, cw, fg, printable


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


ESCAPE = re.compile(r"\x1b(?:\[([0-?]*)[ -/]*([@-~])|\][^\x07\x1b]*(?:\x07|\x1b\\)?|[^\[\]]?)")


def wrap_sgr(text, width, indent=False):
    """Like wrap, but keeps SGR escapes (zero width) and drops every other escape; each row ends in RESET and the next restarts the active style. indent: a continuation row starts with the first row's leading spaces and box-drawing characters unless they are over half the width."""
    rows = []
    for line in text.replace("\r", "").expandtabs(4).split("\n"):
        active, row, used, styled, pos = "", "", 0, False, 0
        plain, npre, pw = printable(ESCAPE.sub("", line)), 0, 0
        while indent and npre < len(plain) and (plain[npre] == " " or "\u2500" <= plain[npre] <= "\u257f"):
            pw += cw(plain[npre])
            npre += 1
        if pw * 2 > width or width - pw < 2:
            npre = 0
        seen, lead = 0, ""
        parts = []
        for m in ESCAPE.finditer(line):
            parts.append((line[pos : m.start()], m))
            pos = m.end()
        parts.append((line[pos:], None))
        for chars, m in parts:
            for ch in printable(chars):
                if used + cw(ch) > width:
                    rows.append(row + RESET if styled else row)
                    row, used, styled = active, 0, bool(active)
                    if npre:
                        row, used = lead + (RESET if "\x1b" in lead else "") + active, pw
                row += ch
                used += cw(ch)
                seen += 1
                if seen == npre:
                    lead = row
            if m and m.group(2) == "m" and re.fullmatch(r"[0-9;:]*", m.group(1)):
                active = "" if m.group(1) in ("", "0") else active + m.group(0)
                row += m.group(0)
                styled = True
        rows.append(row + RESET if styled else row)
    return rows


MD_INLINE = re.compile(
    r"`([^`]+)`|\*\*(.+?)\*\*|(?<!!)\[([^\]]+)\]\(([^)\s]+)\)|\*(?!\s)(.+?)(?<!\s)\*|(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)"
)
MD_HEADING = re.compile(r"#{1,6}\s+(.*)")
MD_RULE = re.compile(r"(-{3,}|\*{3,}|_{3,})\s*")
MD_ITEM = re.compile(r"(?:[-*]|\d+\.)\s+")
MD_QUOTE = re.compile(r"(?:> ?)+")
NO_LINE_START = "，。、；：？！）」』》"
MD_TABLE_SEP = re.compile(r"\|\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*")
MD_RAW = re.compile(r"\s+(?:[-*]|\d+\.)\s|\s*(?:\||>|<)")


def md_inline(text, style=""):
    """Inline Markdown -> [(char, sgr)] cells."""
    cells, pos = [], 0
    for m in MD_INLINE.finditer(text):
        cells += [(ch, style) for ch in text[pos : m.start()]]
        code, bold, label, url, em, em2 = m.groups()
        if code is not None:
            cells += [(ch, style + fg("code")) for ch in code]
        elif bold is not None:
            cells += md_inline(bold, style + "\033[1m")
        elif label is not None:
            cells += md_inline(label, style + fg("blue") + "\033[4m")
            cells += [(ch, style + fg("dim")) for ch in f" ({url})"]
        else:
            cells += md_inline(em or em2, style + "\033[3m")
        pos = m.end()
    return cells + [(ch, style) for ch in text[pos:]]


def md_tokens(cells, words):
    tokens = []
    for cell in cells:
        w = cw(cell[0])
        prev = tokens[-1] if tokens else [(" ", "")]
        joins = w == 0 or (cell[0] in NO_LINE_START and prev[0][0] != " ")
        joins = joins or (
            w == 1 and cell[0] != " " and prev[0][0] != " " and cw(prev[0][0]) < 2 and cw(prev[-1][0]) < 2
        )
        if words and tokens and joins:
            prev.append(cell)
        else:
            tokens.append([cell])
    return tokens


def md_rows(cells, width, indent=0, words=True):
    """Cells -> rows of at most width columns, continuation rows indented; each styled run ends with RESET. With words, a narrow word moves whole to the next row and no row starts with closing punctuation."""
    cells = [c for c in cells if cw(c[0]) <= width - indent]
    lines, row, used, hard = [], [], 0, set()

    def flush(is_hard=False):
        nonlocal row, used
        while words and row and row[-1][0] == " ":
            row.pop()
        if row:
            lines.append(row)
        if is_hard:
            hard.add(len(lines))
        row, used = [], 0

    for tok in md_tokens(cells, words):
        tw = sum(cw(c[0]) for c in tok)
        lim = width if not lines else width - indent
        if words and tok[0][0] == " ":
            if (row or not lines) and used + tw <= lim:
                row += tok
                used += tw
        elif used + tw <= lim:
            row += tok
            used += tw
        elif tw <= width - indent:
            flush()
            row, used = tok[:], tw
        else:
            if row and width - indent > lim - used:
                flush()
            for cell in tok:
                w = cw(cell[0])
                if used + w > (width if not lines else width - indent):
                    flush(True)
                row.append(cell)
                used += w
    flush()
    if not lines:
        lines.append([])
    for i in sorted(hard):
        while i < len(lines) and lines[i][0][0] in NO_LINE_START:
            prev = lines[i - 1]
            k = len(prev) - 1
            while k > 0 and cw(prev[k][0]) == 0:
                k -= 1
            if k < 1 or prev[0][0] in NO_LINE_START or sum(cw(c[0]) for c in prev[k:] + lines[i]) > width - indent:
                break
            lines[i] = prev[k:] + lines[i]
            del prev[k:]
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


def md_table_cells(line):
    body = line.strip()[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", body)]


def md_table(src, width):
    """Table lines (header first, separator already dropped) -> aligned columns if they fit, else one group per data row."""
    grid = [md_table_cells(line) for line in src]
    n = max(len(r) for r in grid)
    grid = [r + [""] * (n - len(r)) for r in grid]
    head, body = grid[0], grid[1:]
    bold = "\033[1m"
    dim = fg("dim")
    cells = [[md_inline(c, bold if r is head else "") for c in r] for r in grid]
    sizes = [max(sum(cw(ch) for ch, _ in row[k]) for row in cells) for k in range(n)]
    sep = [(" ", ""), ("│", dim), (" ", "")]
    lines = []
    for row in cells:
        line = []
        for k, cell in enumerate(row):
            if k:
                line += sep
            line += cell
            if k < n - 1:
                line += [(" ", "")] * (sizes[k] - sum(cw(ch) for ch, _ in cell))
        lines.append(line)
    if sum(sizes) + 3 * (n - 1) <= width:
        return (
            md_rows(lines[0], width, words=False)
            + [dim + "─┼─".join("─" * w for w in sizes) + RESET]
            + [r for line in lines[1:] for r in md_rows(line, width, words=False)]
        )
    if not body:
        return md_rows(lines[0], width)
    out = []
    indent = 2 if width > 2 else 0
    for r, row in enumerate(cells[1:]):
        if r:
            out.append("")
        for k, cell in enumerate(row):
            label = "".join(ch for ch, _ in cells[0][k]) or str(k + 1)
            label += "："
            out += md_rows([(ch, dim) for ch in label] + cell, width, indent)
    return out


def render_markdown(text, width, code_width=None, limit=None):
    """Markdown subset -> rows of at most width columns (fenced code up to code_width, default width) with SGR styles. Tables are aligned columns when they fit, else one "name: value" group per row. Nested lists, images and HTML stay raw. With limit, laying out stops after the block that brings the rows past limit: the rows are the first rows of the full layout, and more than limit only when the text goes on. The last 32 results are kept; callers get their own copy of the rows."""
    return list(_markdown_rows(text, width, code_width or width, limit))


def clear_markdown_cache():
    _markdown_rows.cache_clear()


@lru_cache(maxsize=32)
def _markdown_rows(text, width, code_width, limit):
    rows, code = [], False
    lines = printable_lines(text)
    i = 0
    while i < len(lines) and (limit is None or len(rows) <= limit):
        line = lines[i]
        i += 1
        if not code and line.startswith("|") and i < len(lines) and MD_TABLE_SEP.fullmatch(lines[i]):
            end = i + 1
            while end < len(lines) and lines[end].startswith("|"):
                end += 1
            rows += md_table([line] + lines[i + 1 : end], width)
            i = end
        elif line.startswith("```"):
            code = not code
        elif code:
            rows += md_rows([(ch, fg("green")) for ch in line], code_width, words=False)
        elif m := MD_HEADING.fullmatch(line):
            rows += md_rows(md_inline(m[1], fg("gold", True)), width)
        elif MD_RULE.fullmatch(line):
            rows.append(fg("dim") + "─" * width + RESET)
        elif m := MD_QUOTE.match(line):
            n = min(m[0].count(">"), max(width - 3, 0))
            bar = fg("dim") + "▎" * n + RESET + " " if n else ""
            rows += [bar + r for r in md_rows(md_inline(line[m.end() :], fg("dim")), width - n - 1 if n else width)]
        elif MD_RAW.match(line) or line.lstrip().startswith("!["):
            rows += md_rows([(ch, "") for ch in line], width)
        elif m := MD_ITEM.match(line):
            mark = "•" if m[0][0] in "-*" else m[0].split()[0]
            body = md_inline(line[m.end() :])
            rows += md_rows([(ch, "") for ch in mark + " "] + body, width, cw(mark) + 1)
        else:
            rows += md_rows(md_inline(line), width)
    return tuple(rows)


def printable_lines(text):
    return [printable(line) for line in text.replace("\r", "").expandtabs(4).split("\n")]
