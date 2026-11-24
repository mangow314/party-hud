"""Claude Code transcripts written to a test folder."""

import json
import tempfile
from datetime import datetime

T0 = datetime.fromisoformat("2026-11-07T10:00:00+00:00").timestamp()


def rec(kind, t, content, **extra):
    return {"type": kind, "timestamp": f"2026-11-07T10:{t:02d}:00Z", "message": {"content": content}, **extra}


def text(s):
    return {"type": "text", "text": s}


def transcript(folder, *recs):
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", dir=folder, delete=False) as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    return f.name


def read(path):
    with open(path) as f:
        return [json.loads(line) for line in f]


def append(path, *recs):
    with open(path, "a") as f:
        f.writelines(json.dumps(r) + "\n" for r in recs)


def bulk(t, mb):
    """Bash tool calls and 100 KB results, mb megabytes of them."""
    use = {"type": "tool_use", "id": "z", "name": "Bash", "input": {"command": "ls"}}
    res = {"type": "tool_result", "tool_use_id": "z", "content": "o" * 100000}
    return [
        r
        for _ in range(int(mb * 1024 * 1024 / 100000) + 1)
        for r in (rec("assistant", t, [use]), rec("user", t, [res]))
    ]


def turn():
    """An earlier answered turn, then a turn with thinking, a tool call and a two-part answer, then sidechain and meta noise."""
    return [
        rec("user", 0, "earlier"),
        rec("assistant", 1, [text("old answer")]),
        rec("user", 2, "fix it"),
        rec("assistant", 3, [{"type": "thinking", "thinking": "hm"}]),
        rec("assistant", 3, [text("I'll look first")]),
        rec("assistant", 4, [{"type": "tool_use", "id": "x"}]),
        rec("user", 5, [{"type": "tool_result", "tool_use_id": "x"}]),
        rec("assistant", 6, [text("## 結果\nDone")]),
        rec("assistant", 7, [text("One more line")]),
        rec("assistant", 8, [text("subagent noise")], isSidechain=True),
        rec("user", 9, "caveat", isMeta=True),
    ]


def live_turn():
    """An answered turn, then a turn still working: text, an Edit, its result, then a Bash call."""
    return [
        rec("user", 0, "before"),
        rec("assistant", 1, [text("previous answer")]),
        rec("user", 2, "fix the thing"),
        rec("assistant", 3, [text("working on it\nline2")]),
        rec("assistant", 4, [{"type": "tool_use", "id": "z", "name": "Edit", "input": {"file_path": "/a.py"}}]),
        rec("user", 5, [{"type": "tool_result", "tool_use_id": "z"}]),
        rec(
            "assistant",
            6,
            [
                {
                    "type": "tool_use",
                    "id": "z",
                    "name": "Bash",
                    "input": {"command": "rg -n foo\nsecond line", "description": "search"},
                }
            ],
        ),
    ]


LIMIT_TEXT = "You've hit your weekly limit · resets Nov 9, 2am (UTC). /model to switch models."


def limit_tail(t):
    """What Claude Code 2.1.325 writes when a prompt is refused at the usage limit: the error record, then bookkeeping lines."""
    zero = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation": {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 0},
    }
    error = rec(
        "assistant",
        t,
        [text(LIMIT_TEXT)],
        isSidechain=False,
        apiError="usage_limit_reached",
        error="rate_limit",
        isApiErrorMessage=True,
        apiErrorStatus=429,
        apiErrorType="rate_limit_error",
    )
    error["message"].update(model="<synthetic>", role="assistant", stop_reason="stop_sequence", usage=zero)
    stamp = error["timestamp"]
    return [
        error,
        {"type": "system", "subtype": "turn_duration", "isSidechain": False, "isMeta": False, "timestamp": stamp},
        {"type": "last-prompt", "lastPrompt": "go on"},
        {"type": "cost-state", "totalCostUSD": 0},
    ]
