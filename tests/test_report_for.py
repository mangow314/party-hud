# pyright: reportOptionalSubscript=false
"""Tests index results they expect to exist; a None there fails the test, so the Optional check is off."""

import os

import pytest

from party_hud import collect

agy_screen = "old\n\nI changed 2 files.\nAll tests pass.\n\n\u256d\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256e\n\u2502 > ask   \u2502\n\u2570\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256f\n  ? for shortcuts\n"
grok_screen = "first\n\nDone: \u4fee\u597d\u4e86\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n> \n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n grok-4  ctx 3%\n"
agy_real = "\n".join(
    [
        "\u2500" * 49,
        "> 分三段回答，不要用工具：第一段說明 tmux session",
        "  persistence 是什麼；第二段列出三個常用指令（用 -",
        "  開頭的清單）；第三段一句話總結。",
        "",
        "\u26a0 Sign-in update needed",
        "  \u23bf  Your sign-in is missing permissions that are",
        "     now required, so some requests may fail. Run",
        "     /logout to sign in again.",
        "",
        "\u25b8 Thought for 10s, 829 tokens",
        "",
        "  tmux session",
        "  persistence（工作階段持久化）是指當終端機關閉、",
        "  SSH 連線中斷或網路異常時，tmux",
        "  仍能在伺服器背景持續運行所有程式與終端狀態，讓",
        "  使用者隨時能重新連回原先的作業環境；廣義上亦包",
        "  含透過外掛（如 tmux-",
        "  resurrect）在伺服器重新開機後復原 session",
        "  與視窗佈局的機制。",
        "",
        "  \u2022 tmux new -s <名稱>：建立並進入一個具名的全新",
        "  session。",
        "  \u2022 tmux detach：將目前的 session",
        "  脫離至背景繼續執行（或使用快捷鍵 Ctrl+b 接",
        "  d）。",
        "  \u2022 tmux attach -t",
        "  <名稱>：重新附加並回到指定的背景 session",
        "  繼續作業。",
        "",
        "  tmux session persistence",
        "  能徹底避免因斷線導致工作中斷或進度遺失，實現隨",
        "  時暫停且無縫接續的終端工作流。",
        "",
        "\u2500" * 52,
        ">",
        "\u2500" * 52,
        "? for shortcuts              Gemini 3.8 Flash · high",
        "",
    ]
)
grok_real = "\n".join(
    [
        "  sdlc/quest-report-v2 ~/projects/party-hud [Click here to Upgrade]                 32K / 256K \u2502 [Dashboard]",
        "",
        "",
        "     \u276f 分三段回答，不要用工具：第一段說明 tmux session persistence 是什麼；第二段列出三個常用指令（用 - 開頭的清單）；第三段   12:47 AM   \u2588",
        "       一句話總結。          \u2588",
        "          \u2588",
        "     \u25c6 Thought for 0.8s       \u2588",
        "          \u2588",
        "     tmux session persistence 是指終端機視窗關掉、SSH 斷線，或你登出之後，tmux 裡的工作階段仍留在背景繼續跑。程序、視窗配置和  12:47 AM   \u2588",
        "     工作目錄都還在，之後重新連上同一台機器就能接回去。        \u2588",
        "          \u2588",
        "     \u2022 tmux new -s work：建立名為 work 的工作階段       \u2588",
        "     \u2022 tmux ls：列出目前還在的工作階段       \u2588",
        "     \u2022 tmux attach -t work：接回名為 work 的工作階段       \u2588",
        "          \u2588",
        "     一句話：tmux 把終端工作留在伺服器上，斷線後還能原樣接回來。       \u2588",
        "          \u2588",
        "     Worked for 4.9s        \u2588",
        "          \u2588",
        "",
        "  Help improve Grok                                    [Opt out] [Opt in]",
        "  Off by default. Opt-in to allow SpaceXAI to retain coding data, e.g., prompts, traces, & metrics, for training and",
        "  debugging purposes. Change anytime via settings.",
        "  Read Terms and Privacy Policy.",
        "",
        "  \u256d" + "\u2500" * 40 + "\u256e",
        "  \u2502 \u276f" + " " * 38 + "\u2502",
        "  \u2570" + "\u2500" * 20 + " Grok 4.7 (high) \u2500\u256f",
        "",
        "  Shift+Tab:mode  \u2502  Ctrl+x:shortcuts",
    ]
)
grok_scrolled = "\n".join(
    [
        "  [Click here to Upgra… 32K / 256K \u2502 [Dashboard]",
        "",
        "    tmux 把終端工作留在可隨時接回的",
        "    背景 session 裡，關掉視窗不會中",
        "    斷裡面的程式。",
        "",
        "    Worked for 13s                              \u2588",
        "                                                \u2588",
        "",
        " Help improve Grok            [Opt out] [Opt in]",
        " Off by default. Opt-in to allow SpaceXAI to",
        " retain coding data, e.g., prompts, traces, &",
        " metrics, for training and debugging purposes.",
        " Change anytime via settings.",
        " Read Terms and Privacy Policy.",
        " \u256d" + "\u2500" * 45 + "\u256e",
        " \u2502 \u276f" + " " * 42 + "\u2502",
        " \u2570" + "\u2500" * 27 + " Grok 4.7 (high) \u2500\u256f",
        " Ctrl+x:shortcuts",
    ]
)
agy_thought = "\n".join(
    ["> 問題", "", "▸ Thought for 6s", "  第一段的", "  文字。", "", "  第二段。", "", "─" * 20, ">", "─" * 20]
)
SCREEN_CASES = (
    (
        "agy",
        agy_real,
        "tmux session persistence（工作階段持久化）是指當終端機關閉、SSH 連線中斷或網路異常時，tmux 仍能在伺服器背景持續運行所有程式與終端狀態，讓使用者隨時能重新連回原先的作業環境；廣義上亦包含透過外掛（如 tmux-resurrect）在伺服器重新開機後復原 session 與視窗佈局的機制。\n\n• tmux new -s <名稱>：建立並進入一個具名的全新 session。\n• tmux detach：將目前的 session 脫離至背景繼續執行（或使用快捷鍵 Ctrl+b 接 d）。\n• tmux attach -t <名稱>：重新附加並回到指定的背景 session 繼續作業。\n\ntmux session persistence 能徹底避免因斷線導致工作中斷或進度遺失，實現隨時暫停且無縫接續的終端工作流。",
    ),
    (
        "grok",
        grok_real,
        "tmux session persistence 是指終端機視窗關掉、SSH 斷線，或你登出之後，tmux 裡的工作階段仍留在背景繼續跑。程序、視窗配置和工作目錄都還在，之後重新連上同一台機器就能接回去。\n\n• tmux new -s work：建立名為 work 的工作階段\n• tmux ls：列出目前還在的工作階段\n• tmux attach -t work：接回名為 work 的工作階段\n\n一句話：tmux 把終端工作留在伺服器上，斷線後還能原樣接回來。",
    ),
)


