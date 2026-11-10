# Crew commands

`party.py` has three subcommands that let one agent hand work to another and read the answer back.
The paths below assume the TPM install at `~/.tmux/plugins/party-hud`; replace it with your install path.

The sidebar still only reads; these commands open panes or send keys only when called.

## Reading a report from a script

```sh
python3 ~/.tmux/plugins/party-hud/party.py --report-text PANE [--wait] [--timeout SEC]
```

`PANE` is a tmux pane id such as `%12`. Without `--wait` it prints the member's current report at once. With `--wait`,
if the member is working, still has subagents running, or has a finished subagent the main conversation has not answered
yet, it waits until that stops and then prints. `--timeout` is the most seconds to wait (default 600).

| Exit code | Meaning |
|---|---|
| 0 | Report printed. A known agent with no report also exits 0: stdout is empty and stderr says `no report for PANE` |
| 2 | Bad arguments (not a pane id, bad timeout) or the pane does not exist |
| 3 | `--timeout` ran out while waiting |
| 4 | The pane exists but is not a known agent |

## Summon and ask

`--summon AGENT` opens a pane running `claude`, `codex`, `agy` or `grok` and prints its pane id once it takes input.
`--ask PANE TEXT` pastes text into an agent's pane, presses Enter, and prints the time it was sent. Together with `--report-text PANE
--wait --after EPOCH` (above), one agent can hand work to another and wait for the answer:

```sh
m=$(python3 ~/.tmux/plugins/party-hud/party.py --summon agy)
t=$(python3 ~/.tmux/plugins/party-hud/party.py --ask "$m" "your question")
python3 ~/.tmux/plugins/party-hud/party.py --report-text "$m" --wait --after "$t"
```

`--summon` exits 0 ready, 2 bad arguments or tmux failure, 3 timeout (`--cwd DIR`, `--window`, `--timeout SEC`). `--summon codex --read-only` starts codex in its enforced read-only sandbox (`-s read-only`); the other agents have no such mode and exit 2. `--ask` exits
0 sent, 2 bad or missing pane, 4 not an agent.

Every round is saved for later reference under `~/.local/state/party-hud/crew/` (`$XDG_STATE_HOME/party-hud/crew/` when `XDG_STATE_HOME` is set), one directory `<start time UTC>-<pane id>/round-NNN/`
(`question.md`, `reply.md`, `meta.json`). `--summon` removes sessions untouched for 14 days. If saving fails, `--ask`,
`--report-text` and `--summon` exit 5 after doing their job and say why on stderr.

## Claude Code skill (party-crew)

`skills/party-crew/SKILL.md` is a short Claude Code skill that tells Claude when and how to use `--summon`, `--ask` and `--report-text`. With it, you can tell Claude "ask codex for a second opinion on this diff" and it opens the pane, sends the question and reads the answer back. Claude loads it when the task fits, or you can call it with `/party-crew`.

Link it once:

```sh
mkdir -p ~/.claude/skills
ln -s ~/.tmux/plugins/party-hud/skills/party-crew ~/.claude/skills/party-crew
```

With Claude Code's Bash sandbox on, these commands cannot reach the tmux socket (`Error connecting to /tmp/tmux-1000/default (Operation not permitted)`). To let them run, add party.py to `sandbox.excludedCommands` in `~/.claude/settings.json`:

```json
"excludedCommands": ["python3 ~/.tmux/plugins/party-hud/party.py *"]
```

- Matching commands run outside the sandbox, with no file or network limits, so add only this one.
- The match is on the command text, and every part of the line has to match: a line with `$(...)`, a redirect or `cd` stays in the sandbox. So Claude has to run each step as its own call and read the pane id and time from the output, not use the `m=$(...)` form above.
- `sandbox.network.allowAllUnixSockets` also works, but it opens every Unix socket; not recommended.
