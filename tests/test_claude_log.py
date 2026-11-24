# pyright: reportOptionalSubscript=false, reportOperatorIssue=false
"""Tests index results they expect to exist; a None there fails the test, so the Optional checks are off."""

import json
import os
from datetime import datetime
from functools import partial

import pytest
import records
from records import append, bulk, rec, text

from party_hud import claude_log, collect, common, processes

t0 = records.T0


@pytest.fixture
def transcript(tmp_path):
    return partial(records.transcript, tmp_path)


@pytest.fixture
def turn():
    return records.turn()


@pytest.fixture
def searches(monkeypatch):
    """Offsets _search_long_turn was called with; the search itself still runs."""
    calls = []
    search = claude_log._search_long_turn
    monkeypatch.setattr(claude_log, "_search_long_turn", lambda f, lo: (calls.append(lo), search(f, lo))[1])
    return calls


def edit(t, name, **inp):
    return rec("assistant", t, [{"type": "tool_use", "id": f"u{t}", "name": name, "input": inp}])


def edit_(t, name, **inp):
    return rec("assistant", t, [{"type": "tool_use", "id": "z", "name": name, "input": inp}])


def inj(t, text_, **kw):
    return rec("user", t, text_, **kw)


def pb(body, i="cd54"):
    return f'<pasted_content id="{i}">\n{body}\n</pasted_content id="{i}">'


def test_report_is_the_text_after_the_last_tool_call(transcript, turn):
    r = claude_log.claude_report(transcript(*turn))
    assert r == {"text": "## 結果\nDone\n\nOne more line", "start": t0 + 120, "end": t0 + 420}


def test_report_survives_a_bang_command_after_the_answer(transcript, turn):
    r = claude_log.claude_report(
        transcript(
            *turn, rec("user", 10, "<bash-input>ls</bash-input>"), rec("user", 10, "<bash-stdout>a</bash-stdout>")
        )
    )
    assert r is not None
    assert r["text"].startswith("## 結果")
    assert r["start"] == t0 + 120


def test_report_is_none_while_in_a_tool_call_or_without_file(transcript, turn):
    assert claude_log.claude_report(transcript(*turn[:6])) is None
    assert claude_log.claude_report(transcript(*turn[:7])) is None
    assert claude_log.claude_report("/nope") is None


def test_report_is_none_with_only_thinking_so_far(transcript, turn):
    assert claude_log.claude_report(transcript(*turn[:4])) is None


def test_report_of_an_answer_without_tool_calls(transcript, turn):
    assert claude_log.claude_report(transcript(*turn[:2])) == {"text": "old answer", "start": t0, "end": t0 + 60}


def test_task_counts_the_answered_turns_files_bash_and_agents(transcript):
    task_log = transcript(
        rec("user", 0, "old"),
        rec("assistant", 1, [text("ok")]),
        rec("user", 2, [text("  fix\nthe thing  ")]),
        edit(3, "Edit", file_path="/a.py"),
        edit(3, "Write", file_path="/a.py"),
        edit(4, "MultiEdit", file_path="/b.py"),
        edit(4, "Bash", command="ls"),
        edit(5, "Bash", command="pwd"),
        edit(5, "Task", prompt="x"),
        rec("user", 5, [{"type": "tool_result", "tool_use_id": "x"}]),
        edit(6, "Agent", prompt="y"),
        edit(
            6,
            "Edit",
            file_path="/side.py",
        ),
        rec("assistant", 7, [text("done")]),
        rec("user", 8, "<bash-input>ls</bash-input>"),
    )
    task_log2 = transcript(
        *[
            (
                {**r_, "isSidechain": True}
                if r_["message"]["content"][0].get("input", {}).get("file_path") == "/side.py"
                else r_
            )
            if isinstance(r_["message"]["content"], list)
            else r_
            for r_ in records.read(task_log)
        ]
    )
    assert claude_log.claude_task(task_log2) == {
        "ask": "fix\nthe thing",
        "files": ["/a.py", "/b.py"],
        "cmds": 2,
        "agents": 2,
    }
    assert claude_log.claude_task("/nope")["ask"] is None


def test_task_skips_injected_user_records_but_counts_their_tool_calls(transcript):
    noisy = transcript(
        rec("user", 0, "real ask"),
        edit(1, "Edit", file_path="/a.py"),
        rec("assistant", 2, [text("ok")]),
        inj(3, "<task-notification>\n<task-id>x</task-id>", origin={"kind": "task-notification"}),
        edit(4, "Bash", command="ls"),
        edit(4, "Edit", file_path="/b.py"),
        inj(5, "<system-reminder>\nnote\n</system-reminder>"),
        inj(5, "<local-command-stdout>x</local-command-stdout>"),
        inj(5, "<task-notification>y"),
        inj(5, "peer msg", origin={"kind": "peer"}),
        rec("assistant", 6, [text("done")]),
    )
    assert claude_log.claude_task(noisy) == {"ask": "real ask", "files": ["/a.py", "/b.py"], "cmds": 1, "agents": 0}


