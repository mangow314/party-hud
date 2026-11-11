"""Render the README demo, an animated SVG of the whole tool, from a fixture and a script of steps.

  python3 scripts/demo.py scripts/demo.json docs/img/demo.svg

Every screen is drawn by the same functions as the other README images (scripts/screenshot.py): the sidebar beside a pane,
the select screen and the report page as floating panes over the window, sized and placed by the rules of sidebars.py.
The animation is CSS @keyframes inside the SVG (no script, no external file): each screen is a group that is visible only in its
time slice. The first screen is what a viewer without animation shows. Images and repeated screens are stored once.
Needs Pillow and the fonts of screenshot.py.

demo.json: "fixture" (screenshot.json format, with its "reports" by name), "screens" (text beside the sidebar and
status line, by name), and "steps". A step is one screen shown for "dur" seconds; keys not given stay as in the step before, except
"flash", "reveal" (step of the report's opening animation) and "set" (a patch of the fixture: "panes" is merged by pane id, a
dict is merged, anything else replaced), which count for their step only. "view" is window, select or report; "sel" is the
sidebar selection or the select cursor; "report" the entry of "reports" the select preview or report page shows; "caption" is
[key, text]. The clock of the fixture runs with the animation, so RUNNING times count up."""

import json
import os
import sys
import tempfile
from collections import Counter

S = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, S)
import screenshot as sc

from party_hud.render import set_tick
from party_hud.sidebars import REPORT_PANE_COLS, SELECT_PANE_COLS, report_span, select_span

CW, CH = sc.CW, sc.CH
WIN_COLS, WIN_ROWS = 162, 45  # the window: wide enough for the report pane at its widest
CAP_BG = (20, 24, 40)
LINE = (58, 66, 102)
GOLD, DIM = "\x1b[1m\x1b[38;2;240;180;90m", "\x1b[38;2;120;128;160m"
MARKUP = {"DIM": sc.DIM, "TXT": sc.TXT, "OK": sc.OK, "ACC": sc.ACC}


def patch(state, change):
    for key, val in change.items():
        if key == "panes":
            by_id = {p["pane_id"]: p for p in state["panes"]}
            for pid, fields in val.items():
                if pid in by_id:
                    by_id[pid].update(fields)
                else:
                    state["panes"].append(dict(fields))
        elif isinstance(val, dict) and isinstance(state.get(key), dict):
            patch(state[key], val)
        else:
            state[key] = val


def merge(defs, new):
    for name, text in new.items():
        assert defs.setdefault(name, text) == text, f"two different images named {name}"


def floating(defs, panel, cols, left, top):
    """The elements of the panel canvas as a floating pane: opaque (the page may be transparent), framed, at cell (left, top) of the window."""
    x, y, w, h = left * CW, top * CH, cols * CW, panel.h
    merge(defs, panel.defs)
    return [
        (
            f'<rect x="{x - 3}" y="{y - 3}" width="{w + 6}" height="{h + 6}" fill="{sc.hx(sc.BG)}"'
            f' stroke="{sc.hx(LINE)}" stroke-width="2"/>'
        ),
        f'<svg x="{x}" y="{y}" width="{panel.w}" height="{h}" viewBox="0 0 {panel.w} {h}">',
        *panel.body,
        "</svg>",
    ]


def caption_layer(width, row, caption):
    cv = sc.Canvas(width, 0)
    cv.rect(0, row * CH, width, (row + 1) * CH, CAP_BG)
    key, text = caption
    cv.paint(f" {GOLD}{key}\x1b[0m{'  ' if key else ''}{DIM}{text}", 0, row)
    return cv


def write_state(state, tmp, name):
    path = os.path.join(tmp, name)
    with open(path, "w") as f:
        json.dump(state, f)
    return path


