# Contributing

Issues and pull requests are welcome, especially support for more agents and terminals.

## Ground rules

- No dependencies: `party.py` and `party_hud/` use only the Python standard library (3.10+). Pillow and NumPy are fine in
  `scripts/art/` and `scripts/screenshot.py`, which users never run.
- Performance matters: the sidebar runs all day. If a change adds work per frame or per collection, include
  `bench/bench.py` numbers before and after.
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

A design choice is not one of these. Pin it with a test (`tests/party-test.sh` checks that j / k stop at the ends of
a squad) or write it in `docs/architecture.md`.

Rules for the comments that stay:

- English, one line, says why, never what.
- Change or delete the comment in the same change as the code it explains.
- Do not delete one without checking that the behavior it describes no longer applies; it usually guards a bug
  that the tests cannot reproduce.
- Docstrings only for an interface the name does not make clear: argument meaning, return shape, file formats.

## Tests

```bash
bash tests/party-test.sh        # unit tests, no tmux needed (about 2 s)
bash tests/party-tmux-test.sh   # integration tests on a private tmux server (-L party-test), about 30 s
ruff check .                    # ruff 0.17.1 default rules, same as CI (settings: ruff.toml)
ruff format .                   # 120-column lines; CI runs ruff format --check
basedpyright .                  # type check, standard mode (settings: pyrightconfig.json); keep it at 0 errors
```

Unit tests run party-hud against JSON fixtures (`--fixture`), which replace tmux, `/proc` and agent files.
To test a new agent, add its panes and data to a fixture.

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

Writes `docs/img/window.svg`, `card.svg`, `report.svg`, `report-working.svg` and `help.svg` from the fixture (no tmux needed; the report pages come from the `reports` key).