def test_task_shows_a_slash_command_and_cuts_system_reminders(transcript):
    slash = transcript(
        rec("user", 0, "before"),
        rec("assistant", 1, [text("a")]),
        rec(
            "user",
            2,
            "<command-message>sdlc-run</command-message>\n<command-name>/sdlc-run</command-name>\n<command-args>game-feel 025</command-args>",
            origin={"kind": "human"},
        ),
        rec("user", 2, "Base directory for this skill: /x\n" + "skill text\n" * 50, isMeta=True),
        rec("user", 3, "<system-reminder>\ninjected\n</system-reminder>\n/real typed words"),
        edit(4, "Edit", file_path="/c.py"),
        rec("assistant", 5, [text("done")]),
    )
    slash2 = transcript(*records.read(slash)[:-3], rec("assistant", 5, [text("done")]))
    assert claude_log.claude_task(slash)["ask"] == "/real typed words"
    assert claude_log.claude_task(slash2)["ask"] == "/sdlc-run game-feel 025"
    assert claude_log.claude_typed({}, "<system-reminder>only</system-reminder>") is None


def test_typed_text_outside_a_paste_is_the_ask():
    assert claude_log.claude_typed({}, "[Image #1] it broke\n\n\n" + pb("❯❯ bash x\nok")) == "[Image #1] it broke"
    assert (
        claude_log.claude_typed({}, "\n\n" + pb("❯❯ printf\n57") + "\n\n\nnew window is fine") == "new window is fine"
    )


def test_typed_only_a_paste_is_the_pasted_text():
    assert claude_log.claude_typed({}, pb("❯❯ printf\n57")) == "❯❯ printf\n57"


def test_typed_two_pastes_with_words_between_gives_the_words():
    assert claude_log.claude_typed({}, pb("one", "a") + "\nmiddle\n" + pb("two", "b")) == "middle"


def test_typed_unclosed_paste_loses_only_its_opening_marker():
    assert claude_log.claude_typed({}, 'hi\n<pasted_content id="z">\nbody') == "hi\nbody"
    assert "pasted_content" not in claude_log.claude_typed({}, '<pasted_content id="z">\nbody')


def test_typed_closing_marker_lookalike_does_not_end_a_paste():
    assert claude_log.claude_typed({}, pb('see </pasted_content id="q"> inside') + "\ntyped") == "typed"
    assert claude_log.claude_typed({}, pb('a </pasted_content id="q"> b')) == 'a </pasted_content id="q"> b'
    assert "pasted_content" not in claude_log.claude_typed({}, pb("x") + '\ntyped\n<pasted_content id="z">\nrest')


@pytest.fixture
def liveq(transcript):
    return transcript(*records.live_turn())


def test_live_turn_has_ask_start_tool_said_and_previous_report(liveq):
    cl = claude_log.claude_live(liveq)
    assert cl == {
        "live": True,
        "task": {"ask": "fix the thing", "files": ["/a.py"], "cmds": 1, "agents": 0},
        "start": t0 + 120,
        "end": None,
        "tool": "Bash: rg -n foo",
        "said": "working on it\nline2",
        "prev": {"text": "previous answer", "start": t0, "end": t0 + 60},
    }


@pytest.fixture
def longlog(transcript):
    return transcript(
        rec("user", 0, "before"),
        rec("assistant", 1, [text("previous answer")]),
        rec("user", 2, "long ask"),
        *bulk(3, 1.3),
    )


def test_live_turn_that_began_before_the_tail_keeps_ask_start_and_prev(longlog):
    ll = claude_log.claude_live(longlog)
    assert ll["start"] == t0 + 120
    assert ll["task"]["ask"] == "long ask"
    assert ll["task"]["files"] == []
    assert ll["tool"] == "Bash: ls"
    assert ll["prev"] == {"text": "previous answer", "start": t0, "end": t0 + 60}


def test_live_same_turn_read_again_is_not_searched_again(longlog, searches):
    ll = claude_log.claude_live(longlog)
    append(longlog, rec("assistant", 20, [text("more")]), *bulk(21, 0.1))
    ll2 = claude_log.claude_live(longlog)
    assert len(searches) == 1
    assert (ll2["start"], ll2["task"]["ask"], ll2["prev"]) == (ll["start"], ll["task"]["ask"], ll["prev"])
    assert ll2["said"] == "more"


