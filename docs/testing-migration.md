# Moving the unit tests to pytest

`tests/party-test.sh` (about 3330 lines) is being moved to `tests/test_*.py`, one batch per PR. Delete this file when
the last batch lands.

## Why

- No per-test filter: a single failing assert means rerunning the whole file, and one heredoc of 2385 lines
  (`ui_ok`) reports as one check.
- Monkeypatches are restored by hand (`real_cr = ...; ...; collect.claude_report = real_cr`); a missed restore leaks
  into every later assert. pytest's `monkeypatch` restores on its own.
- Asserts in the big heredoc share state from earlier lines, so one cannot be read or run on its own.

## Rules for every batch

- Runtime stays stdlib only. pytest is a test tool, pinned like ruff: `uvx pytest@9.2.0` locally, `pip install
  pytest==9.2.0` in CI. No project venv (a `.venv` makes basedpyright resolve `scripts/` imports from it and fail on
  Pillow/NumPy).
- One assert in bash becomes one test function (or one `parametrize` case); the bash message becomes its name. Keep
  every condition of the original assert; split an `and` chain into separate `assert` lines.
- Replace a function in the module that defines it (`monkeypatch.setattr(claude_log, "claude_report", ...)`), as
  CLAUDE.md requires for collector modules.
- State a test needs is built by a fixture in that test, not taken from an earlier test. When an old assert relied on
  earlier lines, rebuild that state in a fixture and say so in the PR.
- The same PR deletes the moved lines from `party-test.sh`; nothing is tested twice and nothing is dropped.
- Spot-check the new tests with three hand mutations of the module under test (as the pilot did for `markdown.py`):
  each mutation must fail at least one test.

## Shared pieces (first batch that needs them adds them)

- `tests/conftest.py`: sets `XDG_RUNTIME_DIR` and `XDG_STATE_HOME` to a temp folder before `party_hud` is imported
  (`common.PARTY_DIR` is computed at import) and `LC_COLLATE=C`.
- `tests/fixtures/sidebar.json`: the two-squad fixture, read by `test_render_sidebar.py` and by `party-test.sh`.
- `tests/screen.py`: `strip` (ANSI escapes), `width` (CJK = 2, combining = 0), `widths_ok` (every box line exactly
  33 columns) and `has_line` (a `grep -E` on one line). Test modules import it like `records.py`, not from
  `conftest.py`.
- An autouse fixture in `conftest.py` clears the module-level memos between tests: `claude_log._long_turns`,
  `_cache_memo`, `_transcript_memo`, `codex_log._tail_memo`, `_rollout_meta`, `processes._ps_memo`. In bash they
  carried over from one assert to the next; a test that checks a memo builds it up inside that one test.
- `tests/records.py`: plain helpers that write Claude transcripts to `tmp_path` (`rec`, `text`, `transcript`, `bulk`,
  `turn()`, `live_turn()`). `pytest.ini_options.pythonpath` gets `"tests"` so test files import it. Codex rollout
  event helpers live in `test_codex_log.py`, their only user.

## Batches

Line ranges are approximate: assert topics are interleaved, so a batch picks its asserts by the message prefix (the
text before the first `:`), not by line number. Ranges and counts for batches 2-10 were measured before batch 1
removed 441 lines (from about line 1237 on); batches 2-8 and the pty batch removed 274, 214, 247, 274, 313, 379, 276 and 273 more. They are only a guide;
each batch recounts by prefix when it starts.

| # | Batch | Source in `party-test.sh` | New file | Asserts |
|---|---|---|---|---|
| 0 | Markdown (pilot, done) | wrap, wrap_sgr, render_markdown | `test_markdown.py` | 41 tests |
| 1 | Collector readers (done) | see "Batch 1" below | `test_claude_log.py`, `test_codex_log.py`, `test_processes.py`, `test_report_for.py` | 63 |
| 2 | Collect and snapshot (done) | see "Batch 2" below | `test_collect.py`, `test_codex_log.py` | 53 |
| 3 | `--report-text` (done) | see "Batch 3" below | `test_report_text.py` | 37 |
| 4 | Sidebar rendering (done) | see "Batch 4" below | `test_render_sidebar.py` | 70 |
| 5 | Report page (done) | see "Batch 5" below | `test_render_report.py` | 74 |
| 6 | Select screen (done) | see "Batch 6" below | `test_render_select.py` | 45 |
| 7 | Panes and keys (done) | see "Batch 7" below | `test_ui.py`, `test_sidebars.py` | 96 |
| 8 | Art and images (done) | see "Batch 8" below | `test_art.py`, `test_animation.py`, `test_render_select.py` | 54 |
| 8b | Report pane on a pty (done) | see "Pty batch" below | `test_report_pane.py` | 46 |
| 9 | Crew sub-commands | `summon_ok`, `dismiss_ok`, `crew_ok` (2718-3047) | `test_crew.py` | 67 |
| 10 | The rest | transcript TTL, statusline script, `cw`, imports per sub-command, `leave_without_teardown` (3048-3330) | `test_common.py`, `test_party_cli.py` | 18 |
| 11 | Remove bash runner | delete `party-test.sh`, its CI step and this file; update CLAUDE.md and CONTRIBUTING | | |