@pytest.fixture
def repos(tmp_path):
    """A repo on feat/x with a worktree, a detached repo, one with control characters in HEAD, one on a remote ref."""
    repo, wt, det, bad, tags = (str(tmp_path / n) for n in ("repo", "wt", "det", "bad", "tags"))
    os.makedirs(wt)
    os.makedirs(os.path.join(repo, ".git", "refs"))
    os.makedirs(os.path.join(repo, "src", "deep"))
    with open(os.path.join(repo, ".git", "HEAD"), "w") as f:
        f.write("ref: refs/heads/feat/x\n")
    os.makedirs(os.path.join(repo, ".git", "worktrees", "wt1"))
    with open(os.path.join(repo, ".git", "worktrees", "wt1", "HEAD"), "w") as f:
        f.write("ref: refs/heads/wt-branch\n")
    with open(os.path.join(wt, ".git"), "w") as f:
        f.write("gitdir: " + os.path.join(repo, ".git", "worktrees", "wt1") + "\n")
    os.makedirs(os.path.join(bad, ".git"))
    os.makedirs(os.path.join(det, ".git"))
    with open(os.path.join(det, ".git", "HEAD"), "w") as f:
        f.write("0123456789abcdef0123456789abcdef01234567\n")
    with open(os.path.join(bad, ".git", "HEAD"), "w") as f:
        f.write("ref: refs/heads/a\tb\x1b]52;c;ZXZpbA==\x07\n")
    os.makedirs(os.path.join(tags, ".git"))
    with open(os.path.join(tags, ".git", "HEAD"), "w") as f:
        f.write("ref: refs/remotes/o/x\n")
    return repo, wt, det, bad, tags


