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
  party.py --report-text PANE [--wait [--after EPOCH]] [--timeout SEC]  print a member's last report; --wait until it stops working;
                              --after EPOCH (the time --ask printed) also waits for a report that ends after it
  party.py --ask PANE TEXT    type TEXT into an agent's pane and press Enter (several lines: one paste); print the time sent
  party.py --summon AGENT [--cwd DIR] [--window] [--read-only] [--timeout SEC]  open a pane running AGENT, wait until it takes input, print the pane id;
                              --read-only starts it in an enforced read-only sandbox (codex only)
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
import subprocess
import sys
import time

from party_hud.collect import get_snapshot, report_text
from party_hud.common import tmux_run
from party_hud.render import render
from party_hud.sidebars import ensure, nudge, open_report_pane, reflow, remember_width, summon, tidy, toggle
from party_hud.ui import jump_next, run_report, run_ui


def ask(pane, text):
    """(rc, stdout, stderr) for party.py --ask. rc: 0 sent (stdout: the time just before sending), 2 bad or missing pane or tmux failure, 4 not an agent.
    The text goes in as one bracketed paste, then Enter: codex takes an Enter right after typed keys as a newline."""
    if not pane.startswith("%") or not pane[1:].isdigit():
        return 2, "", f"not a pane id: {pane}\n"
    rc, _, err = tmux_run(["display-message", "-p", "-t", pane, "#{pane_id}"])
    if rc != 0:
        return 2, "", err or f"no such pane: {pane}\n"
    if not any(a["pane"] == pane for t in get_snapshot()["towns"] for a in t["agents"]):
        return 4, "", f"not a known agent: {pane}\n"
    sent = time.time()
    r = subprocess.run(
        ["tmux", "load-buffer", "-b", "party-ask", "-"], input=text, capture_output=True, text=True, check=False
    )
    rc, err = r.returncode, r.stderr
    if rc == 0:
        rc, _, err = tmux_run(["paste-buffer", "-p", "-d", "-b", "party-ask", "-t", pane])
    if rc == 0:
        rc, _, err = tmux_run(["send-keys", "-t", pane, "Enter"])
    if rc != 0:
        return 2, "", err or f"tmux could not send to {pane}\n"
    return 0, f"{sent}\n", ""


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
    ap.add_argument("--ask", nargs=2, metavar=("PANE", "TEXT"))
    ap.add_argument("--after", type=float, metavar="EPOCH")
    ap.add_argument("--summon", metavar="AGENT")
    ap.add_argument("--cwd", metavar="DIR")
    ap.add_argument("--window", action="store_true")
    ap.add_argument("--read-only", action="store_true", help="with --summon: enforced read-only sandbox, codex only")
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--timeout", type=float)
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
        rc, out, err = report_text(
            args.report_text, args.wait, 600 if args.timeout is None else args.timeout, args.after
        )
        sys.stdout.write(out)
        sys.stderr.write(err)
        sys.exit(rc)
    elif args.ask is not None:
        rc, out, err = ask(*args.ask)
        sys.stdout.write(out)
        sys.stderr.write(err)
        sys.exit(rc)
    elif args.summon is not None:
        rc, out, err = summon(
            args.summon, args.cwd, args.window, 60 if args.timeout is None else args.timeout, args.read_only
        )
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
