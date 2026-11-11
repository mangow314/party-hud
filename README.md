# party-hud

[繁體中文](README.zh-TW.md)

A tmux plugin that draws the coding agents you have running as an RPG party. At a glance you see who is waiting for
you, who has finished and how much context each one has left; from there you can jump to its pane or read its report.
It only reads, stays on your machine and uses little CPU and memory.

Each tmux session is a **squad**, each agent in it (Claude Code, Codex, agy, Grok) is a **member**
with a portrait, a status, **HP** (context left) and **SP** (prompt cache minutes left).

<img src="docs/img/window.svg" width="780" alt="A tmux window: the party-hud sidebar on the left with four squads and four member cards (a waiting codex crew member indented under its lead), an agent working in the pane on the right">

- **See who needs you**: a squad turns orange when a member waits for you, green when one finished. `n` selects the
  next waiting member, `Enter` switches to its pane.
- **Know when to compact**: HP and SP show context and prompt cache left for each member.
- **Read what it did**: `prefix R` opens the Party Select screen with a preview of each member; pick one to open its
  last report with its Markdown styled. This only reads, like the sidebar.
- **Optional: agents ask agents**: an add-on. One agent can open another, send it a question and read the answer back.
- **Cheap and local**: Python standard library only, no daemon, no network; it never writes to the agents' files.
  Measured numbers: [Footprint](#footprint).

Install with TPM (`set -g @plugin 'mangow314/party-hud'`), then press `prefix C-t`. Details: [Install](#install).

## See who needs you

A Claude Code member stops to ask a question in another window: its squad turns orange, `n` selects it and `Enter`
jumps there.

Orange means waiting for you, green means done and not seen yet, purple `zzz 1` means a prompt cache expired, gray `·1`
counts idle members. A bell rings in windows you are not looking at. More: [docs/sidebar.md](docs/sidebar.md).

The whole flow, from the sidebar to a report and back:

<img src="docs/img/demo.svg" width="830" alt="Animation: a sidebar with five squads, two empty ones folded into +2 empty; a lead summons a codex crew that turns orange with wait; n and Enter jump to it; prefix R opens the party select with member cards, the crew waiting row and a report preview; j moves to a finished member; Enter opens its report page, j scrolls, n shows the next reports; h goes back and q closes">

## Reading a card

<img src="docs/img/card.svg" width="590" alt="One member card with numbered marks: agent, portrait, class icon and name, status, HP, model, SP, subagents">

| # | Meaning |
|---|---|
| 1 | Agent: claude, codex, agy or grok |
| 2 | Portrait: one of 8 classes, picked from the session id; up to 8 members of one squad do not repeat |
| 3 | Class icon and name: the Claude Code session name (`/rename` or its automatic title), else the tmux window name; other agents show their kind |
| 4 | Status: busy, idle, wait (waiting for you), done |
| 5 | HP: context left (`620k/1M`), blinking under 10% |
| 6 | Model |
| 7 | SP: prompt cache minutes left (`59/60m`); at 0 the next message re-reads the whole context |
| 8 | Subagents running |

The frame blinks when the member turns done or waiting, and a big HP or SP change shows next to the number for a few seconds.

## Quest reports: what it did

`prefix R` opens the Party Select screen in a pane over the current window (a floating pane on tmux 3.8+, a split on
older tmux). It lists the leads of all squads, waiting first, then done, working, idle and sleeping. Each lead is the
same card the sidebar draws. A summoned member (crew) shows up only while it waits for input, as an indented row under
its lead's card.

Beside the list you see the member under the cursor: its time and directory, the state of its lead's crew, what you
asked, and a preview of its report. A working member's preview shows what it is doing now and keeps updating. A member
with no finished report yet shows the last lines of its pane. Previewing does not mark a report as read.

Move with `j`/`k` or the arrow keys, open a report with `1`–`9`, `Enter` or `l`, close with `q`/`Esc`; `?` shows the
keys. To go to a member's pane, open its report and press `Enter` there.

<img src="docs/img/select.svg" width="780" alt="The Party Select screen of `prefix R`: a pixel-art Party Select banner on top; on the left numbered member cards with portraits, a waiting codex crew member as one indented row under auth-refactor; on the right the time and directory, the crew state, the ASKED text and a cut-off preview of the working member under the cursor; key hints on the last row">

The report page opens in the same pane. In a wide pane the left column shows how long it took, how long it has waited,
what you asked, the files it edited and where it runs; the right side is the report with its Markdown styled.

<img src="docs/img/report.svg" width="780" alt="The quest report page of a finished member in a wide pane: Quest Complete banner and a framed left column with portrait, name, TOOK, WAITED, ASKED, FILES and WHERE; on the right a Markdown report with headings, a list, a small table and a code block">

A member that is still working shows what it is doing now:

<img src="docs/img/report-working.svg" width="780" alt="The in-progress page of a working member: status row with the time so far, the Now block with the newest tool call and text, then the previous round's report; RUNNING label in the left column">

In the report page `n` moves to the next member (waiting first, then done) and `h` goes back to the select screen when you came from it.
Banners, pane size, layout, scrolling, images and every key: [docs/reports.md](docs/reports.md).

## Optional: crew, agents asking agents

This is an add-on; the sidebar and the report screens work without it. The HUD itself (sidebar, select screen, report
page) only reads: it never writes to an agent's files and never uses the network. The subcommands below open panes,
send keys and close the panes they opened, and only when an agent calls them.

One agent can open another, send it a question and wait for the answer. Each step prints the value the next one needs
(a pane id such as `%12`, then the time sent):

```sh
python3 ~/.tmux/plugins/party-hud/party.py --summon codex --read-only
python3 ~/.tmux/plugins/party-hud/party.py --ask PANE 'your question'
python3 ~/.tmux/plugins/party-hud/party.py --report-text PANE --wait --after TIME
python3 ~/.tmux/plugins/party-hud/party.py --dismiss PANE
```

`--summon` opens the member in a background tmux session `crew-<your pane number>` (no sidebar); `--window` opens a new window in your session, `--here` a split beside you.
The sidebar lists crew under its lead. A crew member that finishes does not ring, light the squad or count as unread, but one that waits for input does.
`--read-only` makes codex read-only through its sandbox; claude, grok and agy use their own plan mode, which the agent enforces itself. agy in plan mode still asks permission to run shell commands; the HUD then shows it as waiting.
`--report-text` exits 7 when the member waits for input. `--dismiss` closes a member you summoned once it is not working or waiting and you read its report.
A summoned member cannot summon: it reports to its lead, and the lead brings someone in.

The path is the TPM install path; with a clone, use your checkout. With the bundled `party-crew` skill you can tell Claude Code "ask codex for a second opinion on this diff".
Exit codes, saved rounds, the skill and the sandbox setting: [docs/crew.md](docs/crew.md).

## Footprint

All numbers are from one machine (AMD Ryzen 9 5900XT, Linux, Python 3.14); how to measure on yours and the full
tables: [docs/performance.md](docs/performance.md).

- Sidebars in real use: 0.22 % of one core and 32.4 MB of memory on average, all sidebar processes together, over
  300 s with 24 windows (24 sidebar panes), 4 agents and normal window switching (`bench/live.sh`). A sidebar out of
  view stops its process after 2 s, so only the windows you look at run one.
- One sidebar frame on fake data: collecting 0.056 ms and drawing 0.294 ms for 5 agents (`bench/bench.py`, median of
  200 runs).
- Select screen and report page: 0.84 % of one core over a fixed 27.5 s key script with 5 leads in a 179 × 47 pty,
  images on (`bench/use.py`, median of 3 runs).

## Requirements

- Linux or macOS on the machine running tmux.
- tmux 3.3 or newer.
- Python 3.10 or newer as `python3` on tmux's `PATH`. On macOS the system `python3` is 3.9: install Homebrew's and
  make sure tmux finds it first, or the keys do nothing.
- A [Nerd Font](https://www.nerdfonts.com/) in your terminal.
- For portraits and crests: [Ghostty](https://ghostty.org/) or [Kitty](https://sw.kovidgoyal.net/kitty/)
  (Kitty graphics protocol with Unicode placeholders). Other terminals get the text version automatically.
- Optional: `jq`, for the Claude Code HP integration below. Without it the integration does nothing and HP stays estimated.

## Install

With [TPM](https://github.com/tmux-plugins/tpm), add this to `~/.tmux.conf` and press `prefix I`:

```tmux
set -g @plugin 'mangow314/party-hud'
```

Or clone it anywhere, add `run-shell ~/path/to/party-hud/party.tmux` to `~/.tmux.conf` and reload it
(`tmux source ~/.tmux.conf`).

Then start an agent in a tmux pane and press `prefix C-t` to open the sidebar.

The paths below assume the TPM install at `~/.tmux/plugins/party-hud`; with a clone or a different TPM path, use yours.

### HP for Claude Code (recommended)

Claude Code passes a JSON object to your statusline command. Forward it to party-hud so HP shows the real
context size and the model name. In your statusline script (`statusLine.command` in `~/.claude/settings.json`):

```bash
input=$(cat)
printf '%s' "$input" | ~/.tmux/plugins/party-hud/integrations/claude-statusline.sh
# ... the rest of your statusline, using "$input" ...
```

This needs `jq`. Without it, HP is estimated from the transcript. Details: [docs/integrations.md](docs/integrations.md).

### Terminal tips

- The HP / SP bars are colored underlines. In Ghostty they look best a little lower and thicker:

  ```
  adjust-underline-position = 2
  adjust-underline-thickness = 3
  ```

- Over SSH the remote runs everything and your local terminal only draws. The remote needs your terminal's terminfo
  (Ghostty: `shell-integration-features = ssh-terminfo`).

## Keys

| Key | Action |
|---|---|
| `prefix C-t` | Open / close the sidebar in every window |
| `prefix P` | Popup version |
| `prefix a` | Jump to the next member that is waiting or done, without opening anything |
| `prefix R` | Party Select screen: leads across squads (waiting, done, working, idle, sleep) with a preview; pick one to open its report, `h` in the report comes back |
| `j` / `k` | Next / previous member in this squad (stops at the ends) |
| `J` / `K` | Next / previous squad |
| `1`–`9` | Member N of this squad |
| `Enter` | Go to that member's pane |
| `n` | Next waiting member, then next finished one |
| `v` | Peek at the member's last lines of output |
| `r` | In the sidebar: open the selected member's quest report in a pane |
| `Esc` / `q` | Back to your pane / hide all sidebars |
| `?` | Show / hide the key help (also in the quest report); while it is open `Esc` / `q` only close the help |

Drag the sidebar border to resize; the width is remembered for all sidebars (minimum 30 columns).

## Options

Set these in `~/.tmux.conf` before the plugin loads.

| Option | Default | Meaning |
|---|---|---|
| `@party_key_toggle` | `C-t` | Key for open / close |
| `@party_key_popup` | `P` | Key for the popup |
| `@party_key_next` | `a` | Key for "next waiting" |
| `@party_key_report` | `R` | Key for quest reports |
| `@party_art` | `auto` | `on` / `off` forces images; `auto` uses them on Ghostty and Kitty |
| `@party_anim` | `on` | `off` turns off the opening animation of the report pane and the sidebar's card blink and HP / SP `+N` / `-N` labels |
| `@party_sidebar_width` | `34` | Sidebar width in columns |

The `prefix P` popup shows images only with `allow-passthrough on` set globally; see [docs/sidebar.md](docs/sidebar.md#images-and-passthrough).

## How members are detected

| Agent | Status | HP | SP |
|---|---|---|---|
| Claude Code | `~/.claude/sessions/*.json` | statusline integration, or estimated from the transcript | prompt cache TTL from the transcript |
| Codex | screen changes | rollout file in `~/.codex/sessions` | not shown |
| agy, Grok | screen changes | `--` | not shown |

A pane counts when an agent is its command or runs among its child processes. [workmux](https://github.com/raine/workmux)
status is used too. Everything is read locally; nothing is sent anywhere. Details: [docs/integrations.md](docs/integrations.md).

## Limitations

- One tmux server per user. All servers share one state folder and tmux pane ids (`%5`) repeat across servers,
  so with a second server (`tmux -L name`) the sidebars can show the wrong members or jump to the wrong pane.
  Separate sessions in one server work fine.

## More

- [docs/sidebar.md](docs/sidebar.md): squad colors, HP / SP, blinking, narrow sidebars, images
- [docs/reports.md](docs/reports.md): the quest report page in full
- [docs/crew.md](docs/crew.md): `--summon`, `--ask`, `--report-text`, `--dismiss` and the party-crew skill
- [docs/integrations.md](docs/integrations.md): what is read for each agent
- [docs/architecture.md](docs/architecture.md), [docs/performance.md](docs/performance.md): design and numbers

## Credits and license

Code: [MIT](LICENSE). Images: [CC0](art/LICENSE), generated locally with FLUX.2 [klein] 4B (Apache-2.0);
prompts, seeds and the full pipeline are in [ASSETS.md](ASSETS.md).
