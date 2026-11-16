# Contributing

Issues and pull requests are welcome, especially support for more agents and terminals.

## Ground rules

- No dependencies: `party.py` and `party_hud/` use only the Python standard library (3.10+). Pillow and NumPy are fine in
  `scripts/art/` and `scripts/screenshot.py`, which users never run.
- Performance matters: the sidebar runs all day. If a change adds work per frame or per collection, include
  `bench/bench.py` numbers before and after (the table covers the sidebar, select screen and report page; the "in use"
  part plays a fixed key script and gives CPU as a share of one core, target under 1 %).
- Read only. party-hud never writes to an agent's files and never sends data anywhere.
- No comments by default; see [Comments](#comments).

## Comments

Code should explain itself through names, small functions and tests, so the default is no comment. Comments go
stale, and a reader who trusts one may skip reading the code it describes.

A comment is allowed only for something the code cannot show:

- Behavior outside this repo that a line depends on or works around: tmux, a terminal, the OS, Python or an agent.
  Example: `# ?7l: no autowrap, so a squeezed pane clips lines instead of wrapping them`.
- A constraint set elsewhere in the code that this line must respect: `# same order as CLASSES`,
  `# kept outside the snapshot: nudge deletes the snapshot on every window switch`.
- The name of an opaque value, such as a Nerd Font code point: `"\U000f03e9",  # md-paw`.
- A lint suppression with its reason: `# noqa: BLE001 <why>`.

A design choice is not one of these. Pin it with a test (`tests/test_ui.py` checks that j / k stop at the ends of
a squad) or write it in `docs/architecture.md`.

Rules for the comments that stay:

- English, one line, says why, never what.
- Change or delete the comment in the same change as the code it explains.
- Do not delete one without checking that the behavior it describes no longer applies; it usually guards a bug
  that the tests cannot reproduce.
- Docstrings only for an interface the name does not make clear: argument meaning, return shape, file formats.

## Tests

```bash
uvx pytest@9.2.0                # unit tests in tests/test_*.py (pytest 9.2.0, same as CI); -k NAME runs one
uvx pytest@9.2.0 -m tmux        # integration tests on a private tmux server (-L party-test), about 60 s
ruff check .                    # ruff 0.17.1 default rules, same as CI (settings: ruff.toml)
ruff format .                   # 120-column lines; CI runs ruff format --check
basedpyright .                  # type check, standard mode (settings: pyrightconfig.json); keep it at 0 errors
```

Unit tests run party-hud against JSON fixtures (`--fixture`), which replace tmux, `/proc` and agent files.
To test a new agent, add its panes and data to a fixture. New unit tests go in `tests/test_*.py`.

The integration tests in `tests/test_tmux.py` (marker `tmux`) are skipped by the default run. They run in file order
on one shared tmux server, each step building on the last, so run them as a whole with `-m tmux`, not one with `-k`.

## Images

See [ASSETS.md](ASSETS.md). To regenerate from scratch, run ComfyUI with the three models listed there and run
all three scripts. To rebuild only `art/`, download `party-hud-raw-art.tar.gz` from a release, extract it with
`tar -xzf party-hud-raw-art.tar.gz -C scripts/art` and skip `generate.py`.

```bash
python3 scripts/art/generate.py        # raw images -> scripts/art/raw/
python3 scripts/art/decor.py           # portraits  -> art/
python3 scripts/art/crest_compose.py   # crests     -> art/
```

New art must be CC0-compatible and must not imitate a specific existing game, character or artist.

## README images

```bash
python3 scripts/screenshot.py scripts/screenshot.json docs/img
```

Writes `docs/img/window.svg`, `card.svg`, `report.svg`, `report-working.svg`, `help.svg`, `banners.svg` and `select.svg` from the fixture (no tmux needed; the report pages come from the `reports` key).
Icons need a Nerd Font: `PARTY_FONT` is a TTF path with `{}` for the style (default
`/usr/share/fonts/MapleMonoNL-NF-CN/MapleMonoNL-NF-CN-{}.ttf`); characters that font lacks (⏎) come from
`PARTY_FALLBACK_FONT` (default `/usr/share/fonts/TTF/JetBrainsMonoNerdFontMono-{}.ttf`).

```bash
python3 scripts/demo.py scripts/demo.json docs/img/demo.svg
```

Writes `docs/img/demo.svg`, the animated demo, from `scripts/demo.json` (a fixture plus a script of steps; the same drawing code, CSS animation inside the SVG, no external tools).
`demo.json` holds `fixture` (the `screenshot.json` format, with its `reports` by name), `screens` (text beside the sidebar
and status line, by name) and `steps`. A step is one screen shown for `dur` seconds; keys not given stay as in the step
before, except `flash`, `reveal` (a step of the report's opening animation) and `set` (a patch of the fixture: `panes` is
merged by pane id, a dict is merged, anything else replaced), which count for their step only. `sidebar: false` draws the
window without the sidebar until set back to true; `view` is `window`, `select` or `report`; `sel` is the sidebar
selection or the select cursor; `report` is the entry of `reports` the select preview or report page shows; `caption` is
`[key, text]`. The fixture's clock runs with the animation, so RUNNING times count up.
In dark mode the images have a transparent background and in light mode a black one; the SVG's own `prefers-color-scheme` rule decides.
