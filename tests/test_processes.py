import os
import time

import pytest

from party_hud import collect, processes

PS_OUT = (
    "  100     1 Wed Nov  4 11:46:42 2026 -zsh\n"
    "  200   100 Wed Nov  4 11:50:00 2026 node /opt/homebrew/bin/codex --yolo\n"
    "  300   200 Wed Nov  4 11:50:01 2026 /opt/codex/codex-aarch64\n"
    "garbage line\n"
)


@pytest.fixture
def ak():
    """agent_kind with child command lines from a table instead of the process tree."""
    fake = {
        "7": [["node", "/home/u/.nvm/bin/codex"]],
        "8": [["node", "server.js"]],
        "9": [["codex", "exec", "--json", "hi"]],
        "10": [["/usr/bin/python3.13", "/opt/agy"]],
        "11": [["nvim", "codex"]],
        "12": [
            [
                "/Library/Frameworks/Python.framework/Versions/3.13/Resources/Python.app/Contents/MacOS/Python",
                "/tmp/agy",
            ]
        ],
    }
    return lambda cmd, pid="": collect.agent_kind(cmd, pid, lambda p: fake.get(p, []))


def test_recognizes_claude_agy_grok_and_codex_under_node(ak):
    assert ak("claude") == "claude"
    assert ak("agy") == "agy"
    assert ak("grok") == "grok"
    assert ak("node", "7") == "codex"


def test_plain_node_shells_and_nested_tmux_are_not_members(ak):
    assert ak("node", "8") is None
    assert ak("bash") is None
    assert ak("tmux") is None


def test_wrappers_an_agent_among_child_processes_counts(ak):
    assert ak("python3", "9") == "codex"
    assert ak("bash", "10") == "agy"
    assert ak("bash", "11") is None


def test_wrappers_macos_framework_python_counts(ak):
    assert ak("bash", "12") == "agy"


def test_ps_parsing_pid_parent_arguments_and_start_time():
    tbl = processes.parse_ps(PS_OUT)
    assert set(tbl) == {"100", "200", "300"}
    assert tbl["200"][0] == "100"
    assert tbl["200"][1][:2] == ["node", "/opt/homebrew/bin/codex"]
    assert tbl["300"][2] == time.mktime((2026, 11, 4, 11, 50, 1, 0, 0, -1))


def test_without_proc_codex_under_node_is_recognized_and_start_read_from_ps(monkeypatch):
    tbl = processes.parse_ps(PS_OUT)
    monkeypatch.setattr(processes, "HAVE_PROC", False)
    monkeypatch.setattr(processes, "_ps_memo", [time.time() + 3600, tbl])
    assert collect.agent_kind("node", "100") == "codex"
    assert processes.proc_start("200") == tbl["200"][2]
    assert processes.proc_start("999") is None
    assert processes.proc_children("100") == ["200"]


def test_process_alive_check_without_proc():
    assert processes.proc_alive(os.getpid())
    assert not processes.proc_alive(2**22 + 12345)
    assert not processes.proc_alive("x")
