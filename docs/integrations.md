# Integrations

Process information (child processes, command lines, start times) comes from `/proc` on Linux and from one
`ps -axo pid=,ppid=,lstart=,args=` call per collection elsewhere (macOS).

party-hud only reads files. This page lists what it reads for each agent, so you can check what it sees
or add support for another agent.

## Claude Code

| What | Source | Written by |
|---|---|---|
| Which pane runs Claude, session id, name, busy / idle | `~/.claude/sessions/<pid>.json` (`pid`, `sessionId`, `name`, `status`, `tmux`) | Claude Code |
| Transcript path | `~/.claude/projects/*/<session id>.jsonl` (found by session id) | Claude Code |
| SP: when the prompt cache expires | last `usage` entry in the transcript: its timestamp + TTL (1 h if it wrote `ephemeral_1h_input_tokens`, else 5 min) | Claude Code |
| Subagents in flight (paw count) | `<transcript without .jsonl>/subagents/*.meta.json`, not `finished`, log touched in the last 15 min | Claude Code |
| HP: context left and context size, model name | `$XDG_RUNTIME_DIR/party-hud/<pane>.json` | `integrations/claude-statusline.sh` |

### The statusline file

`integrations/claude-statusline.sh` turns Claude Code's statusline JSON into one file per tmux pane
(`<pane>` is `$TMUX_PANE` without the `%`). Fields:

| Field | Type | From statusline JSON |
|---|---|---|
| `updated` | epoch seconds | time of writing |
| `session_id` | string, `[A-Za-z0-9_-]` only | `.session_id` |
| `ctx_left` | integer percent or `null` | `100 - .context_window.used_percentage` |
| `ctx_size` | integer tokens or `null` | `.context_window.context_window_size` |
| `transcript` | path ending in `.jsonl`, or `""` | `.transcript_path` |
| `model` | string | `.model.display_name`, with any ` (…)` suffix removed |

If `session_id` does not match the session Claude Code reports for that pane, the file is ignored
(the pane was reused by another session). You can write this file from any language; only the fields above are read.

Without the file, HP is estimated from the transcript: the tokens sent in the last request, against a 200k window
(or 1M if more than 200k were sent).

## Codex

| What | Source |
|---|---|
| Which pane runs Codex | the pane's command is `codex`, or a child process (up to 3 levels down) is `codex` or an interpreter (`node`, `bun`, `deno`, `python*`) running a `codex` script |
| Working / idle | the pane's screen changed in the last 4 seconds (only a CRC32 hash of the screen is stored, in `activity.json`) |
| HP | last `token_count` event in the rollout file: `last_token_usage.total_tokens` of `model_context_window` |

The rollout file is found in two ways:

1. A file under `~/.codex/sessions/` held open by a process in the pane (Linux only: read from `/proc/<pid>/fd`).
2. Newer Codex builds write rollouts from a background app-server instead. Then the newest rollout whose
   `session_meta.cwd` equals the pane's directory and that was modified after the Codex process started is used.
   Two Codex sessions in the same directory will show the same HP.

SP is not shown: OpenAI does not publish a fixed cache lifetime we could count down
([prompt caching guide](https://developers.openai.com/api/docs/guides/prompt-caching)).

## agy, Grok

Detected by the pane's command name, or among its child processes as for Codex. Working / idle comes from screen changes, as for Codex. HP and SP show `--`.

## workmux

If a pane has the tmux option `@workmux_pane_status` set by [workmux](https://github.com/raine/workmux)
(`🤖` working, `💬` waiting, `✅` done), that status wins over the others.

## Adding an agent

1. Add the command name to `AGENT_CMDS` in `party_hud/collect.py`.
2. If the agent writes a log with token usage, add a reader like `codex_usage` and call it in `collect()`.
3. Add a fixture case to `tests/party-test.sh` (see the `"codex"` key in the fixtures).
