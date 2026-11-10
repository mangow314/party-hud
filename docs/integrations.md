# Integrations

Process information (child processes, command lines, start times) comes from `/proc` on Linux and from one
`ps -axo pid=,ppid=,lstart=,args=` call per collection elsewhere (macOS).

party-hud only reads files. This page lists what it reads for each agent, so you can check what it sees
or add support for another agent.

## Claude Code

| What | Source | Written by |
|---|---|---|
| Which pane runs Claude, session id, name, busy / idle / waiting | `~/.claude/sessions/<pid>.json` (`pid`, `sessionId`, `name`, `status`, `tmux`) | Claude Code |
| Transcript path | `~/.claude/projects/*/<session id>.jsonl` (found by session id) | Claude Code |
| SP: when the prompt cache expires | last `usage` entry in the transcript: its timestamp + TTL (1 h if it wrote `ephemeral_1h_input_tokens`, else 5 min) | Claude Code |
| Quest report (`prefix R`, read only when opened) | text blocks of the last answered turn after its last `tool_use`, and the timestamps of its prompt and last text; subagent (`isSidechain`) and `isMeta` entries are skipped, as are prompts nobody answered (`!` commands, `/cost`) | Claude Code |
| Report left column (read only when the report opens) | the turn runs from the last prompt the user typed (a `type: user` record whose `origin.kind` is absent or `human`, not `isMeta`/`isSidechain`/`isCompactSummary`, and whose text, after cutting `<system-reminder>` blocks, does not start with `<task-notification>`, `<local-command-`, `<bash-input>`, `<bash-stdout>`, `<bash-stderr>` or `[Request interrupted`); its text is `ASKED` (a `<command-name>` record shows as `/name args`); `tool_use` of the main conversation only (subagent logs are not read): distinct `file_path` of `Edit`, `Write`, `MultiEdit`, `NotebookEdit` listed in first-edit order (`FILES`), `Bash` (cmds), `Agent` / `Task` (agents); `WAITED` is now minus the report's end | Claude Code |
| In-progress page (member `working`; re-read every 1.5 s while the report is open, last 1 MB of the log) | the same turn from the last typed prompt to now: its timestamp (elapsed time), the newest main-conversation `tool_use` (`name` plus `command` / `file_path` / `description` / `pattern` / `url` / `query` / `prompt`, first line) and the newest assistant text; the answer of the turn before it is the previous report | Claude Code |
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
| Quest report (`prefix R`, read only when opened) | last `task_complete` event in the rollout file: `last_agent_message`, `started_at`, `completed_at` |
| Report left column (read only when the report opens) | the first `item_completed` event with item `UserMessage` of the finished turn (`turn_id`) for `ASKED` (its `text` parts); `CommandExecution` items of that turn for cmds. Edits go through commands, so files and agents are not shown |
| In-progress page (member `working`; re-read every 1.5 s while the report is open, last 1 MB of the file) | newest `task_started` with no `task_complete` after it: `started_at`, its `UserMessage` / `CommandExecution` items as above, the newest `response_item` of type `function_call`, `custom_tool_call` or `local_shell_call` (`name` plus the first line of `input` / `arguments`, `cmd` or `command` when it is JSON), the newest `AgentMessage` text; the last `task_complete` before it is the previous report |

The rollout file is found in two ways:

1. A file under `~/.codex/sessions/` held open by a process in the pane (Linux only: read from `/proc/<pid>/fd`).
2. Newer Codex builds write rollouts from a background app-server instead. Then the newest rollout whose
   `session_meta.cwd` equals the pane's directory and that was modified after the Codex process started is used.
   If several Codex sessions run in the same directory, they are ordered by start time, and each takes the earliest
   rollout whose `session_meta.timestamp` is not earlier than its own start time (1 second of slack) and that no
   other session has taken.

SP is not shown: OpenAI does not publish a fixed cache lifetime we could count down
([prompt caching guide](https://developers.openai.com/api/docs/guides/prompt-caching)).

## agy, Grok

Detected by the pane's command name, or among its child processes as for Codex. Working / idle comes from screen changes, as for Codex. They write no report: the
report pane reads their last reply off the screen (the text after the last prompt line, without the input box below it), and its left column has no prompt, work counts, directory or wait.

## Directory and git branch

The report's `WHERE` is tmux `pane_current_path` (home directory written `~`) plus the branch, read from files only (no `git` process): walk up to `.git`; a directory holds `HEAD`, a file (worktree) names the `gitdir:` that holds it. `ref: refs/heads/<name>` shows `<name>`, a detached HEAD the 7-character sha.

## workmux

If a pane has the tmux option `@workmux_pane_status` set by [workmux](https://github.com/raine/workmux)
(`🤖` working, `💬` waiting, `✅` done), that status wins over the others, except that Claude Code's own
`waiting` wins over `🤖` (workmux switches to `💬` only when Claude's notification hook runs, a few seconds later).

## Adding an agent

1. Add the command name to `AGENT_CMDS` in `party_hud/collect.py`.
2. If the agent writes a log with token usage, add a reader like `codex_usage` and call it in `collect()`.
3. Add a fixture case to `tests/party-test.sh` (see the `"codex"` key in the fixtures).
