---
name: party-crew
description: Use when you need another coding agent (claude, codex, agy, grok) in the same tmux to work with you, or need to ask an agent already running in a tmux pane and read its report back.
---

# party-crew

Four `party.py` subcommands let you open an agent pane, send it a question, wait for its reply and close it. Run them from inside tmux (`$TMUX_PANE` must be set). `party.py` is `~/.tmux/plugins/party-hud/party.py` if installed through tpm, otherwise the path of your checkout.

The HUD itself only reads. These subcommands open or close a pane or send keys only when you call them; they never write to an agent's files and never use the network.

## When to use which

- `--summon AGENT`: you need a new helper. Opens a pane running `claude`, `codex`, `agy` or `grok` and waits until it takes input.
- `--ask PANE TEXT`: you have a pane id (from `--summon` or `%N` of a running agent) and want to send it a question.
- `--report-text PANE --wait --after EPOCH`: you sent a question and need the answer. Blocks until the agent has finished a report newer than your question, then prints it.
- `--dismiss PANE`: you read the answer and expect no follow-up. Closes a member you summoned.

## Commands

`party.py --summon AGENT [--cwd DIR] [--window | --here] [--read-only] [--timeout SEC]`
- Default: a new window in your own detached session `crew-<your pane number>` (created at your window's size if it does not exist yet). That session gets no sidebar; the sidebar lists the member under you. `--window`: a new window in your session. `--here`: a split beside your pane. `--window` and `--here` together exit 2.
- Working dir `--cwd` (default: current).
- `--summon` only opens a pane running the agent. Whether it asks permission and what it allows is the user's setting in that agent; you neither set nor bypass it.
- `--read-only`: starts the agent read-only. Only `codex` is enforced by the system (`codex -s read-only`). `claude`, `grok` and `agy` start in their own plan mode: the agent refuses edits itself, nothing enforces it. Plan mode can stop a member midway: `agy` still asks permission for each shell command (the HUD shows it as waiting), and `claude` may stop at a plan approval prompt. `codex` can stop too, when it asks the user to approve a command its read-only sandbox blocks (also shown as waiting).
- Review: pass `--read-only` to `codex`; to have it change code, do not. For `claude`, `agy` and `grok` you may omit it and write "do not edit files" in the question; then only the user's permission settings in that agent stop an edit.
- stdout: the new pane id, e.g. `%12`. `--timeout` default 60.
- A member that was itself summoned (its pane has a lead that still exists) gets exit 6 and no pane is opened: stderr `PANE is crew of LEAD: report to your lead instead of summoning`. If the lead's pane is gone, it works as usual.
- Exit: 0 ready, 2 bad arguments, unknown agent, not in tmux, tmux failure, or the new pane closed before it was ready (stderr `no such pane: PANE`), 3 timeout, 6 the rules do not allow it (stderr says which one).

`party.py --ask PANE TEXT`
- Pastes TEXT into the agent's pane as one paste (several lines included) and presses Enter.
- stdout: the time sent (epoch seconds). Keep it for `--after`.
- Exit: 0 sent, 2 bad or missing pane or tmux failure, 4 pane is not a known agent.

`party.py --report-text PANE --wait --after EPOCH [--timeout SEC]`
- Waits while the agent is working, has subagents running, or has a finished subagent whose result its main conversation has not answered yet, and until a report newer than EPOCH exists, then prints it. `--after` requires `--wait`. `--timeout` default 600.
- Without `--after` it prints the current report (add `--wait` to let the agent finish first).
- If the agent is waiting for input and has no report newer than EPOCH, it returns 7 at once: stdout is the last 20 non-empty lines of the pane's screen, stderr `PANE is waiting for input`. This also covers agy and grok. It needs a snapshot taken after your question, so right after `--ask` it can take a moment.
- A member that waits for input while it has subagents running, or a finished subagent's result not yet answered, does not give 7; it keeps waiting. It gives 7 once the subagents are done and their results are handled; if that never happens, the wait ends at the timeout (exit 3).
- Exit: 0 printed (a known agent with no report: empty stdout, stderr `no report for PANE`), 2 bad arguments or missing pane, 3 timeout, 4 not a known agent, 7 waiting for input.
- Only claude and codex reports carry a time. For agy and grok, `--after` only waits for a snapshot newer than EPOCH in which the agent is not working, so it can print the pane's lines from before the agent started. Prefer codex or claude when you need this round's answer.

`party.py --dismiss PANE`
- Closes the pane of a member you summoned (its lead is your pane). When it was the last pane of the `crew-` session, tmux ends that session.
- Refused with exit 6, stderr says which: the member was not summoned by you, it is still working (or has subagents running, or a finished subagent's result its main conversation has not answered yet; stderr `PANE: still working`), it waits for input (`PANE: waiting for input, not dismissed`), or it is done and you did not read its report (run `--report-text` first).
- Exit: 0 closed, 2 not in tmux, bad or missing pane, tmux could not close the pane, 4 not a known agent, 6 the rules do not allow it (stderr says which one).

## Example

Run each step as its own command and copy the value it prints into the next one:

```sh
python3 ~/.tmux/plugins/party-hud/party.py --summon codex --read-only
# prints %12
python3 ~/.tmux/plugins/party-hud/party.py --ask %12 'Review src/foo.py for race conditions and report findings'
# prints 1762680000.5
python3 ~/.tmux/plugins/party-hud/party.py --report-text %12 --wait --after 1762680000.5
# prints the report
python3 ~/.tmux/plugins/party-hud/party.py --dismiss %12
```

## Acting as lead

- Each member has one lead; do not send it a second question before you read the reply to the first.
- Answer a member yourself only when the answer is in scope, already covered by what the user asked, and easy to undo. Anything that needs the user's approval (permissions, skipping hooks, pushing, deleting) goes to the user, whether it comes as a prompt or as text.
- Send the first question once `--summon` returned 0; send each later question only when the member's last `--report-text` returned 0. Never use text or keys to answer a permission prompt. Exit 7 means the member waits for input: show the user the printed lines.
- When a member is blocked on the user, ask the user right away and keep doing work that does not depend on the answer. Merge questions you can ask together: at most two options and your pick.
- For review questions, ask the member to answer directly rather than propose a plan (claude in plan mode may otherwise stop on a plan approval). Even when asked this way, claude in plan mode can still stop on a plan approval prompt: `--report-text` then returns 7 and the printed lines hold its conclusion. Hand them to the user as for any exit 7; do not approve with keys.
- For review questions, ask the member to list what it checked and what it did not check, and to give `path:line` for each finding. Treat a finding without a location as unconfirmed: open the file and check it yourself before you use it.
- Dismiss a member only after you checked its report and expect no follow-up. Timeout, exit 7, or exit 5 does not mean done.
- `--dismiss` exits 6 for a member that waits for input: answer it or take it to the user first. Do not dismiss right after `--ask`: the HUD may still show the member idle for about two seconds.

## Working as a member

- Do the one thing your lead asked. When you cannot finish it, or need someone else, say in your reply who you need and for what, then end the turn.
- Do not run `--summon`: it exits 6 while your lead's pane exists. Your lead decides whether to bring someone in, and takes what it cannot settle to the user.

Claude Code's Bash sandbox blocks the tmux socket (`Error connecting to /tmp/tmux-…/default (Operation not permitted)`). The user can allow these commands with `sandbox.excludedCommands`, which matches the command text: the line has to start with `python3` and the path as listed (no shell variable for the path), every command in the line has to match, and a line with `$(...)`, a redirect or `cd` stays in the sandbox. So run one step per call, as above. Put the question in single quotes so the shell does not expand backticks or `$` in it. If you still get the error, report it to the user instead of working around it.

`--report-text --wait` can block until `--timeout` (default 600 seconds), and a shell tool with a shorter command limit kills it first (Claude Code's Bash: 2 minutes by default, 10 minutes at most). Do one of: set the tool's timeout to at least `--timeout`; run it in the background; or pass a smaller `--timeout` and call it again on exit 3 (3 does not mean the member finished or failed).

Every round is saved under `${XDG_STATE_HOME:-~/.local/state}/party-hud/crew/<start time UTC>-<pane id>/round-NNN/` (`question.md`, `reply.md`, `meta.json`); `--summon` deletes sessions older than 14 days. Exit 5 from `--summon`, `--ask` or `--report-text` means the action was done but saving the round failed (see stderr).

Check the exit code of each step: 2 with stderr `no such pane: PANE` means the member's pane is gone (its agent exited or the pane was closed): tell the user and summon again; 3 from `--summon` or `--report-text` means it timed out and the pane may still be alive; 4 means the pane is not an agent; 6 means a rule refused it, read stderr.
