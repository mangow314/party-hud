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
  (`common.PARTY_DIR` is computed at import), `LC_COLLATE=C`, and the `strip` helper for ANSI escapes.
- `tests/fixtures/sidebar.json`: the fixture now written inline at the top of `party-test.sh` (lines 27-50).
- `widths_ok` (every box line exactly 33 columns) becomes a helper in `conftest.py`.
- An autouse fixture in `conftest.py` clears the module-level memos between tests: `claude_log._long_turns`,
  `_cache_memo`, `_transcript_memo`, `codex_log._tail_memo`, `_rollout_meta`, `processes._ps_memo`. In bash they
  carried over from one assert to the next; a test that checks a memo builds it up inside that one test.
- `tests/records.py`: plain helpers that write Claude transcripts to `tmp_path` (`rec`, `text`, `transcript`, `bulk`,
  `turn()`, `live_turn()`). `pytest.ini_options.pythonpath` gets `"tests"` so test files import it. Codex rollout
  event helpers live in `test_codex_log.py`, their only user.

## Batches

Line ranges are approximate: assert topics are interleaved, so a batch picks its asserts by the message prefix (the
text before the first `:`), not by line number. Ranges and counts for batches 2-10 were measured before batch 1
removed 441 lines (from about line 1237 on) and batch 2 removed 274 more, so they are only a guide; each batch recounts
by prefix when it starts.

| # | Batch | Source in `party-test.sh` | New file | Asserts |
|---|---|---|---|---|
| 0 | Markdown (pilot, done) | wrap, wrap_sgr, render_markdown | `test_markdown.py` | 41 tests |
| 1 | Collector readers (done) | see "Batch 1" below | `test_claude_log.py`, `test_codex_log.py`, `test_processes.py`, `test_report_for.py` | 63 |
| 2 | Collect and snapshot (done) | see "Batch 2" below | `test_collect.py`, `test_codex_log.py` | 53 |
| 3 | `--report-text` | `report_text_ok` heredoc (2505-2717) | `test_report_text.py` | 39 |
| 4 | Sidebar rendering | fixture cards and widths (52-113), squads, peek, fit (117-170, 2116-2163, 2333-2427) | `test_render_sidebar.py` | 76 |
| 5 | Report page | report rows, live page, banners, queue (171-458) | `test_render_report.py` | 76 |
| 6 | Select screen | roster, cards, preview, time ticks (459-812) | `test_render_select.py` | 48 |
| 7 | Panes and keys | pane widths, fit, open/close, Tidy, key handling (813-1213, 2264-2332) | `test_ui.py`, `test_sidebars.py` | 101 |
| 8 | Art and images | placeholders, uploads, crests, animations, select art (1669-1805, 1969-2085, 2164-2263) | `test_art.py` | 78 |
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
