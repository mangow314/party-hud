# Architecture

`party.py` is the entry point, started in different modes by tmux. The code is in `party_hud/` (Python standard
library only):

| Module | What it does |
|---|---|
| `common.py` | colors, status names, classes, text width (`cw`: ASCII strings are `len`, other characters reuse a 4096-entry `lru_cache` of per-character widths), tmux calls, the shared cursor and error log |
| `art.py` | loads `art/`, sends images (Kitty graphics protocol), draws placeholders |
| `collect.py` | reads tmux, agent session files, transcripts and rollouts; the shared snapshot and its lock |
| `render.py` | draws the squad list and cards from a snapshot (pure functions; `render_markdown` remembers the last 32 layouts, so the same input gives the same output and it is still input in, text out). The Squads frame gets the rows left after the selected card (or the first one), the border and the hint row; when the squads do not fit it keeps the viewed squad and as many neighbours as fit, with `▲ n more` / `▼ n more` rows (n counts squads, a folded `+N empty` run counts N) |
| `sidebars.py` | opens, closes, restarts and resizes sidebar panes; installs the hooks |
| `ui.py` | the sidebar loop: input, cursor, redraws |

A module imports only modules listed above it, so there are no import cycles.

`party.py` loads only what the sub-command it runs needs. `--sidebar`, `--select`, `--report` and `--report PANE`, the
three long-running processes, are recognised from `sys.argv` before anything else and go straight to `run_ui`,
`run_menu` or `run_report`, so they never import `argparse` (about 0.5 MB); any other argument list, including
`--fixture` and `--help`, goes through `argparse` as before. `party.py` imports `collect`, `common` and `sidebars` at the
top, which every sub-command uses; `ui` and `render` are imported inside the branch that needs them, so the tmux
hooks that run `--ensure`, `--reflow`, `--nudge`, `--tidy` or `--remember-width` on every window event, and `--ask`,
`--dismiss`, `--summon` and `--report-text`, do not pay for them. `shutil` (the terminal size, the 14-day cleanup of
saved rounds) is imported where it is used; only the three long-running processes go without it, because
`argparse` loads it. Nothing in `party_hud/` imports `typing` or `traceback` at start-up
(`log_error` imports `traceback` when an error is logged).

The same three sub-commands leave through `ui.leave_without_teardown`: when the screen function returns normally,
`party.py` flushes stdout and stderr and calls `os._exit(0)`, which skips the interpreter's module and object teardown
(about 5 ms of CPU per exit; a sidebar leaves and starts again on every window switch). It is not used when the screen
function raises (the exception propagates, the traceback is printed, the exit code is not 0, the interpreter shuts down
normally), on the `argparse` path (`--sidebar --fixture F` and the like) or in any short-lived sub-command. The terminal
is restored before `party.py` is back in control: every screen function restores termios, mouse reporting, the cursor
and the alternate screen in its own `finally` block and flushes stdout there, so no exit path of `run_ui`, `run_select`
or `run_report` depends on the interpreter's shutdown. Nothing in `party.py` or `party_hud/` uses `atexit`, `__del__`
or a temporary file.

```
 tmux key / hook                         party.py modes
 ----------------                        --------------
 prefix C-t  ------------------------->  --toggle   open or close a sidebar pane in every window, install hooks
 after-new-window / new-session hook ->  --ensure   add a sidebar to a new window
 window-resized hook ----------------->  --reflow   put the sidebar width back
 session / window changed, attach --->  --nudge    restart this window's sidebar if it was stopped, redraw now
 after-kill-pane hook --------------->  --tidy     close windows left with only a sidebar (a report pane counts as one)
 sidebar pane ------------------------>  --sidebar  the long-running UI, one per window
 prefix a ---------------------------->  --next     jump to the next waiting / done member and exit
 prefix R ---------------------------->  --menu      open a pane running --select, the select screen
 sidebar r --------------------------->  --open-report  open a report pane: floating (tmux 3.8+) or split, running --report
```

