# Architecture

`party.py` is the entry point, started in different modes by tmux. The code is in `party_hud/` (Python standard
library only):

| Module | What it does |
|---|---|
| `common.py` | colors, status names, classes, text width, tmux calls, the shared cursor and error log |
| `art.py` | loads `art/`, sends images (Kitty graphics protocol), draws placeholders |
| `collect.py` | reads tmux, agent session files, transcripts and rollouts; the shared snapshot and its lock |
| `render.py` | draws the squad list and cards from a snapshot (pure functions). The Squads frame gets the rows left after the selected card (or the first one), the border and the hint row; when the squads do not fit it keeps the viewed squad and as many neighbours as fit, with `▲ n more` / `▼ n more` rows (n counts squads, a folded `+N empty` run counts N) |
| `sidebars.py` | opens, closes, restarts and resizes sidebar panes; installs the hooks |
| `ui.py` | the sidebar / popup loop: input, cursor, redraws |

A module imports only modules listed above it, so there are no import cycles.

```
 tmux key / hook                         party.py modes
 ----------------                        --------------
 prefix C-t  ------------------------->  --toggle   open or close a sidebar pane in every window, install hooks
 after-new-window / new-session hook ->  --ensure   add a sidebar to a new window
 window-resized hook ----------------->  --reflow   put the sidebar width back
 session / window changed, attach --->  --nudge    restart this window's sidebar if it was stopped, redraw now
 after-kill-pane hook --------------->  --tidy     close windows left with only a sidebar (a report pane counts as one)
 sidebar pane ------------------------>  --sidebar  the long-running UI, one per window
 prefix P ---------------------------->  --watch    the same UI in a popup
 prefix a ---------------------------->  --next     jump to the next waiting / done member and exit
 prefix R, sidebar r ----------------->  --open-report  open a report pane: floating (tmux 3.8+) or split, running --report
```

## One collector, many readers

Every sidebar is its own process, but they share one snapshot:

```
 sidebar A --+                         +--> read tmux list-panes, session files,
 sidebar B --+--> snapshot.json older  |    transcripts, rollouts, capture-pane
 sidebar C --+    than 2 s?  -- yes -->+    (only the process holding snapshot.lock)
                  |                    |
                  no                   +--> write snapshot.json (atomic rename)
                  |
                  v
             render from snapshot, redraw only if the frame changed
```

- `snapshot.lock` is an `fcntl` lock. A sidebar that does not get it uses the old snapshot instead of waiting.
- The UI loop wakes once per second (or on a key press) for the spinner, countdowns and blinking.
- With 20+ sidebars open, data is still collected about once every 2 seconds (checked by `tests/party-tmux-test.sh`).

## Only visible sidebars run

Each Python sidebar takes about 25 MB, so one per window adds up (24 windows: about 590 MB). Instead:

1. Sidebar panes have `remain-on-exit on` (with an empty `remain-on-exit-format`).
2. A sidebar that has been out of view for 2 seconds exits. The pane stays, still showing its last frame.
3. When you switch to a window (or attach), `--nudge` runs `respawn-pane` on that window's stopped sidebar.
   The new process starts (about 50 ms), reads the snapshot and redraws.
4. Work that used to happen in every window's own sidebar moved:
   - bells: the process that collects the snapshot writes a BEL to the pane of a hidden member that just started
     waiting or finished, so tmux flags that window;
   - windows left with only a sidebar (or a report pane) are closed by the `--tidy` hook (after `kill-pane`) and by the collector
     (when the main program exits by itself).

The 2-second delay keeps quick back-and-forth switching from restarting processes.

## State files

All in `$XDG_RUNTIME_DIR/party-hud/` (or `~/.cache/party-hud/`). Deleting the folder is safe.

| File | What |
|---|---|
| `snapshot.json` / `snapshot.lock` | shared snapshot and its lock |
| `<pane>.json` | statusline integration output (see [integrations](integrations.md)) |
| `activity.json` | CRC32 of each non-Claude pane's screen and when it last changed |
| `unseen.json` | members that finished while you were not looking ("done" until you look) |
| `bells.json` | each member's status at the last collection, to ring only on a change, and to set the tmux option `@party_reports` (members waiting or done) only when that number changes |
| `collections` | how many times data was collected (used by the tests and `bench/live.sh`) |
| `cursor.json` | shared cursor, so every sidebar highlights the same member |
| `error.log` | tracebacks; a sidebar that hits an error logs it and retries next second |

