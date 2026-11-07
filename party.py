#!/usr/bin/env python3
"""party-hud: tmux sessions as squads, the coding agents running in them as members.

Modes (started by tmux; see party.tmux):
  party.py                    print once
  party.py --watch            popup (prefix P)
  party.py --sidebar          sidebar UI, one per window
  party.py --toggle           open / close the sidebars in every window (prefix C-t)
  party.py --next             jump to the next waiting / done member (prefix a)
  party.py --open-report [PANE]  open the report pane, floating on tmux 3.8+ else a split (prefix R, sidebar r)
  party.py --report [PANE]    what runs in the report pane: the last report of waiting / done members
  party.py --report-text PANE [--wait] [--timeout SEC]  print a member's last report; --wait until it stops working
  party.py --ensure WID       add a sidebar to a window (hook)
  party.py --reflow WID       put the sidebar width back (hook)
  party.py --nudge [WID]      restart a stopped sidebar and redraw now (hook)
  party.py --tidy             close windows left with only a sidebar (hook)
  party.py --remember-width   keep the width you dragged a sidebar to (mouse binding)
  party.py --fixture F        read fake data from a JSON file instead of tmux (tests)

Design: docs/architecture.md. What is read for each agent: docs/integrations.md.
"""

import argparse
import shutil
import sys

from party_hud.collect import get_snapshot, report_text
from party_hud.render import render
from party_hud.sidebars import ensure, nudge, open_report_pane, reflow, remember_width, tidy, toggle
from party_hud.ui import jump_next, run_report, run_ui


def main():
    ap = argparse.ArgumentParser(description="tmux party sidebar: sessions as squads, agents as members")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--sidebar", action="store_true")
    ap.add_argument("--toggle", action="store_true")
    ap.add_argument("--ensure", metavar="WINDOW_ID")
    ap.add_argument("--reflow", metavar="WINDOW_ID")
    ap.add_argument("--remember-width", action="store_true")
    ap.add_argument("--nudge", nargs="?", const="", metavar="WINDOW_ID")
    ap.add_argument("--tidy", action="store_true")
    ap.add_argument("--next", action="store_true")
    ap.add_argument("--open-report", nargs="?", const="", metavar="PANE")
    ap.add_argument("--report", nargs="?", const="", metavar="PANE")
    ap.add_argument("--report-text", metavar="PANE")
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--width", type=int)
    ap.add_argument("--fixture")
    args = ap.parse_args()
    if args.toggle:
        toggle()
    elif args.ensure:
        ensure(args.ensure)
    elif args.reflow:
        reflow(args.reflow)
    elif args.remember_width:
        remember_width()
    elif args.nudge is not None:
        nudge(args.nudge)
    elif args.tidy:
        tidy()
    elif args.next:
        jump_next()
    elif args.open_report is not None:
        open_report_pane("", args.open_report)
    elif args.report is not None:
        run_report(args.report or None, args.fixture)
    elif args.report_text is not None:
        rc, out, err = report_text(args.report_text, args.wait, args.timeout)
        sys.stdout.write(out)
        sys.stderr.write(err)
        sys.exit(rc)
    elif args.watch or args.sidebar:
        run_ui("sidebar" if args.sidebar else "popup", args.fixture)
    else:
        towns = get_snapshot(args.fixture)["towns"]
        print(render(towns, args.width or shutil.get_terminal_size().columns - 1))


if __name__ == "__main__":
    main()
