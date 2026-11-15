import builtins
import json
import os
import time
from datetime import datetime, timezone

import pytest

from party_hud import claude_log, codex_log, collect, processes


def write(folder, name, *lines):
    path = os.path.join(folder, name)
    with open(path, "w") as f:
        f.write("".join(lines))
    return path


def um(tid, t):
    item = {"type": "UserMessage", "content": [{"type": "text", "text": t}]}
    return json.dumps({"type": "event_msg", "payload": {"type": "item_completed", "turn_id": tid, "item": item}}) + "\n"


def ce(tid):
    item = {"type": "CommandExecution"}
    return json.dumps({"type": "event_msg", "payload": {"type": "item_completed", "turn_id": tid, "item": item}}) + "\n"


def ts(tid):
    return json.dumps({"type": "event_msg", "payload": {"type": "task_started", "turn_id": tid}}) + "\n"


def fc(tid, name, inp):
    return (
        json.dumps({"type": "response_item", "payload": {"type": "custom_tool_call", "name": name, "input": inp}})
        + "\n"
    )


def am(tid, t):
    item = {"type": "AgentMessage", "content": [{"type": "Text", "text": t}]}
    return json.dumps({"type": "event_msg", "payload": {"type": "item_completed", "turn_id": tid, "item": item}}) + "\n"


def rollout(folder, name, *events):
    return write(folder, name, *(json.dumps({"type": "event_msg", "payload": {"type": e}}) + "\n" for e in events))


NULL_ANSWER = '{"type":"event_msg","payload":{"type":"task_complete","last_agent_message":null}}\n'


def test_usage_is_the_last_token_count_with_info(tmp_path):
    path = write(
        tmp_path,
        "r.jsonl",
        '{"type":"session_meta","payload":{}}\n',
        '{"type":"event_msg","payload":{"type":"token_count","info":null}}\n',
        '{"type":"event_msg","payload":{"type":"token_count","info":{"last_token_usage":{"total_tokens":18981},'
        '"model_context_window":258400}}}\n',
        '{"type":"event_msg","payload":{"type":"token_count","info":null}}\n',
    )
    assert codex_log.codex_usage(path) == (18981, 258400)
    assert codex_log.codex_usage("/nope") is None


def test_report_is_the_last_task_complete(tmp_path):
    path = write(
        tmp_path,
        "r.jsonl",
        '{"type":"event_msg","payload":{"type":"task_complete","last_agent_message":"old","started_at":1,"completed_at":2}}\n',
        '{"type":"event_msg","payload":{"type":"task_complete","last_agent_message":"## 結果\\n完成","started_at":100,'
        '"completed_at":160,"duration_ms":60000}}\n',
        '{"type":"event_msg","payload":{"type":"token_count","info":null}}\n',
    )
    assert codex_log.codex_report(path) == {"text": "## 結果\n完成", "start": 100, "end": 160}


def test_report_without_message_or_file_is_none(tmp_path):
    path = write(tmp_path, "r.jsonl", NULL_ANSWER)
    assert codex_log.codex_report(path) is None
    assert codex_log.codex_report("/nope") is None


def test_task_is_the_finished_turns_ask_and_command_count(tmp_path):
    path = write(
        tmp_path,
        "r.jsonl",
        ts("t1") + um("t1", "old ask") + ce("t1") + ts("t2") + um("t2", " new ask ") + ce("t2") + ce("t2"),
        '{"type":"event_msg","payload":{"type":"task_complete","turn_id":"t2","last_agent_message":"x","started_at":1,"completed_at":2}}\n',
    )
    assert codex_log.codex_task(path) == {"ask": "new ask", "files": 0, "cmds": 2, "agents": 0}
    assert codex_log.codex_task("/nope") is None


def test_task_started_before_the_tail_is_none(tmp_path):
    path = write(
        tmp_path,
        "r.jsonl",
        ts("t9") + um("t9", "long turn") + ce("t9") + ("x" * 1000 + "\n") * 300 + ce("t9") + ce("t9"),
        '{"type":"event_msg","payload":{"type":"task_complete","turn_id":"t9","last_agent_message":"x","started_at":1,"completed_at":2}}\n',
    )
    assert codex_log.codex_task(path) is None


def test_live_turn_has_ask_start_tool_said_and_previous_report(tmp_path):
    path = write(
        tmp_path,
        "r.jsonl",
        ts("t1") + um("t1", "old ask"),
        '{"type":"event_msg","payload":{"type":"task_complete","turn_id":"t1","last_agent_message":"earlier answer","started_at":10,"completed_at":20}}\n',
        '{"type":"event_msg","payload":{"type":"task_started","turn_id":"t2","started_at":500}}\n',
        um("t2", "now ask")
        + fc("t2", "exec", "\nrg -n foo src\nmore")
        + ce("t2")
        + am("t2", "a\nb\nc")
        + fc("t2", "exec", "ls -la"),
    )
    cl = codex_log.codex_live(path)
    assert cl == {
        "live": True,
        "task": {"ask": "now ask", "files": 0, "cmds": 1, "agents": 0},
        "start": 500,
        "end": None,
        "tool": "exec: ls -la",
        "said": "a\nb\nc",
        "prev": {"text": "earlier answer", "start": 10, "end": 20},
    }