Batches 1-3 first: they are the code the split into `claude_log` / `codex_log` / `processes` was for, and they need
`monkeypatch` most. Batches 4-10 can go in any order. `tests/party-tmux-test.sh` (real tmux) stays bash; moving it to a
`@pytest.mark.tmux` test that skips without tmux is a separate decision after batch 11.

## Batch 1: collector readers (done)

63 bash asserts became 65 tests (two asserts that looped over agy and grok are `parametrize` cases), found by message
prefix: `claude live` 11, `screen report` 8, `subagents` / `subagent report` 8, `codex rollout` / `codex_rollout` 6,
`claude report` 5, `claude typed` 5, `claude task` 3, `report_for` 3, `codex report` / `codex task` / `codex live` 2
each, `git branch` 2, `Wrappers` 2, and one each for `codex turn done`, `codex process`, `claude session`,
`Recognizes claude / agy / grok`, `Plain node`, `ps parsing`, `Without /proc`, `Process alive`.

| File | Module under test | Asserts |
|---|---|---|
| `test_claude_log.py` | `claude_log` (report, task, typed, live, subagents, session) and `report_for` on Claude | 31 |
| `test_codex_log.py` | `codex_log`: usage, report, task, live, turn done, rollout pairing, process match | 14 |
| `test_processes.py` | `processes` and `collect.agent_kind`: `ps` parsing, without `/proc`, alive check, wrappers | 7 |
| `test_report_for.py` | `collect.git_branch` and agy / grok reports read off the screen | 11 |

How the shared state was untangled:

- `claude live` long-turn asserts read one log again and again. Each became its own test that replays the reads it
  depends on; a `searches` fixture spies on `_search_long_turn` through `monkeypatch`.
- `report_for` and `subagents` asserts reused `turn`, `liveq` and the `sess` folder; fixtures build them per test
  with `records.py` in `tmp_path`.
- `collect.tmux`, `HAVE_PROC`, `_ps_memo`, the `proc_*` functions, `rollouts_since`, `glob.glob` and
  `LONG_TURN_LOOKBACK` are replaced with `monkeypatch` in their defining modules.
- `test_claude_log.py` and `test_report_for.py` turn off basedpyright's Optional checks at the top of the file: the
  tests index results they expect to exist, and a `None` there fails the test anyway.

## Batch 2: collect and snapshot (done)

53 bash asserts became 53 tests: `collect.collect` on a fixture (fresh Claude, report pane, other agents, sessions
status against workmux icons, codex HP, a stale pane state file) 10, `Screen diff` 1, agy / codex permission prompts 8,
`codex:` turn status and rounds 5, unseen / `Round` / `Seen` 13, `Bell`, `Tidy` and the two collector `crew done`
asserts 4, `No snapshot`, `list-panes` and `printable` 3, and the codex rollout tail memo 9 (in `test_codex_log.py`, its
module). The `crew done` asserts on `ui` and `render`, `SP = cache minutes`, and the cursor `follow_here` asserts stay
for batches 4 and 7.

- An autouse fixture in `test_collect.py` points `collect.PARTY_DIR` and `sidebars.PARTY_DIR` at `tmp_path`; bash set
  them with `tempfile.mkdtemp()` and left them for later lines.
- `collect.read_tmux`, `collect.tmux`, `collect.screen_changed`, `claude_log.read_claude_sessions`,
  `codex_log.codex_rollout`, `collect.collect` and `builtins.open` are replaced with `monkeypatch`.
- Rollout tail asserts read one file in sequence; each test replays the writes and reads it depends on.

## Batch 3: `--report-text` (done)

The `report_text_ok` heredoc (37 asserts, two of them in a loop over the two outputs tmux gives for a missing pane)
became 39 tests in `test_report_text.py`: `collect.report_text` exit codes, `--wait`, `--after` and the
waiting-for-input screen tail 27, `party.ask` 9, `common.tmux_run`'s timeout 1, and the collector's `wait-for -S` and
`@party_reports` 2. The bash count drops by 39 lines: 37 `ok(` calls, the heredoc's `def ok(` and its `check` line.