def test_live_new_prompt_replaces_the_remembered_turn(longlog, searches):
    claude_log.claude_live(longlog)
    append(longlog, rec("assistant", 20, [text("more")]), *bulk(21, 0.1))
    claude_log.claude_live(longlog)
    append(longlog, rec("user", 30, "second ask"), rec("assistant", 31, [text("on it")]))
    ll3 = claude_log.claude_live(longlog)
    n_ = len(searches)
    append(longlog, rec("user", 40, "third ask"), *bulk(41, 1.3))
    ll4 = claude_log.claude_live(longlog)
    assert ll3["start"] == t0 + 1800
    assert ll3["task"]["ask"] == "second ask"
    assert n_ == 1
    assert len(searches) == 2
    assert ll4["start"] == t0 + 2400
    assert ll4["task"]["ask"] == "third ask"
    assert ll4["prev"]["text"] == "on it"


def test_live_log_replaced_by_another_file_is_not_the_remembered_turn(transcript, longlog):
    claude_log.claude_live(longlog)
    other = transcript(rec("user", 0, "other ask"), *bulk(1, 1.3))
    os.replace(other, longlog)
    assert claude_log.claude_live(longlog)["task"]["ask"] == "other ask"


def test_live_log_rewritten_in_place_is_searched_again(transcript, searches):
    longlog = transcript(rec("user", 0, "other ask"), *bulk(1, 1.3))
    claude_log.claude_live(longlog)
    n_ = len(searches)
    with open(longlog, "w") as f:
        f.writelines(json.dumps(r_) + "\n" for r_ in [rec("user", 0, "rewritten ask"), *bulk(1, 1.4)])
    assert claude_log.claude_live(longlog)["task"]["ask"] == "rewritten ask"
    assert len(searches) == n_ + 1


def test_live_log_cut_shorter_is_searched_again(transcript, searches):
    cut = transcript(rec("user", 0, "cut ask"), *bulk(1, 1.3))
    claude_log.claude_live(cut)
    with open(cut, "r+") as f:
        f.truncate(os.path.getsize(cut) - 100000)
    n_ = len(searches)
    assert claude_log.claude_live(cut)["task"]["ask"] == "cut ask"
    assert len(searches) == n_ + 1


def test_live_new_prompt_at_the_tail_edge_is_the_turn(transcript):
    edge = []
    for d in (-1, 0, 1):
        el = transcript(rec("user", 0, "OLD"), *bulk(1, 1.3))
        claude_log.claude_live(el)
        prompt = json.dumps(rec("user", 50, "EDGE new")) + "\n"
        pad = lambda n: (
            json.dumps(rec("user", 51, [{"type": "tool_result", "tool_use_id": "z", "content": "o" * n}])) + "\n"
        )
        room = common.LIVE_TAIL + d - len(prompt) - len(pad(0))
        with open(el, "a") as f:
            f.write(prompt + pad(room))
        edge.append(claude_log.claude_live(el)["task"].get("ask"))
        for _ in range(2):
            append(el, *bulk(52, 0.1))
            edge.append(claude_log.claude_live(el)["task"].get("ask"))
    assert edge == ["EDGE new"] * 9


def test_live_prompt_with_a_tool_result_lookalike_is_still_the_prompt(transcript):
    mid = transcript(
        rec("user", 0, "earlier"),
        rec("assistant", 1, [text("a")]),
        rec("user", 2, "ask with a lookalike", meta={"type": "tool_result"}),
        *bulk(3, 1.3),
    )
    assert claude_log.claude_live(mid)["task"]["ask"] == "ask with a lookalike"


def test_live_prompt_beyond_the_lookback_is_not_found(transcript, monkeypatch):
    monkeypatch.setattr(claude_log, "LONG_TURN_LOOKBACK", 64 * 1024)
    far = transcript(rec("user", 0, "far ask"), *bulk(1, 1.3))
    fl = claude_log.claude_live(far)
    assert fl["start"] is None
    assert fl["task"] == {}
    assert fl["prev"] is None
    assert fl["tool"] == "Bash: ls"


def test_live_turn_inside_the_tail_never_searches(liveq, searches):
    cl = claude_log.claude_live(liveq)
    assert searches == []
    assert claude_log.claude_live(liveq) == cl
    assert searches == []


