## What and why



## Checklist

- [ ] `ruff check . && ruff format --check . && basedpyright . && uvx pytest@9.2.0` passes
- [ ] `bash tests/party-tmux-test.sh` passes (needs a real tmux)
- [ ] If this adds work per frame or per collection: `python3 bench/bench.py` numbers before and after are below
- [ ] If user-visible behavior changed: both `README.md` and `README.zh-TW.md` are updated
- [ ] No new dependency in `party.py` or `party_hud/`, nothing written to an agent's files, no network use
- [ ] New art (if any) is CC0-compatible, see `ASSETS.md`