- The `run` / `run_after` / `run_waiting` helpers, which reset shared `calls` and `snaps` lists, are methods of a
  `Fake` built per test by the `fk` fixture; `collect.get_snapshot`, `tmux_run`, `report_for`,
  `claude_log.claude_report`, `party.get_snapshot`, `party.tmux_run` and `party.subprocess.run` go through
  `monkeypatch`.
- The collector asserts ran the real `get_snapshot` in the shared state folder; a fixture points `collect.PARTY_DIR`
  at `tmp_path`, so each starts with no `bells.json`.
- The file turns off basedpyright's `reportArgumentType`: `report_text`'s `timeout` is inferred as `int` from its
  default, and the tests pass a float as `--timeout` does.

## Batch 4: sidebar rendering (done)

70 bash asserts became 76 tests in `test_render_sidebar.py` (three that looped over art on / off and one over four
squad / art cases are `parametrize` cases): the 26 top-level `check` lines on the `--fixture` output and the selected
%4 / empty squad renders, and 44 `ok(` calls in `ui_ok` on `render.render`, `render.card`, `stat_rows`, `meter_row`,
`model_badge`, `squad_summary`, `squad_alert`, `sp_points` and the render row map: peek, key hints, empty squads,
cards without SP, art cards and squad rows, narrow widths, HP colours, crowded sidebars and the `UI text is all
English` check.

The prefix ranges in the table above did not hold: they also covered keys, mouse input, `--restore-*`, report and
select asserts. Those stay for batches 5-8, as do `Portrait chosen by class`, `Classes`, `Class icon fixed`, and the
`ui` asserts on `crew done`.

- `party.py --fixture` runs once per module in a subprocess, as the bash `check` lines ran it.
- `render._tick` is set with `monkeypatch`; bash set it by hand and reset it to 0.
- `party-test.sh` reads the fixture from `tests/fixtures/sidebar.json` instead of writing it to `$tmp`; `ui_ok` gets
  `$tmp` as a third argument for its cursor file, which used to sit next to the fixture.

## Batch 5: report page (done)

74 bash asserts at the top of `ui_ok` became 76 tests in `test_render_report.py` (the markdown cache assert looped
over three reports and is a `parametrize` case): `render.render_report` and `report_side_rows` (narrow and split
pages, side column, banners, WHERE and FILES rows), `report_rows` for the last output, `collect.home_path`,
`render.where_rows`, `render_no_report`, `ui.banner_cells`, `ui.report_images` / `report_first_deletes`,
`ui.portrait_cells`, `report_resize_wait`, `report_peek` and `report_queue`.

Left in bash: `select banner: still at most 10 rows` (batch 6) and `r in the sidebar opens the report pane` (batch 7).
The `report pane:` asserts that drive the pane through a pty stay too; they need their own batch.

- Inputs shared by many asserts (`done`, `rep`, `sub`, `busy`, `task_l`, `many`) are module constants; the pages
  built from them (`frame`, `wide`, `side`, the fake art files) are fixtures.
- The bash loop over the markdown cache cases rebound `rep` to its last case, and later asserts in `ui_ok` read
  that value. `ui_ok` now sets `rep` to that case directly, so those asserts see the same input.
- `HOME` is set with `monkeypatch.setenv`; bash set `os.environ["HOME"]` for the rest of the heredoc.

## Batch 6: select screen (done)

45 bash asserts in `ui_ok` became 45 tests in `test_render_select.py`: `ui.select_key`, `ui.select_banner`,
`render.select_roster`, `render_select`, `select_preview`, `select_summary`, `select_crew_line`, `select_row`,
`ui.select_image_plan` / `select_images_out`, `select_reread`, and the time ticks (`tick_wait`, `time_anchor`,
`select_wait`, `select_phase`) with their simulated clocks.

Left in bash: `--menu` and `r: the report opens beside the sidebar's own window` (tmux pane opening, batch 7), and
the `live page re-read` assert (with the pty `report pane:` asserts).

- The roster fixtures (`st`, `sst`, `srs`, `srep`) are module constants; `srows_of` is a module function.
- The preview layout count replaces `markdown.md_rows` / `md_table` with `monkeypatch` instead of by hand.
- The clock simulations are copied as they were, with two lint changes: `itertools.pairwise` for successive pairs
  and default arguments for the loop variables their lambdas read (each lambda is called inside its own loop pass,
  so the values are the same).
- `ui_ok` keeps `mm`, `mt`, `sm`, `sst`, `srs`, `srep`, `PH` and `srows_of`: the `--menu` and pty asserts read them.

