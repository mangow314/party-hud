# Sidebar

## Squad colors

- Orange: someone is waiting for you.
- Green: someone finished and you have not looked yet.
- Purple `zzz 1`: a member's prompt cache has expired.
- Gray `·1`: counts idle members.
- A bell rings in windows you are not looking at.

Each tmux session is a squad with its own crest. The squad you are looking at has a gold background and bar,
and a pin marks the session the sidebar itself is in.

## HP and SP

- HP is the context window left (`620k/1M`), blinking under 10%.
- SP counts down the prompt cache (`59/60m`); after it hits 0 the next message re-reads the whole context.
  A member with no cache data shows no SP row.
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
other pane still cannot send escape sequences straight to your terminal. The `prefix P` popup is not a pane, so it shows images only if
you set `allow-passthrough on` globally in `~/.tmux.conf` yourself (then every pane can bypass tmux); otherwise it uses
the text version. Details: [architecture.md](architecture.md#images).