def render_step(cur, state, under, tick, tmp):
    """Layers of one step. The window below a floating pane keeps the clock it had when the pane opened, so those steps share one window layer."""
    now = state["now"]
    path = write_state(state, tmp, "state.json")
    data = {"now": now}
    win_path = path if cur["view"] == "window" else write_state({**state, "now": under[0]}, tmp, "under.json")
    screen = cur["screens"][cur["screen"]]
    fill = {**MARKUP}
    main = "\n".join(line.format(**fill) for line in screen["main"])
    status = screen["status"].format(**fill)
    view = cur["view"]
    win = sc.shot(
        win_path,
        sel=cur.get("sel") if view == "window" else None,
        height=WIN_ROWS,
        main=main,
        status=status,
        tick=tick if cur["view"] == "window" else under[1],
        flash=cur.get("flash", ()),
        main_cols=WIN_COLS - 35,
    )
    els = list(win.body)
    defs = dict(win.defs)
    if view != "window":
        entry = cur["reports"][cur["report"]]
        set_tick(tick)
        if view == "select":
            panel = sc.select_page(path, data, entry, cur["sel"])
            cols, left = select_span(WIN_COLS)
            assert cols == SELECT_PANE_COLS
        else:
            panel = sc.report_page(path, data, entry, offset=cur.get("offset", 0), frame=cur.get("reveal"))
            cols, left = report_span(WIN_COLS)
            assert cols == REPORT_PANE_COLS
        els += floating(defs, panel, cols, left, WIN_ROWS // 10)
    cap = caption_layer(win.w, WIN_ROWS + 1, cur["caption"])
    els += cap.body
    merge(defs, cap.defs)
    return els, defs


def pct(v):
    return f"{v:.4f}".rstrip("0").rstrip(".")


def build(spec):
    state = json.loads(json.dumps(spec["fixture"]))
    base_now = state["now"]
    cur = {"screens": spec["screens"], "reports": spec["fixture"]["reports"]}
    frames, defs, t, under = [], {}, 0.0, (base_now, 0)
    with tempfile.TemporaryDirectory() as tmp:
        for tick, step in enumerate(spec["steps"]):
            if "set" in step:
                patch(state, step["set"])
            state["now"] = base_now + int(t)
            cur.pop("flash", None)
            cur.pop("reveal", None)
            cur.update({k: v for k, v in step.items() if k not in ("set", "dur")})
            if cur["view"] == "window":
                under = (state["now"], tick)
            els, new = render_step(cur, state, under, tick, tmp)
            merge(defs, new)
            frames.append((t, step["dur"], els))
            t += step["dur"]
    return frames, defs, t


def svg(frames, defs, total):
    used = Counter(el for _, _, els in frames for el in dict.fromkeys(els))
    shared = {}
    for el, n in used.items():
        if (n - 1) * len(el) > 30 + 23 * n and el.count("<svg") == el.count("</svg>"):
            shared[el] = f"e{len(shared)}"
            defs[shared[el]] = f'<g id="{shared[el]}">{el}</g>'
    css = [
        f".f{{visibility:hidden;animation-duration:{total:g}s;animation-iteration-count:infinite;"
        + "animation-timing-function:step-end}.f0{visibility:visible}"
    ]
    body = []
    for i, (start, dur, els) in enumerate(frames):
        keys = ([] if i == 0 else ["0%{visibility:hidden}"]) + [f"{pct(start * 100 / total)}%{{visibility:visible}}"]
        if i + 1 < len(frames):
            keys.append(f"{pct((start + dur) * 100 / total)}%{{visibility:hidden}}")
        css.append(f".k{i}{{animation-name:k{i}}}@keyframes k{i}{{{''.join(keys)}}}")
        inner = "".join(f'<use href="#{shared[x]}"/>' if x in shared else x for x in els)
        body.append(f'<g class="f k{i}{" f0" if i == 0 else ""}">{inner}</g>')
    cv = sc.Canvas(WIN_COLS * CW, (WIN_ROWS + 2) * CH)
    cv.defs = defs
    cv.body = [f"<style>{''.join(css)}</style>", *body]
    return cv.svg()


if __name__ == "__main__":
    with open(sys.argv[1]) as f:
        spec = json.load(f)
    out = svg(*build(spec))
    with open(sys.argv[2], "w") as f:
        f.write(out)
    print(sys.argv[2], len(out.encode()))