def test_live_is_none_after_task_complete_or_without_file(tmp_path):
    path = write(tmp_path, "r.jsonl", NULL_ANSWER)
    assert codex_log.codex_live(path) is None
    assert codex_log.codex_live("/nope") is None


def test_turn_done_only_when_the_newest_turn_event_is_task_complete(tmp_path):
    done_f = rollout(tmp_path, "done.jsonl", "task_started", "task_complete")
    started_f = rollout(tmp_path, "started.jsonl", "task_complete", "task_started")
    empty_f = rollout(tmp_path, "empty.jsonl", "token_count")
    assert codex_log.codex_turn_done(done_f)
    assert not codex_log.codex_turn_done(started_f)
    assert not codex_log.codex_turn_done(empty_f)
    assert not codex_log.codex_turn_done("/nope")


@pytest.fixture
def rolls(tmp_path):
    """roll(name, cwd, age, ts) writes a rollout in today's date folder under root; returns (root, now_, roll)."""
    root = str(tmp_path)
    now_ = time.time()
    day = os.path.join(root, f"{datetime.now():%Y/%m/%d}")
    os.makedirs(day)

    def roll(name, cwd, age, ts=None):
        p = os.path.join(day, f"rollout-{name}.jsonl")
        stamp = {}
        if ts is not None:
            stamp = {
                "timestamp": datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")
                if isinstance(ts, float)
                else ts
            }
        with open(p, "w") as f:
            f.write(json.dumps({"type": "session_meta", "payload": {"cwd": cwd, **stamp}}) + "\n")
        os.utime(p, (now_ - age, now_ - age))
        return p

    return root, now_, roll


def test_newest_rollout_after_start_in_the_same_cwd(rolls):
    root, now_, roll = rolls
    roll("old", "/w/a", 600)
    new_a = roll("new", "/w/a", 5)
    roll("other", "/w/b", 1)
    assert codex_log.newest_rollout("/w/a", now_ - 60, root) == new_a
    assert codex_log.newest_rollout("/w/a", now_ - 3, root) is None
    assert codex_log.newest_rollout("/w/c", now_ - 60, root) is None


def test_broken_or_missing_timestamp_counts_for_newest_but_not_pairing(rolls):
    root, now_, roll = rolls
    roll("bad-ts", "/w/e", 5, "not a time")
    num_ts = roll("num-ts", "/w/e", 4, 12345)
    no_ts = roll("no-ts", "/w/e", 3)
    first = codex_log.newest_rollout("/w/e", now_ - 60, root)
    os.utime(no_ts, (now_ - 30, now_ - 30))
    assert first == no_ts
    assert codex_log.newest_rollout("/w/e", now_ - 60, root) == num_ts
    assert codex_log.paired_rollout("/w/e", now_ - 60, [now_ - 50], root) is None


def test_same_cwd_processes_take_rollouts_one_to_one(rolls):
    root, now_, roll = rolls
    ra = roll("pair-a", "/w/p", 20, now_ - 50.0)
    rb = roll("pair-b", "/w/p", 5, now_ - 40.0)
    assert codex_log.paired_rollout("/w/p", now_ - 110, [now_ - 60], root) == ra
    assert codex_log.paired_rollout("/w/p", now_ - 60, [now_ - 110], root) == rb
    assert codex_log.paired_rollout("/w/p", now_ - 110, [now_ - 60, now_ - 10], root) == ra
    assert codex_log.paired_rollout("/w/p", now_ - 10, [now_ - 110, now_ - 60], root) is None


@pytest.fixture
def paired(rolls, monkeypatch):
    """Two codex processes (pids 10 and 20) in /w/p and their rollouts; process lookups are fakes."""
    root, now_, roll = rolls
    ra = roll("pair-a", "/w/p", 20, now_ - 50.0)
    rb = roll("pair-b", "/w/p", 5, now_ - 40.0)
    procs = {"10": ["codex"], "20": ["codex"]}
    starts = {"10": now_ - 110, "20": now_ - 60}
    since, real_glob = codex_log.rollouts_since, codex_log.glob.glob
    monkeypatch.setattr(processes, "proc_args", lambda pid: procs.get(str(pid)))
    monkeypatch.setattr(processes, "proc_children", lambda pid: [])
    monkeypatch.setattr(processes, "proc_start", lambda pid: starts.get(str(pid)))
    monkeypatch.setattr(codex_log, "rollouts_since", lambda c, s, r=None: since(c, s, root))
    monkeypatch.setattr(codex_log.glob, "glob", lambda pat: [] if pat.startswith("/proc/") else real_glob(pat))
    return ra, rb, procs


def test_codex_rollout_gives_same_cwd_panes_their_own_rollouts(paired):
    ra, rb, _ = paired
    both = [{"pane_pid": "10", "pane_current_path": "/w/p"}, {"pane_pid": "20", "pane_current_path": "/w/p"}]
    got = [codex_log.codex_rollout(pp, "/w/p", both) for pp in ("10", "20")]
    solo = codex_log.codex_rollout("10", "/w/p", both[:1])
    assert got == [ra, rb]
    assert solo == rb


