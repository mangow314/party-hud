#!/usr/bin/env python3
"""party-hud: tmux sessions as squads, the coding agents running in them as members."""

import subprocess
import sys
import time

from party_hud.collect import FIELD_SEP, get_snapshot, pane_values, report_text
from party_hud.common import tmux_run
from party_hud.sidebars import (
    crew_asked,
    crew_replied,
    crew_summoned,
    dismiss,
    ensure,
    mark_seen,
    nudge,
    open_report_pane,
    reflow,
    remember_width,
    restore_begin,
    restore_end,
    summon,
    tidy,
    toggle,
)


def ask(pane, text):
    """(rc, stdout, stderr) for party.py --ask. rc: 0 sent (stdout: the time just before sending), 2 bad or missing pane
    or tmux failure, 4 not an agent, 5 sent but not saved."""
    if not pane.startswith("%") or not pane[1:].isdigit():
        return 2, "", f"not a pane id: {pane}\n"
    found, err = pane_values(pane, "#{pane_current_path}", "#{start_time}", "#{@party_model}")
    if found is None:
        return 2, "", err
    cwd, server, model = found[0], found[1], FIELD_SEP.join(found[2:])
    agent = next((a for t in get_snapshot()["towns"] for a in t["agents"] if a["pane"] == pane), None)
    if agent is None:
        return 4, "", f"not a known agent: {pane}\n"
    sent = time.time()
    # one bracketed paste, then Enter: codex takes an Enter right after typed keys as a newline
    buf = f"party-ask-{pane[1:]}"
    r = subprocess.run(["tmux", "load-buffer", "-b", buf, "-"], input=text, capture_output=True, text=True, check=False)
    rc, err = r.returncode, r.stderr
    if rc == 0:
        rc, _, err = tmux_run(["paste-buffer", "-p", "-d", "-b", buf, "-t", pane])
    if rc == 0:
        rc, _, err = tmux_run(["send-keys", "-t", pane, "Enter"])
    if rc != 0:
        return 2, "", err or f"tmux could not send to {pane}\n"
    err = crew_asked(pane, text, sent, agent["kind"], cwd, agent.get("lead", ""), server, model)
    return (5 if err else 0), f"{sent}\n", err