## Images

Portraits and crests use the [Kitty graphics protocol](https://sw.kovidgoyal.net/kitty/graphics-protocol/)
with Unicode placeholders:

1. When a sidebar has been visible for a second, it sends the 16 PNGs once (wrapped in tmux passthrough), each with
   an id. `allow-passthrough` is a pane option; `mark_sidebar` sets it on the sidebar pane only, so other panes keep
   tmux's default and cannot reach the outer terminal. `mark_report` does the same for the quest report pane (`@party_report`), which draws the
   member's portrait. The `--watch` popup has no pane and gets images only when the user set it
   globally. The wait matters: while tmux redraws a client (after a split, a session switch or an attach) it drops
   passthrough without counting it, and an image that loses one chunk stays black.
2. Each image cell is drawn as the character U+10EEEE, colored with the image id, plus two combining
   diacritics for row and column. tmux treats these as normal text, so scrolling, redrawing and pane
   switching just work.
3. The terminal replaces the placeholders with the image.

`art_supported` decides whether to use images: the `@party_art` option, otherwise the outer terminal name
(`client_termname`) contains `ghostty` or `kitty`. Other terminals get the text version, which has the same
information without pictures.

The report pane runs on the alternate screen, so tmux has no old content to reflow while the pane is dragged. SIGWINCH wakes
its loop through a pipe (`signal.set_wakeup_fd`); the page is redrawn in place at most once per `RESIZE_INTERVAL`, counted from the start of the render (a redraw costs
about 55 ms for a 300-row report, so the measured rate there is about 17 per second). Images are resent under the same id only after
`RESIZE_SETTLE` without a new signal, since each banner resend is tens of KB through passthrough.

The split page's left column scrolls with nothing, so `report_parts` (fixed) cuts it to the pane height when it is taller: rows are cut from the bottom (the order is portrait and name, TOOK, ASKED, FILES, WHERE, page number, so lists go first), a dim `…` row (no arrow: the column does not scroll) stands above the hint, and the hint stays on the last content row. A portrait that the cut would split is dropped whole. This runs in `report_parts`, once per page and per resize, never per scroll step.

A fresh page (the first one, `n`, `N`; not a resize, a live re-read or a scroll) opens with `report_frames`: the banner, head and left column are in every frame and the right column's paragraphs appear in at most 5 steps over `ANIM_TOTAL` (0.4 s), counting only paragraphs that start in the visible rows. `report_parts` runs once per page, and a step is one slice plus one write. The wait between steps is the loop's own `select`, so input or SIGWINCH ends the animation without being read, and the main loop handles it as before. The image wait `REPORT_ART_SETTLE` (0.3 s, shorter than the sidebar's 1 s `ART_SETTLE`, chosen by trying it in Ghostty) counts from the first frame, so the animation does not delay the images. `@party_anim off` (read once when the pane opens) turns it off.

The report pane remembers each image id it has sent with its cells (`sent`, kept across pages). On a fresh page an id already sent at the same cells is not deleted or resent, so banner and portrait do not blink when `n` or `N` changes page; one sent at other cells is resent under the same id without a delete; one never sent is deleted and then sent after `REPORT_ART_SETTLE`. The first frame of a fresh page also carries the deletes for the ids never sent (`report_first_deletes`), so a stale image under the same id in the terminal is gone before the placeholders show. The sidebar portrait is never deleted, since it shares its id with the sidebar. When the pane ends normally it deletes every image it sent (again except the sidebar portrait) in the same write that leaves the alternate screen, so the next report page finds no older image under its ids to show; a pane that is killed cleans up nothing.

## HP / SP bars

Each bar is the label and number text with a colored underline (`SGR 4` + `SGR 58` underline color):
the first part in the bar color, the rest dim. tmux forwards underline colors only when the terminal declares the
`usstyle` feature, which `party.tmux` adds for Ghostty and Kitty.

## Classes and crests

A member's class (portrait) comes from a hash of its session id, and a squad's crest from a hash of the session
name. `spread()` assigns them so that up to 8 members of one squad (or 8 squads) never share one.
Renaming a window does not change them.