## Batch 7: panes and keys (done)

96 bash asserts in `ui_ok` became 106 tests (loops over usage strings, cell ratios and heights are `parametrize`
cases):

- `test_sidebars.py` (42): `open_report_pane` on tmux with and without `new-pane`, pane widths and spans,
  `fit_report_pane`, banner sizes at those widths, `tidy`, `remember_width`, `nudge`, `restore_begin` /
  `restore_end` / `ensure`.
- `test_ui.py` (64): `--menu` (`open_select`, `run_menu`), `open_report`, `refresh_live`, `follow_here`,
  `next_waiting`, `report_queue` on crew, `parse_input`, `handle_key`, `report_scroll` / `report_step`, the report
  left column and `report_view`, key help and its overlay, `point_at`, the shared cursor file and the class icon.

Left in bash: the pty `report pane:` / `select screen:` asserts and the art, image and animation asserts (batch 8).

- `ui_ok` changed `towns` in place for the cursor asserts (every member in its own window, then %1 and %2 sharing
  one) and every later key assert ran on that; the `windowed` fixture rebuilds that state.
- The sequential `point_at` and `follow_here` calls are replayed by fixtures that record the cursor after each step.
- `sidebars.tmux`, `sidebars._new_pane`, `ui.tmux`, `ui.get_snapshot`, `ui.run_*`, `common.CURSOR` and
  `TMUX_PANE` go through `monkeypatch`; bash restored some by hand and left `_new_pane` at `None`.

## Batch 8: art, images and animations (done)

54 bash asserts at the end of `ui_ok` became 55 tests (the squad flash assert looped over art on / off):

- `test_art.py` (17): `load_art` with no, all and one missing image, image files read only when sent, image ids,
  `art_supported`, placeholders and diacritics, `kitty_image` / `kitty_delete`, crests, portraits and classes.
- `test_animation.py` (26): `report_frames`, `report_anim_enabled`, `ui.animate` (change labels, flashes), the flash
  in `render.render` / `render.card`, and change labels on stat rows and cards.
- `test_render_select.py` (+12): select screen images and banners (`select_image_plan`, `select_images_due`,
  `select_images_out`, `select_title_plan`, `select_banner`), cards built once a frame, and the art / text cards.

`ui_ok` now holds only the pty-driven `report pane:` / `select screen:` asserts; the definitions that only the moved
asserts read (`done`, `rep`, `mk`, `mm`, `mt`, `sm`, `sst`, `srs`, `srep`, `PH`, `srows_of`, `png`, `empty`) are
gone with them.

- `art.ART_DIR`, `common.PARTY_DIR` / `ERROR_LOG`, `builtins.open`, `render.card` and `TMUX` go through
  `monkeypatch`; the image files are written to `tmp_path` per test.
- The unreadable-image assert caught any exception to check that none was raised; the test calls `send_image`
  directly, so an exception fails it.

## Pty batch: report pane and select screen on a pty (done)

46 bash asserts, the whole rest of `ui_ok`, became 47 tests in `test_report_pane.py` (the running-time assert looped
over two phases). `ui_ok` and its `check` line are gone, so the bash count dropped by 48: the 46 asserts, `def ok(`
and `check`.

- `report_session` is a module function; the child gets the repo and fixture paths from `ROOT` / `FIXTURE`.
- A session read by several tests (`once`, `twice`, the resize burst, the select screen) runs once per module.
- Bash shared one `seen.json` and removed it between sessions; each session that reads it now gets its own
  `XDG_RUNTIME_DIR` under `tmp_path`, so no test depends on the order.

## Gates

| Phase | Gate (machine-checked) |
|---|---|
| Each batch 1-10 | `ruff check . && ruff format --check . && basedpyright . && uvx pytest@9.2.0 && bash tests/party-test.sh` passes, `grep -c FAIL` is 0 |
| Each batch 1-10 | new pytest count minus old ≥ asserts removed from bash (an `and` chain may become several tests, never fewer) |
| Each batch 1-10 | `grep -cE 'ok\(|^check ' tests/party-test.sh` drops by exactly the batch's asserts |
| Each batch 1-10 | three hand mutations of the module under test each fail ≥ 1 new test |
| Each batch 1-10 | CI green on `ubuntu-latest` (3.10, 3.12, 3.14) and `macos-latest` |
| Batch 11 | `test ! -e tests/party-test.sh`, and no file mentions it: `rg -l party-test.sh` is empty |

## Optional later

- `hypothesis` for the width rule (every card line exactly the drawable width, CJK = 2, combining = 0) on random
  names and reports.
- `mutmut` on `markdown.py` and `render.py`, run by hand, not in CI.
