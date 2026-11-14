import os
import tempfile

# party_hud.common reads these at import, so they are set before any test module imports party_hud
_state = tempfile.mkdtemp(prefix="party-pytest-")
os.environ["XDG_RUNTIME_DIR"] = os.path.join(_state, "xdg")
os.environ["XDG_STATE_HOME"] = os.path.join(_state, "state")
os.environ["LC_COLLATE"] = "C"

import pytest

from party_hud import claude_log, codex_log, processes


@pytest.fixture(autouse=True)
def fresh_memos():
    for memo in (
        claude_log._long_turns,
        claude_log._cache_memo,
        claude_log._transcript_memo,
        codex_log._tail_memo,
        codex_log._rollout_meta,
    ):
        memo.clear()
    processes._ps_memo[:] = [0.0, {}]