def test_report_for_working_gives_the_live_page(transcript, turn, liveq):
    assert collect.report_for({"kind": "claude", "transcript": liveq, "status": "working"})["live"] is True
    assert collect.report_for({"kind": "claude", "transcript": liveq}) is None
    assert collect.report_for({"kind": "claude", "transcript": transcript(*turn), "status": "idle"})["text"].startswith(
        "## 結果"
    )


@pytest.fixture
def subagents(transcript, turn):
    """A main transcript with subagents a (finished, answered), b (running), c and e (broken metas), d (finished, no text)."""
    sess = transcript(*turn)
    sdir = os.path.join(sess[:-6], "subagents")
    os.makedirs(sdir)

    def agent(name, meta, *recs):
        if meta is not None:
            with open(os.path.join(sdir, f"agent-{name}.meta.json"), "w") as m:
                m.write(meta if isinstance(meta, str) else json.dumps(meta))
        with open(os.path.join(sdir, f"agent-{name}.jsonl"), "w") as g:
            g.writelines(json.dumps(r) + "\n" for r in recs)

    agent(
        "a",
        {"agentType": "executor", "description": "Fin one", "finished": True},
        rec("user", 0, "go", isSidechain=True),
        rec("assistant", 1, [text("sub final")], isSidechain=True),
    )
    agent("b", {"agentType": "executor", "description": "Still running"}, rec("user", 0, "go", isSidechain=True))
    agent("c", "not json {", rec("user", 0, "go", isSidechain=True))
    agent("e", "[1]", rec("user", 0, "go", isSidechain=True))
    agent(
        "d",
        {"agentType": "executor", "description": "No log text", "finished": True},
        rec("user", 0, "go", isSidechain=True),
    )
    return sess, sdir, agent


def test_subagent_report_is_read_only_on_request(subagents):
    _, sdir, _ = subagents
    assert claude_log.claude_report(os.path.join(sdir, "agent-a.jsonl")) is None
    assert claude_log.claude_report(os.path.join(sdir, "agent-a.jsonl"), sidechain=True)["text"] == "sub final"


def test_subagents_only_finished_metas_with_their_text(subagents):
    sess, _, _ = subagents
    fin = claude_log.finished_subagents(sess)
    assert fin == [
        {"type": "executor", "desc": "Fin one", "text": "sub final"},
        {"type": "executor", "desc": "No log text", "text": ""},
    ]


def test_report_for_carries_the_subagents_finished_in_its_turn(transcript, turn, subagents):
    sess, _, _ = subagents
    fin = claude_log.finished_subagents(sess)
    assert collect.report_for({"kind": "claude", "transcript": sess})["subagents"] == [
        s for s in fin if s["desc"] == "No log text"
    ]
    assert collect.report_for({"kind": "claude", "transcript": sess})["text"].startswith("## 結果")
    assert collect.report_for({"kind": "claude", "transcript": transcript(*turn)})["subagents"] == []


def test_subagent_handback_message_is_its_report(transcript, subagents):
    sess, sdir, agent = subagents
    handback = [
        rec("user", 0, "go", isSidechain=True),
        rec("assistant", 1, [text("working")], isSidechain=True),
        rec(
            "assistant",
            2,
            [
                {
                    "type": "tool_use",
                    "id": "h",
                    "name": "SubagentHandback",
                    "input": {"message": "  ## 報告\nall good \n"},
                }
            ],
            isSidechain=True,
        ),
        rec(
            "user",
            3,
            [{"type": "tool_result", "tool_use_id": "h", "content": [text('{"success":true}')]}],
            isSidechain=True,
        ),
    ]
    agent("h", {"agentType": "general-purpose", "description": "Handback", "finished": True}, *handback)
    hb_log = os.path.join(sdir, "agent-h.jsonl")
    assert claude_log.claude_report(hb_log, sidechain=True) == {
        "text": "## 報告\nall good",
        "start": t0,
        "end": t0 + 120,
    }
    assert (
        next(s for s in claude_log.finished_subagents(sess) if s["desc"] == "Handback")["text"] == "## 報告\nall good"
    )
    assert claude_log.claude_report(hb_log) is None
    assert claude_log.claude_report(transcript(*[{**r_, "isSidechain": False} for r_ in handback])) is None