def test_codex_process_matched_by_program_name(paired):
    _, _, procs = paired
    cprocs = {
        "30": ["bash", "/tmp/codex-notes.sh"],
        "31": ["vim", "codex.md"],
        "32": ["/x/bin/codex"],
        "33": ["node", "/x/bin/codex.js"],
    }
    procs.update(cprocs)
    assert [bool(codex_log.is_codex_proc(cprocs[k])) for k in ("30", "31", "32", "33")] == [False, False, True, True]
    assert codex_log.find_codex("30") is None
    assert codex_log.find_codex("33") == "33"


def test_collect_and_report_pair_the_same_rollouts(paired, monkeypatch):
    ra, rb, _ = paired
    fields = {f: "" for f in collect.TMUX_FIELDS}
    tpanes = [
        dict(
            fields,
            pane_id=f"%{i}",
            pane_pid=pp,
            pane_current_path="/w/p",
            pane_current_command="codex",
            session_name="s",
            session_attached="1",
            window_active="1",
            window_id="@1",
            window_panes="2",
        )
        for i, pp in ((1, "10"), (2, "20"))
    ]
    seen = []
    real = codex_log.codex_rollout
    monkeypatch.setattr(collect, "read_tmux", lambda: tpanes)
    monkeypatch.setattr(claude_log, "read_claude_sessions", dict)
    monkeypatch.setattr(collect, "screen_changed", lambda ps, now: {})
    monkeypatch.setattr(codex_log, "codex_rollout", lambda *a: seen.append(real(*a)) or seen[-1])
    collect.collect()
    from_collect, seen[:] = list(seen), []
    for i in (1, 2):
        collect.report_for({"kind": "codex", "pane": f"%{i}"})
    assert from_collect == [ra, rb]
    assert seen == [ra, rb]


def put(path, text):
    with open(path, "w") as f:
        f.write(text)


@pytest.fixture
def roll(tmp_path):
    return str(tmp_path / "r.jsonl")


def test_tail_unchanged_file_is_not_opened_again(roll, monkeypatch):
    opened = []
    real_open = open

    def spy_open(file, *a, **k):
        if file == roll:
            opened.append(file)
        return real_open(file, *a, **k)

    put(roll, "a\nb\n")
    monkeypatch.setattr(builtins, "open", spy_open)
    first = codex_log._tail_lines(roll)
    second = codex_log._tail_lines(roll)
    assert first == [b"a", b"b"]
    assert second == first
    assert len(opened) == 1
    assert second is not first


def test_tail_caller_changing_the_list_does_not_change_the_memory(roll):
    put(roll, "a\nb\n")
    codex_log._tail_lines(roll).append(b"x")
    assert codex_log._tail_lines(roll) == [b"a", b"b"]


def test_tail_appended_line_is_read(roll):
    put(roll, "a\nb\n")
    codex_log._tail_lines(roll)
    with open(roll, "a") as f:
        f.write("c\n")
    assert codex_log._tail_lines(roll) == [b"a", b"b", b"c"]


def test_tail_same_size_newer_mtime_is_read(roll):
    put(roll, "a\nb\nc\n")
    codex_log._tail_lines(roll)
    st = os.stat(roll)
    put(roll, "a\nb\nZ\n")
    os.utime(roll, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert codex_log._tail_lines(roll) == [b"a", b"b", b"Z"]


def test_tail_deleted_file_gives_no_lines(roll):
    put(roll, "a\n")
    codex_log._tail_lines(roll)
    os.remove(roll)
    assert codex_log._tail_lines(roll) == []


def test_tail_recreated_file_is_read(roll):
    put(roll, "a\n")
    codex_log._tail_lines(roll)
    os.remove(roll)
    codex_log._tail_lines(roll)
    put(roll, "new\n")
    assert codex_log._tail_lines(roll) == [b"new"]


def test_tail_truncated_file_is_read(roll):
    put(roll, "new\n")
    codex_log._tail_lines(roll)
    put(roll, "n\n")
    assert codex_log._tail_lines(roll) == [b"n"]


def test_tail_different_file_of_the_same_size_and_mtime_is_read(roll, tmp_path):
    put(roll, "n\n")
    codex_log._tail_lines(roll)
    st = os.stat(roll)
    other = str(tmp_path / "o.jsonl")
    put(other, "m\n")
    os.utime(other, ns=(st.st_atime_ns, st.st_mtime_ns))
    os.replace(other, roll)
    st2 = os.stat(roll)
    assert st2.st_size == st.st_size
    assert st2.st_mtime_ns == st.st_mtime_ns
    assert st2.st_ino != st.st_ino
    assert codex_log._tail_lines(roll) == [b"m"]


def test_tail_memory_is_capped_and_drops_the_oldest(roll):
    put(roll, "m\n")
    for i in range(codex_log.TAIL_MEMO_MAX + 3):
        codex_log._tail_lines(roll, 1000 + i)
    assert len(codex_log._tail_memo) == codex_log.TAIL_MEMO_MAX
    assert (roll, 1000) not in codex_log._tail_memo
