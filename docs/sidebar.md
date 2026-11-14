# Sidebar

## Squad colors

- Orange: someone is waiting for you.
- Green: someone finished and you have not looked yet. A member with a lead (crew) finishing does not turn the squad green; waiting still does.
- Purple `zzz 1`: a member's prompt cache has expired.
- Gray `·1`: counts idle members.
- A bell rings in windows you are not looking at. It does not ring for a finished crew member; waiting still rings. Once the lead is gone, crew count again.

Each tmux session is a squad with its own crest. Crew members (`crew-<N>` sessions) are listed in their lead's squad; a `crew-<N>` session never gets a sidebar. While the lead's pane exists it has no squad of its own; once the lead is gone it shows as an ordinary squad. The squad you are looking at has a gold background and bar,
and a pin marks the session the sidebar itself is in.

## HP and SP

- HP is the context window left (`620k/1M`), blinking under 10%.
- SP counts down the prompt cache (`59/60m`); after it hits 0 the next message re-reads the whole context.
  Only Claude Code members have an SP row; Codex, agy and Grok members, and a Claude Code member with no cache data,
  show none.
- The bars are colored underlines. tmux forwards the underline color only when the terminal declares `usstyle`;
  `party.tmux` adds it for Ghostty and Kitty. For another terminal, add it yourself:
  `set -as terminal-features ',<TERM>:usstyle'`.

## Changes you can see

- A card's frame blinks slowly for about 4 s when its member turns done or waiting. That squad's name in the Squads
  list blinks with it, so you see it from another squad too.
- A big change shows next to the number for about 10 s: HP in percentage points (`+40%`), SP in minutes (`-12`),
  5 or more.
- `set -g @party_anim off` turns both off.

## Narrow sidebars and many squads

- In a narrow sidebar the name is cut first and HP keeps its full value.
- Runs of empty squads fold into one `+N empty` row (the squad under the cursor always shows).
- With many squads the Squads frame shrinks around the viewed squad and shows `▲ n more` / `▼ n more`,
  so the selected card always stays on screen.
- Drag the sidebar border to resize; the width is remembered for all sidebars (minimum 30 columns).

## Images and passthrough

Images leave tmux through `allow-passthrough`, which party-hud turns on for its own sidebar and report panes only: a program in any
other pane still cannot send escape sequences straight to your terminal. Details: [architecture.md](architecture.md#images).

## After a tmux-resurrect restore

[tmux-resurrect](https://github.com/tmux-plugins/tmux-resurrect) saves a sidebar pane without a command to start again,
so a restore brings it back as an empty shell. Sidebar panes carry the pane title `party-hud`, and the save file keeps
pane titles. With two hooks party-hud turns the restored panes back into sidebars:

```tmux
set -g @resurrect-hook-pre-restore-all 'python3 ~/.tmux/plugins/party-hud/party.py --restore-begin'
set -g @resurrect-hook-post-restore-all '~/.config/tmux/party-restore.sh'
```

`~/.config/tmux/party-restore.sh` (make it executable) lists the places where the save file had a sidebar:

```sh
#!/bin/sh
# tmux-resurrect's save directory; it is ~/.tmux/resurrect when that directory exists
last="${XDG_DATA_HOME:-$HOME/.local/share}/tmux/resurrect/last"
set -f
IFS='
'
# shellcheck disable=SC2046 # split on newlines only: one place per line, session names may hold spaces
exec python3 ~/.tmux/plugins/party-hud/party.py --restore-end $(
  awk -F '\t' '$1 == "pane" && $7 == "party-hud" { print $2 ":" $3 "." $6 }' "$last"
)
```

- `--restore-begin` notes the panes that exist and keeps new windows from getting a sidebar until `--restore-end`:
  a sidebar added while a window is being rebuilt would shift the pane indexes the restore goes by.
- `--restore-end` takes places written `session:window.pane` (window and pane index). The pane at a place becomes a
  sidebar and the shell in it is ended, unless the pane existed before `--restore-begin`, is a sidebar already, or
  the place does not exist. If a pane was taken over, or the sidebars were on already, they are on afterwards and
  every window without a sidebar gets one. Without `--restore-begin` it exits 2 and changes nothing.
- party-hud does not read the save file itself; the script above does.
- Sidebars opened by an older version have no title. Close and open them once (`prefix C-t` twice) so the next save
  has it.
- If a restore stops between the two hooks, new windows get no sidebar until you run `tmux set -gu @party_restoring`.