def test_subagents_only_those_that_ended_in_the_reports_turn(subagents):
    sess, sdir, agent = subagents
    handback = [
        rec("user", 0, "go", isSidechain=True),
        rec("assistant", 1, [text("working")], isSidechain=True),
        rec(
            "assistant",
            2,
            [
                {
                    "type": "tool_use",
                    "id": "h",
                    "name": "SubagentHandback",
                    "input": {"message": "  ## 報告\nall good \n"},
                }
            ],
            isSidechain=True,
        ),
        rec(
            "user",
            3,
            [{"type": "tool_result", "tool_use_id": "h", "content": [text('{"success":true}')]}],
            isSidechain=True,
        ),
    ]
    agent("h", {"agentType": "general-purpose", "description": "Handback", "finished": True}, *handback)
    os.utime(os.path.join(sdir, "agent-d.jsonl"), (t0, t0))
    assert [s["desc"] for s in claude_log.finished_subagents(sess, t0 + 120)] == ["Handback"]
    assert [s["desc"] for s in collect.report_for({"kind": "claude", "transcript": sess})["subagents"]] == ["Handback"]


def test_claude_session_only_in_a_pane_whose_process_tree_holds_its_pid(monkeypatch):
    fields = {f: "" for f in collect.TMUX_FIELDS}
    kids = {"50": ["51"], "51": ["52"]}
    cpanes = [
        dict(
            fields,
            pane_id="%7",
            pane_pid="50",
            pane_current_command="sleep",
            session_name="s",
            session_attached="1",
            window_active="1",
            window_id="@1",
            window_panes="1",
        )
    ]
    monkeypatch.setattr(collect, "read_tmux", lambda: cpanes)
    monkeypatch.setattr(processes, "proc_children", lambda pid: kids.get(str(pid), []))
    monkeypatch.setattr(collect, "screen_changed", lambda ps, now: {})
    kinds = []
    for spid in ("52", "99"):
        monkeypatch.setattr(
            claude_log,
            "read_claude_sessions",
            lambda spid=spid: {"%7": {"pid": spid, "sid": "", "name": "", "status": "idle"}},
        )
        kinds.append([a["kind"] for t in collect.collect()["towns"] for a in t["agents"]])
    assert kinds == [["claude"], []]


CACHE_LINES = [
    {
        "type": "assistant",
        "timestamp": "2026-11-03T04:00:00.000Z",
        "message": {"usage": {"cache_creation": {"ephemeral_1h_input_tokens": 500, "ephemeral_5m_input_tokens": 0}}},
    },
    {"type": "user", "timestamp": "2026-11-03T04:05:00.000Z", "message": {"content": "hi"}},
    {
        "type": "assistant",
        "timestamp": "2026-11-03T04:06:00.000Z",
        "message": {
            "usage": {
                "input_tokens": 10,
                "cache_read_input_tokens": 40000,
                "cache_creation_input_tokens": 90,
                "cache_creation": {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 0},
            }
        },
    },
    {
        "type": "assistant",
        "isSidechain": True,
        "timestamp": "2026-11-03T04:07:00.000Z",
        "message": {"usage": {"input_tokens": 999999}},
    },
]


def write_cache_transcript(path, pad_kb=0):
    with open(path, "w") as f:
        f.writelines(json.dumps(line) + "\n" for line in CACHE_LINES)
        f.writelines(json.dumps({"type": "attachment", "content": "x" * 1000}) + "\n" for _ in range(pad_kb))
    return str(path)


def test_cache_info_takes_the_last_usage_time_the_ttl_of_the_last_cache_write_and_main_context(tmp_path):
    info = claude_log.cache_info(write_cache_transcript(tmp_path / "t.jsonl"))
    assert info is not None
    last, ttl, used, limit = info
    assert limit is None
    assert last == datetime.fromisoformat("2026-11-03T04:06:00+00:00").timestamp()
    assert ttl == 3600
    assert used == 40100


def test_cache_info_finds_the_last_usage_behind_300_kb_of_attachments(tmp_path):
    assert claude_log.cache_info(write_cache_transcript(tmp_path / "t.jsonl", 300))[1:3] == (3600, 40100)


def test_cache_info_gives_the_usage_limit_message_that_ended_the_newest_turn(transcript, turn):
    path = transcript(*turn, rec("user", 10, "go on"), *records.limit_tail(11))
    assert claude_log.cache_info(path)[3] == {"text": records.LIMIT_TEXT, "end": t0 + 11 * 60}


def test_cache_info_usage_limit_is_cleared_by_a_later_prompt_but_not_by_an_injected_one(transcript, turn):
    limited = records.limit_tail(11)
    noted = transcript(*limited, rec("user", 12, "<task-notification>x</task-notification>"))
    asked = transcript(*limited, rec("user", 12, "try again"))
    answered = transcript(*limited, *turn)
    assert claude_log.cache_info(noted)[3] is not None
    assert claude_log.cache_info(asked)[3] is None
    assert claude_log.cache_info(answered)[3] is None