def main():
    argv = sys.argv[1:]
    if argv == ["--sidebar"]:
        from party_hud.ui import leave_without_teardown, run_ui

        run_ui()
        leave_without_teardown()
        return
    if argv == ["--select"]:
        from party_hud.ui import leave_without_teardown, run_menu

        run_menu()
        leave_without_teardown()
        return
    if argv == ["--report"] or (len(argv) == 2 and argv[0] == "--report" and not argv[1].startswith("-")):
        from party_hud.ui import leave_without_teardown, run_report

        run_report(argv[1] or None if len(argv) == 2 else None)
        leave_without_teardown()
        return
    import argparse

    ap = argparse.ArgumentParser(
        description="tmux party sidebar: sessions as squads, agents as members",
        epilog="--ask, --report-text and --summon save each round under ${XDG_STATE_HOME:-~/.local/state}/party-hud/crew/ "
        "(kept 14 days). Exit code 5: the action was done but saving failed (see stderr). "
        "--report-text exit code 7: the member is waiting for input, stdout is the end of its screen. "
        "Exit code 6: the rules do not allow it (stderr says which one).",
    )
    ap.add_argument("--sidebar", action="store_true")
    ap.add_argument("--toggle", action="store_true")
    ap.add_argument("--ensure", metavar="WINDOW_ID")
    ap.add_argument("--reflow", metavar="WINDOW_ID")
    ap.add_argument("--remember-width", action="store_true")
    ap.add_argument("--nudge", nargs="?", const="", metavar="WINDOW_ID")
    ap.add_argument("--tidy", action="store_true")
    ap.add_argument("--restore-begin", action="store_true")
    ap.add_argument("--restore-end", nargs="*", metavar="PLACE")
    ap.add_argument("--next", action="store_true")
    ap.add_argument("--menu", action="store_true")
    ap.add_argument("--select", action="store_true")
    ap.add_argument("--open-report", nargs="?", const="", metavar="PANE")
    ap.add_argument("--report", nargs="?", const="", metavar="PANE")
    ap.add_argument("--report-text", metavar="PANE")
    ap.add_argument("--ask", nargs=2, metavar=("PANE", "TEXT"))
    ap.add_argument("--dismiss", metavar="PANE")
    ap.add_argument("--after", type=float, metavar="EPOCH")
    ap.add_argument(
        "--summon", metavar="AGENT", help="open a pane running AGENT (exit 6 if the caller is itself a summoned member)"
    )
    ap.add_argument(
        "--model",
        metavar="MODEL",
        help="with --summon: start the agent on MODEL, passed to its own model option (claude --model, codex -m, agy --model, grok -m) and saved in each round's meta.json; a model the agent refuses at startup ends like any failed start (exit 2, no such pane: PANE)",
    )
    ap.add_argument("--cwd", metavar="DIR")
    ap.add_argument("--window", action="store_true")
    ap.add_argument("--here", action="store_true")
    ap.add_argument(
        "--read-only",
        action="store_true",
        help="with --summon: codex runs in an enforced read-only sandbox; claude, grok and agy start in their own plan mode (the agent refuses edits itself, the system does not enforce it; agy still asks permission to run shell commands, codex to run one outside its sandbox, and the HUD then shows it as waiting)",
    )
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--timeout", type=float)
    ap.add_argument("--width", type=int)
    ap.add_argument("--fixture")
    args = ap.parse_args()
    if args.model is not None and args.summon is None:
        ap.error("--model needs --summon")
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
    elif args.restore_begin:
        restore_begin()
    elif args.restore_end is not None:
        rc, out, err = restore_end(args.restore_end)
        sys.stdout.write(out)
        sys.stderr.write(err)
        sys.exit(rc)
    elif args.next:
        from party_hud.ui import jump_next

        jump_next()
    elif args.menu:
        from party_hud.ui import open_select

        open_select()
    elif args.select:
        from party_hud.ui import run_menu

        run_menu(args.fixture)
    elif args.open_report is not None:
        open_report_pane("", args.open_report)
    elif args.report is not None:
        from party_hud.ui import run_report

        run_report(args.report or None, args.fixture)
    elif args.report_text is not None:
        read = {}
        rc, out, err = report_text(
            args.report_text, args.wait, 600 if args.timeout is None else args.timeout, args.after, read
        )
        record_seen = rc == 0 and bool(out) and "round" in read
        if rc in (0, 7) and out:
            save_err = crew_replied(args.report_text, out, rc)
            if save_err:
                rc, err = (5 if rc == 0 else rc), err + save_err
        sys.stdout.write(out)
        sys.stdout.flush()
        if record_seen:
            try:
                mark_seen(args.report_text, read["round"])
            except OSError as e:
                err += f"could not record the report as read: {e}\n"
        sys.stderr.write(err)
        sys.exit(rc)
    elif args.ask is not None:
        rc, out, err = ask(*args.ask)
        sys.stdout.write(out)
        sys.stderr.write(err)
        sys.exit(rc)
    elif args.dismiss is not None:
        rc, out, err = dismiss(args.dismiss)
        sys.stdout.write(out)
        sys.stderr.write(err)
        sys.exit(rc)
    elif args.summon is not None:
        rc, out, err = summon(
            args.summon,
            args.cwd,
            args.window,
            60 if args.timeout is None else args.timeout,
            args.read_only,
            args.here,
            args.model,
        )
        if rc == 0:
            save_err = crew_summoned(out.strip())
            rc, err = (5, err + save_err) if save_err else (rc, err)
        sys.stdout.write(out)
        sys.stderr.write(err)
        sys.exit(rc)
    elif args.sidebar:
        from party_hud.ui import run_ui

        run_ui(args.fixture)
    else:
        import shutil

        from party_hud.render import render

        towns = get_snapshot(args.fixture)["towns"]
        print(render(towns, args.width or shutil.get_terminal_size().columns - 1))


if __name__ == "__main__":
    main()