`--menu` opens the same kind of pane as `--open-report`, running `--select`, but at most `select_cols(ratio)` wide (82 at a cell ratio of 0.5) so the banner is the whole 4:1 image; the report page's pane is at most `report_cols(ratio)` wide (105 at 0.5: sized for the 6:1 banner, since the flatter 8:1 image cuts too much of the scene, and never below `SPLIT_MIN_WIDTH` + 3 so the split layout survives wide cells), and both take `ratio` from tmux's `window_cell_width` / `window_cell_height` (0.5 when tmux gives none, since there is no tty to ask), asked in the same `display-message` as the window size; the banner's rows follow the width and its image is the k:1 one (k = 4..8) closest to the cells' shape (`fit_banner`), cut and centred only when the cells are more than one column wider than the image, so a drawable width one or two columns short of the pane's still fills the width; `run_menu` calls `fit_report_pane` once before each report page (report size) and once before each return to the select screen (select size), only on floating panes. The select screen and the report page it opens are one process: `run_menu` alternates `run_select` and `run_report`, so `h` in the report returns to the select screen without a new pane. The select screen calls `get_snapshot` about once per second, like a sidebar, so under the lock rule below it can be the process that collects; it has no wake of its own while a time is on screen: the read happens at the wake of a time anchor when the last read is at least `SNAP_AGE` (0.9 s) old, and `select_wait` falls back to one second after the read when the next anchor is more than `SNAP_MAX` (1.9 s) after it (no anchor at all, or only 60 s anchors), so the snapshot is never older than 2 s. It redraws only when a shown time value changes and writes only when the frame differs from the last one written (the wall-clock second for the spinner and the low-HP blink, only while a member works or has HP <= 10; the cursor member's `start` / `end` through `time_anchor` for `RUNNING` / `WAITED`: `fmt_took` rounds, so a value turns at timestamp + n + `ROUND_HALF` every second, and from 3600 s on, when only the minute shows, at timestamp + 60 n - `ROUND_HALF` every 60 s; an anchor is a (time, period) pair and `tick_wait` gives the wait to the first one, with a 10 ms margin so a wake just before the boundary does not spin). `select_phase` puts the spinner (and the low-HP blink) on the phase of the cursor member's second-by-second time anchor, so the tick is `floor(now - anchor)` and the spinner turns in the same instant as `RUNNING` / `WAITED`: one wake and one frame a second instead of two with different phases. It does not apply when no such time is shown (no preview, cursor member neither live working nor waiting with an `end`) or when the time is past 3600 s and turns once a minute: the spinner then turns on the whole second as before. When the phase changes (the cursor moves to a member with another phase or none, or a time passes 3600 s) the tick holds its value and the next step falls on the new phase's next boundary (less than a second later), so the tick never goes back or skips; a step lasts less than 2 seconds when the phase changes once, and when it changes again before the step ends (the cursor keeps moving) the step lasts until the boundary after the last change; `run_select` carries the state `select_phase` returns from frame to frame. A screen thus recomputes once a second while a second-by-second time anchor is on screen; with the whole-second spinner anchor and a once-a-minute anchor (the cursor member's time is past 3600 s and a member works) the phases differ, so there is one extra wake a minute, as before. At the moment the cursor member's time passes 3600 s the anchor moves from the time's phase back to the whole second, and that one snapshot read can be up to about 1.9 s after the last (1 s otherwise), still within `SNAP_MAX`. The screen re-reads the cursor member's log once `LIVE_REFRESH` seconds have passed, checked at those wakes (so 1.5 s to the next wake, at most about 2.5 s), only when that member works; the report page reads the snapshot when it opens and on `n` / `N`. The select screen's images (the banner and the portraits of the member cards on screen) are each sent only when their content or cell size changes, judged against the `sent` it shares with the report page. When the screen is left no image is deleted (see the report pane below for why). `run_select` calls `select_view` once a frame, which builds each member card once to measure it and returns the rows with the layout; `select_cards` (which portraits to send) and `render_select` both take that view, so a card is built once a frame. `render_select` lays out the member cards (`select_card`, the sidebar card with a number key) and, when the pane is wide enough, `select_preview` beside them; the preview draws the report with `report_rows`, the first rows of the same rows as the report page: it passes `limit` (the rows it can show), `render_markdown` stops after the block (a line, a whole table, a paragraph or list item, a code line) that brings the rows past `limit`, so what shows is a prefix of the full layout and the last row says `… more · ⏎ to read`.

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
| `unseen.json` | per pane `{status, unseen, round}`: members that finished while you were not looking ("done" until you look or read the report), and the round counter below; a pane that is gone keeps its round |
| `seen.json` / `seen.lock` | per pane, the round whose report was read (see Crew) |
| `bells.json` | each member's status at the last collection, to ring only on a change, plus the key `reports`: the unread count last written to the tmux option `@party_reports` (waiting members, and done members that have no lead), which is set only when that number changes |
| `collections` | how many times data was collected (used by the tests and `bench/live.sh`) |
| `cursor.json` | shared cursor, so every sidebar highlights the same member |
| `error.log` | tracebacks; a sidebar that hits an error logs it and retries next second |

## Crew

`--summon` opens a member in the detached session `crew-<lead pane number>` (created at the lead window's size; later members become new windows in it) unless `--window` or `--here` is given. `--ensure` returns at once for a session whose name starts with `crew-`, so those sessions get no sidebar (the new-session hook fires before any option could be set, so the name is the test; a session you name `crew-xxx` yourself is treated the same). The summoned pane carries the pane option `@party_lead` (the lead's pane). The collector moves a member whose `@party_lead` is a live agent in another squad into the lead's squad and drops the squad that this empties (`adopt_crews`), then `group_under_leads` lists it right under its lead. This goes one level only: a member whose lead is itself a member of another lead is not indented under it and is not treated as crew (its done still alerts); it stays in the squad where its lead sits at collection time. When the lead pane is gone, the crew session shows as an ordinary squad.

A crew member's `done` does not alert: it does not rank in the report queue's waiting/done tier (it falls in the rest), `--next`, bells, `@party_reports` and the squad alert (and the squad title's "· N done"). `waiting` alerts as for anyone. Without a lead the member alerts again.

Round numbers: each time the collector sees a member go from working to idle or asleep, its `round` grows by 1 (kept in `unseen.json`, put in the snapshot). When the report page shows a finished report, or `--report-text` prints a non-empty report (exit 0), that member's `seen` becomes the `round` of the report shown. `mark_unseen` does not mark a member `done` when `seen >= round`, so a report read through `--report-text` stops the "done" mark, and `--dismiss` accepts a done member whose `seen` caught up. `seen.json` has its own lock, `seen.lock`, and is replaced atomically; the collector only reads it. It does not reuse `snapshot.lock` so that the report page and `--report-text` never wait for a collection, and "only the lock holder collects" stays true. The round only advances while some collector runs, so with no sidebar or reader two rounds can count as one; a member no collector saw working is not marked done, so neither the alert nor the `--dismiss` unread check fires for it; `--report-text --after` compares the report time, not the round, and still returns a report newer than the question.

A summoned member does not summon: `summon` in `sidebars.py` exits 6 when the caller pane has `@party_lead` and that pane still exists. Collaboration follows how people split work: a crew member does the one thing it was given, reports to its lead what it needs, and the lead decides whether to bring someone in or take it to the user. When the lead pane is gone the member can summon again.

## Images

Portraits and crests use the [Kitty graphics protocol](https://sw.kovidgoyal.net/kitty/graphics-protocol/)
with Unicode placeholders:

1. When a sidebar has been visible for a second, it sends the 16 PNGs once (wrapped in tmux passthrough), each with
   an id. `allow-passthrough` is a pane option; `mark_sidebar` sets it on the sidebar pane only, so other panes keep
   tmux's default and cannot reach the outer terminal. `mark_report` does the same for the quest report pane (`@party_report`), which draws the
   member's portrait. The wait matters: while tmux redraws a client (after a split, a session switch or an attach) it drops
   passthrough without counting it, and an image that loses one chunk stays black.
2. Each image cell is drawn as the character U+10EEEE, colored with the image id, plus two combining
   diacritics for row and column. tmux treats these as normal text, so scrolling, redrawing and pane
   switching just work.
3. The terminal replaces the placeholders with the image.

`load_art` only checks at start-up that all 56 files in `art/` can be opened and keeps each image's path and cell size; `send_image` reads the one file when it is sent and keeps no reference to the bytes. An image is sent about once per process, so holding all 56 PNGs (2.1 MB) in every long-running process would cost memory for nothing. A file that cannot be read at that point (deleted while the program runs) is logged with `log_error()` and that image is not sent. The bytes still go through the terminal's escape sequences, not as a path the terminal reads, because the terminal may be on the other end of an SSH connection.

`art_supported` decides whether to use images: the `@party_art` option, otherwise the outer terminal name
(`client_termname`) contains `ghostty` or `kitty`. Other terminals get the text version, which has the same
information without pictures.

The report pane runs on the alternate screen, so tmux has no old content to reflow while the pane is dragged. SIGWINCH wakes
its loop through a pipe (`signal.set_wakeup_fd`); the page is redrawn in place at most once per `RESIZE_INTERVAL`, counted from the start of the render (a redraw costs
about 55 ms for a 300-row report, so the measured rate there is about 17 per second). Images are resent under the same id only after
`RESIZE_SETTLE` without a new signal, since each banner resend is tens of KB through passthrough.

The split page's left column scrolls with nothing, so `report_parts` (fixed) cuts it to the pane height when it is taller: rows are cut from the bottom (the order is portrait and name, TOOK, ASKED, FILES, WHERE, page number, so lists go first), a dim `…` row (no arrow: the column does not scroll) stands above the hint, and the hint stays on the last content row. A portrait that the cut would split is dropped whole. This runs in `report_parts`, once per page, per resize, per live re-read and per time redraw of the page, never per scroll step.

`?` on the report page lays `help_overlay` over the rows `report_view` returns: every page row in faint text (SGR 2 after each SGR, so a Kitty placeholder keeps its image-id color and the image stays bright), the key box centered, page text kept left and right of it. It is computed on open, resize, live re-read and the redraw at a time boundary (`tick_wait` over `start` of a live page and `end` of a split page, each through `time_anchor` because `fmt_took` rounds; a tick whose rows equal the last ones written writes nothing; text only: images, scroll offset and the opening animation are untouched), not per frame; the sidebar `?` still shows the full-pane `help_screen`.

A fresh page (the first one, `n`, `N`; not a resize, a live re-read or a scroll) opens with `report_frames`: the banner, head and left column are in every frame and the right column's paragraphs appear in at most 5 steps over `ANIM_TOTAL` (0.4 s), counting only paragraphs that start in the visible rows. `report_parts` runs once per page (the animation plays only on a fresh page), and a step is one slice plus one write. The wait between steps is the loop's own `select`, so input or SIGWINCH ends the animation without being read, and the main loop handles it as before. The images are sent right after the first frame is written, before the other steps, so the animation does not delay them; there is no fixed wait. Only after a pane resize do they wait for `RESIZE_SETTLE` without a new signal. `@party_anim off` (read once when the pane opens) turns it off.

The report pane remembers each image id it has sent with its cells (`sent`, kept across pages; when opened from the select screen it is the select screen's own `sent`: `run_menu` calls `load_images` once, which checks the image files and makes the one `sent`, and passes both to every `run_select` and `run_report`, so an image already in the terminal at the same cells is not sent again when the screens switch; a report page opened directly makes its own). On a fresh page an id already sent at the same cells is not deleted or resent, so banner and portrait do not blink when `n` or `N` changes page; one sent at other cells is resent under the same id without a delete; one never sent is deleted and then sent right after the first frame. The first frame of a fresh page also carries the deletes for the ids never sent (`report_first_deletes`), so a stale image under the same id in the terminal is gone before the placeholders show. The sidebar portrait is never deleted, since it shares its id with the sidebar. When the pane ends it deletes no image: the ids are shared by every pane in the terminal, so a delete on exit would remove an image another pane still shows. An image left in the terminal has no placeholder pointing at it, so it is not visible, and the delete before the next page's first frame replaces it. When an open page turns from in progress into the final report (the new banner id is sent once), the images that send actually wrote are sent once more after `ART_SETTLE`, without a delete: tmux drops a pane's passthrough while it redraws a client, the program cannot tell, and `sent` would otherwise keep the lost image as sent for the rest of the run. Only the images whose cells are still the ones in `sent` are resent, `n` / `N` before the due time does not cancel it, and leaving the page does. This covers only that moment; an image lost at another time still needs the page reopened. What the user sees: a banner left blank when the member finishes is filled in about a second later.

## HP / SP bars

Each bar is the label and number text with a colored underline (`SGR 4` + `SGR 58` underline color):
the first part in the bar color, the rest dim. tmux forwards underline colors only when the terminal declares the
`usstyle` feature, which `party.tmux` adds for Ghostty and Kitty.

## Classes and crests

A member's class (portrait) comes from a hash of its session id, and a squad's crest from a hash of the session
name. `spread()` assigns them so that up to 8 members of one squad (or 8 squads) never share one.
Renaming a window does not change them.
