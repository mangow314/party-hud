"""integrations/claude-statusline.sh: Claude Code's statusline JSON in, party-hud/<pane>.json out, read by collect."""

import json
import os
import shutil
import subprocess

import pytest

from party_hud import collect

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "integrations", "claude-statusline.sh")
STATUS = {
    "session_id": "abc-1",
    "context_window": {"used_percentage": 12.4, "context_window_size": 1000000},
    "transcript_path": "/p/abc-1.jsonl",
    "model": {"display_name": "Opus 5.5 (1M context)"},
}

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="the script does nothing without jq")


def statusline(text, runtime, pane):
    env = dict(os.environ, XDG_RUNTIME_DIR=str(runtime), TMUX_PANE=pane)
    return subprocess.run([SCRIPT], input=text, capture_output=True, text=True, env=env, check=True)


def test_statusline_writes_session_context_left_size_transcript_and_model_base_name(tmp_path, monkeypatch):
    statusline(json.dumps(STATUS), tmp_path, "%7")
    monkeypatch.setattr(collect, "PARTY_DIR", str(tmp_path / "party-hud"))
    d = collect.read_party("%7")
    got = (d["session_id"], d["ctx_left"], d["ctx_size"], d["transcript"], d["model"])
    assert got == ("abc-1", 88, 1000000, "/p/abc-1.jsonl", "Opus 5.5")


@pytest.mark.parametrize(("text", "pane"), [("garbage", "%9"), ("{}", "")], ids=["broken-json", "outside-tmux"])
def test_statusline_prints_nothing_on_broken_json_or_outside_tmux(tmp_path, text, pane):
    r = statusline(text, tmp_path, pane)
    assert (r.stdout, r.stderr) == ("", "")
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []
