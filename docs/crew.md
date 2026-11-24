# Crew commands

`party.py` has four subcommands that let one agent hand work to another, read the answer back and close the helper.
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
| 5 | The report was printed but saving the round failed (see below) |
| 7 | With `--wait --after`: the member is waiting for input and has no new report from this round. stdout is the last 20 non-empty lines of its screen, stderr `PANE is waiting for input` |
| 8 | With `--wait`: the member's newest turn ended on its usage limit (Claude Code and Codex only). stdout is the agent's limit message, stderr `PANE hit a usage limit`. With `--after`, only a limit hit after `EPOCH` counts |

Exit 8 comes at once, without waiting for the member to stop working. The limit stays until someone sends the member a new prompt, so asking again before the limit resets gives 8 again: take it to the user. Until then the HUD shows the member as waiting, so `--dismiss` refuses it like any waiting member.

Exit 7 needs a snapshot taken after the question, so right after `--ask` it can take a moment. A member that waits for input while it still has subagents running does not give 7 until they finish; if they never finish, it waits until `--timeout` (exit 3). Only Claude Code and Codex reports carry a time; for agy and grok, `--after` only waits for a snapshot newer than `EPOCH` in which the member is not working, so the printed lines may be from before it started.

## Summon and ask

`--summon AGENT` opens a pane running `claude`, `codex`, `agy` or `grok` and prints its pane id once it takes input.
`--ask PANE TEXT` pastes text into an agent's pane, presses Enter, and prints the time it was sent. Together with `--report-text PANE
--wait --after EPOCH` (above), one agent can hand work to another and wait for the answer:

```sh
m=$(python3 ~/.tmux/plugins/party-hud/party.py --summon agy)
t=$(python3 ~/.tmux/plugins/party-hud/party.py --ask "$m" "your question")
python3 ~/.tmux/plugins/party-hud/party.py --report-text "$m" --wait --after "$t"
```

`--summon AGENT [--model MODEL] [--cwd DIR] [--window | --here] [--read-only] [--timeout SEC]` (default timeout 60 s) decides where the pane goes:

- Default: a new window in a detached session `crew-<your pane number>` (`crew-12` for `%12`), created at your window's size if it does not exist yet. That session gets no sidebar; the sidebar lists the member in your squad, under you. After you switch to `crew-N`, tmux's own last-session key takes you back to the session you came from: `prefix L` by default (`switch-client -l`).
- `--window`: a new window in your own session. `--here`: a split beside your pane. Giving both exits 2.
- `--summon` only opens a tmux pane running the agent. Whether it asks for permission and which commands it allows is the user's setting in that agent; party-hud neither sets nor bypasses it. A member stopped at a permission prompt gives the lead exit 7, and the user answers in that pane.
- `--read-only` starts the agent read-only. Only codex is enforced by the system (`codex -s read-only`). claude (`--permission-mode plan`), grok (`--permission-mode plan`) and agy (`--mode plan`) start in their own plan mode: the agent refuses edits itself, nothing enforces it. Plan mode can stop a member midway: agy still asks permission for each shell command (the HUD shows it as waiting), and claude may stop at a plan approval prompt. Codex can stop too: when a command needs more than the read-only sandbox allows, it asks the user to approve running it outside the sandbox (the HUD shows it as waiting).
- `--model MODEL` starts the agent on that model, through the agent's own option: `claude --model`, `codex -m`, `agy --model`, `grok -m`. It works together with `--read-only`, `--cwd`, `--window` and `--here`; without it the agent starts on its own default. MODEL is passed as one shell-quoted argument and is not checked: a model the agent refuses at startup ends like any failed start (exit 2, stderr `no such pane: PANE`). `--model` without `--summon` exits 2. It cannot change the model of a member that is already running.
- codex is started with `-c check_for_update_on_startup=false`, with or without `--read-only`. Otherwise, when a newer Codex is out, it opens on an update prompt, the Enter of the first `--ask` picks "Update now" there, and Codex updates itself and exits.
- For a review, pass `--read-only` to codex (the sandbox enforces it); to change code, do not. For claude, agy and grok you may omit it and write "do not edit files" in the question; then nothing stops an edit except the permission settings the user has in that agent.
- A member that was itself summoned (its pane has a lead that still exists) cannot summon: exit 6, nothing is opened, stderr `PANE is crew of LEAD: report to your lead instead of summoning`. If the lead's pane is gone, it works as usual.

`--ask` exit codes:

| Exit code | Meaning |
|---|---|
| 0 | Sent; stdout is the time just before sending |
| 2 | Bad or missing pane, or tmux failure |
| 4 | The pane exists but is not a known agent |
| 5 | Sent, but saving the round failed (see below) |
| 6 | Not allowed, nothing is sent. The pane is a member of another lead whose pane still exists (stderr `PANE is crew of LEAD`), or it waits for input and its newest turn has no final answer (stderr `PANE: waiting for input, not sent`) |

An agent with no lead, your own member and a member whose lead pane is gone can be asked. So can a Claude Code or Codex member shown as waiting whose newest turn is answered (with workmux, `💬` stays on a Claude that finished and waits for the next prompt); agy and grok logs carry no turns, so a waiting one is always refused. When a pane is both another lead's member and waiting, the crew message is the one printed. The check reads the last snapshot, so a member that began to wait after it is not caught.

## Dismiss

```sh
python3 ~/.tmux/plugins/party-hud/party.py --dismiss PANE
```

Closes the pane of a member you summoned (its lead is your pane). It is refused with exit 6 unless the member is not working, has no subagents running and no finished subagent whose result the main conversation has not answered yet, is not waiting for input, and, if it is done, you have read its report with `--report-text`. The session `crew-N` is not closed separately; tmux ends it when its last pane closes. stderr says which rule refused:

- `PANE: not summoned by you`
- `PANE: still working`
- `PANE: waiting for input, not dismissed` (answer it, or take it to the user, first)
- `PANE: report not read yet; run --report-text first`

Exit 0 closed (nothing is saved), 2 not in tmux, not a pane id, pane does not exist or tmux could not close it, 4 not a known agent, 6 not allowed.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Done |
| 2 | Bad arguments, not in tmux, unknown agent, missing pane or tmux failure |
| 3 | Timeout (`--summon` ready, or `--report-text --wait`); the pane may still be alive |
| 4 | The pane is not a known agent |
| 5 | The action was done but saving the round failed (stderr says why) |
| 6 | The rules do not allow it; stderr says which one (`--summon` by a summoned member, `--ask`, `--dismiss`) |
| 7 | `--report-text --wait --after`: the member is waiting for input and has no new report |
| 8 | `--report-text --wait`: the member hit its usage limit; stdout is the limit message |

## Working together

Each member has one lead. A member does only what it was asked; when it needs help it says so in its report and the lead brings someone in or asks the user. The rules for both sides are in `skills/party-crew/SKILL.md`.

Every round is saved for later reference under `~/.local/state/party-hud/crew/` (`$XDG_STATE_HOME/party-hud/crew/` when `XDG_STATE_HOME` is set), one directory `<start time UTC>-<pane number>/round-NNN/` (the pane id without the `%`, for example `20260101T120000Z-12` for `%12`)
(`question.md`, `reply.md`, `meta.json`). `meta.json` holds `asked_at`, `pane`, `agent`, `cwd`, `lead` (the asked
member's lead pane, `""` when it has none) and `server_start` (the tmux server's `#{start_time}`) and `model` (the `--model` the member was summoned with; left out when there was none) from `--ask`, and
`replied_at` and `rc` once `--report-text` saves a reply (a report, the screen lines of an exit 7 or the limit message of an exit 8).
Party Select lists a lead's last 5 rounds from these files (see the README): only rounds whose `server_start` is the
running server's, since pane ids start over with a new server; rounds without it are not listed. Outside a task worktree
a round's title there is the first non-empty line of `question.md`, so leads start the `--ask` text with a short task name.
`--summon` removes sessions untouched for 14 days. If saving fails, `--ask`,
`--report-text` and `--summon` exit 5 after doing their job and say why on stderr (an exit 7 or 8 stays as it is; the failure is only on stderr).

## Claude Code skill (party-crew)

`skills/party-crew/SKILL.md` is a short Claude Code skill that tells Claude when and how to use `--summon`, `--ask`, `--report-text` and `--dismiss`. With it, you can tell Claude "ask codex for a second opinion on this diff" and it opens the pane, sends the question and reads the answer back. Claude loads it when the task fits, or you can call it with `/party-crew`.

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
