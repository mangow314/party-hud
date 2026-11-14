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

## Batches

Counts are bash `ok(` / `check` calls in that range, measured on the pilot branch.

| # | Batch | Source in `party-test.sh` | New file | Asserts |
|---|---|---|---|---|
| 0 | Markdown (pilot, done) | wrap, wrap_sgr, render_markdown | `test_markdown.py` | 41 tests |
| 1 | Collector readers | claude report/task/typed/live, codex rollout/report/task/live, `ps` parsing, without `/proc` (≈1214-1555, 1863-1940, 2086-2115) | `test_claude_log.py`, `test_codex_log.py`, `test_processes.py` | 64 |
| 2 | Collect and snapshot | screen diff, unseen/round, bells, snapshot lock, list-panes (≈1556-1668, 1806-1862, 1941-1968, 2428-2501) | `test_collect.py` | 59 |
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
