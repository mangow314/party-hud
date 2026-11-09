---
name: party-crew
description: Use when you need another coding agent (claude, codex, agy, grok) in the same tmux to work with you, or need to ask an agent already running in a tmux pane and read its report back.
---

# party-crew

Three `party.py` subcommands let you open an agent pane, send it a question, and wait for its reply. Run them from inside tmux (`$TMUX_PANE` must be set). `party.py` is `~/.tmux/plugins/party-hud/party.py` if installed through tpm, otherwise the path of your checkout.

The HUD itself only reads. These subcommands open a pane or send keys only when you call them; they never write to an agent's files and never use the network.

## When to use which

- `--summon AGENT`: you need a new helper. Opens a pane running `claude`, `codex`, `agy` or `grok` and waits until it takes input.
- `--ask PANE TEXT`: you have a pane id (from `--summon` or `%N` of a running agent) and want to send it a question.
- `--report-text PANE --wait --after EPOCH`: you sent a question and need the answer. Blocks until the agent has finished a report newer than your question, then prints it.

## Commands

`party.py --summon AGENT [--cwd DIR] [--window] [--read-only] [--timeout SEC]`
- `--read-only`: starts the agent in an enforced read-only sandbox. Only `codex` has one (`codex -s read-only`); other agents exit 2 and no pane is opened. Use it for review work that must not change the tree.
- Splits next to your pane (or `--window` for a new window), working dir `--cwd` (default: current).
- stdout: the new pane id, e.g. `%12`. `--timeout` default 60.
- Exit: 0 ready, 2 bad arguments, unknown agent, not in tmux, or tmux failure, 3 timeout.

`party.py --ask PANE TEXT`
- Pastes TEXT into the agent's pane as one paste (several lines included) and presses Enter.
- stdout: the time sent (epoch seconds). Keep it for `--after`.
- Exit: 0 sent, 2 bad or missing pane or tmux failure, 4 pane is not a known agent.

`party.py --report-text PANE --wait --after EPOCH [--timeout SEC]`
- Waits while the agent is working or has subagents running, and until a report newer than EPOCH exists, then prints it. `--after` requires `--wait`. `--timeout` default 600.
- Without `--after` it prints the current report (add `--wait` to let the agent finish first).
- Exit: 0 printed (a known agent with no report: empty stdout, stderr `no report for PANE`), 2 bad arguments or missing pane, 3 timeout, 4 not a known agent.
- Only claude and codex reports carry a time. For agy and grok, `--after` only waits for a snapshot newer than EPOCH in which the agent is not working, so it can print the pane's lines from before the agent started. Prefer codex or claude when you need this round's answer.

## Example

Run each step as its own command and copy the value it prints into the next one:

```sh
python3 ~/.tmux/plugins/party-hud/party.py --summon codex --read-only
# prints %12
python3 ~/.tmux/plugins/party-hud/party.py --ask %12 'Review src/foo.py for race conditions and report findings'
# prints 1762680000.5
python3 ~/.tmux/plugins/party-hud/party.py --report-text %12 --wait --after 1762680000.5
```

Claude Code's Bash sandbox blocks the tmux socket (`Error connecting to /tmp/tmux-…/default (Operation not permitted)`). The user can allow these commands with `sandbox.excludedCommands`, which matches the command text: the line has to start with `python3` and the path as listed (no shell variable for the path), every command in the line has to match, and a line with `$(...)`, a redirect or `cd` stays in the sandbox. So run one step per call, as above. Put the question in single quotes so the shell does not expand backticks or `$` in it. If you still get the error, report it to the user instead of working around it.

Every round is saved under `${XDG_STATE_HOME:-~/.local/state}/party-hud/crew/<start time UTC>-<pane id>/round-NNN/` (`question.md`, `reply.md`, `meta.json`); `--summon` deletes sessions older than 14 days. Exit 5 from `--summon`, `--ask` or `--report-text` means the action was done but saving the round failed (see stderr).

Check the exit code of each step: 3 from `--summon` or `--report-text` means it timed out and the pane may still be alive; 4 means the pane is not an agent.