def test_git_branch_drops_control_characters_and_ignores_other_refs(repos):
    _, _, _, bad, tags = repos
    assert collect.git_branch(bad) == "ab]52;c;ZXZpbA=="
    assert collect.git_branch(tags) is None


def test_git_branch_from_head_parent_dir_worktree_and_detached(repos):
    repo, wt, det, _, _ = repos
    assert collect.git_branch(os.path.join(repo, "src", "deep")) == "feat/x"
    assert collect.git_branch(wt) == "wt-branch"
    assert collect.git_branch(det) == "0123456"
    assert collect.git_branch("/nope/none") is None


def screen(monkeypatch, text):
    monkeypatch.setattr(collect, "tmux", lambda *args: text)


@pytest.mark.parametrize(
    ("kind", "shown", "want"),
    [("agy", agy_screen, "I changed 2 files. All tests pass."), ("grok", grok_screen, "Done: 修好了")],
)
def test_report_for_agy_grok_last_paragraph_above_input_box(monkeypatch, kind, shown, want):
    screen(monkeypatch, shown)
    got = collect.report_for({"kind": kind, "pane": "%3"})
    assert got
    assert got["text"] == want


@pytest.mark.parametrize(("kind", "shown", "want"), SCREEN_CASES)
def test_screen_report_whole_last_reply_unwrapped(monkeypatch, kind, shown, want):
    screen(monkeypatch, shown)
    got = collect.report_for({"kind": kind, "pane": "%3"})
    assert got
    assert got["text"] == want


def test_screen_report_prompt_then_one_line(monkeypatch):
    screen(monkeypatch, "> ask\n\nonly line\n")
    assert collect.report_for({"kind": "agy", "pane": "%3"})["text"] == "only line"


def test_screen_report_without_box_is_the_last_paragraph(monkeypatch):
    screen(monkeypatch, "no border\n\nlast words\n")
    assert collect.report_for({"kind": "agy", "pane": "%3"})["text"] == "last words"


def test_screen_report_grok_scrolled_past_the_prompt(monkeypatch):
    screen(monkeypatch, grok_scrolled)
    assert (
        collect.report_for({"kind": "grok", "pane": "%3"})["text"]
        == "tmux 把終端工作留在可隨時接回的背景 session 裡，關掉視窗不會中斷裡面的程式。"
    )


def test_screen_report_reads_scrollback(monkeypatch):
    cap_args = []
    monkeypatch.setattr(collect, "tmux", lambda *args: cap_args.append(args) or "x\n")
    collect.report_for({"kind": "agy", "pane": "%3"})
    assert cap_args
    assert "-S" in cap_args[0]
    assert "-J" in cap_args[0]


def test_screen_report_thought_line_keeps_its_paragraph(monkeypatch):
    screen(monkeypatch, agy_thought)
    assert collect.report_for({"kind": "agy", "pane": "%3"})["text"] == "第一段的文字。\n\n第二段。"


def test_screen_report_fake_agy_screen_gives_the_reply(monkeypatch):
    screen(monkeypatch, "ready\nhello\n\nparty-test-reply-42\n")
    assert collect.report_for({"kind": "agy", "pane": "%3"})["text"] == "party-test-reply-42"


def test_screen_report_blank_screen_is_none(monkeypatch):
    screen(monkeypatch, "\n\n")
    assert collect.report_for({"kind": "grok", "pane": "%3"}) is None
