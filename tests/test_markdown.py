import re

import pytest

from party_hud import common, markdown

md = markdown.render_markdown
B, I, R, fgc = "\033[1m", "\033[3m", common.RESET, common.fg
TABLE = "| 名稱 | `k` |\n|:--|--:|\n| 一二 | **x** |\n| ab | yy |"
MIXED = "# T\n\n- a **b** `c`\n\n| h | i |\n|---|---|\n| 1 | 2 |\n\n```\ncode line that is long\n```\nlast line of text"


def strip(text):
    return re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", text)


def plain(text, width, code_width=None):
    return [strip(r) for r in md(text, width, code_width)]


@pytest.fixture(autouse=True)
def fresh_cache():
    markdown.clear_markdown_cache()


def test_wrap_sgr_keeps_sgr_escapes():
    assert markdown.wrap_sgr("\x1b[31mred\x1b[0m plain", 40) == ["\x1b[31mred\x1b[0m plain\x1b[0m"]


def test_wrap_sgr_drops_other_escapes():
    text = "a\x1b[2Jb\x1b[1;1Hc\x1b]0;title\x07d\x1b[?25l\x1b[38;5;1me"
    assert markdown.wrap_sgr(text, 40) == ["abcd\x1b[38;5;1me\x1b[0m"]


def test_wrap_sgr_carries_colour_to_every_row_within_width():
    wr = markdown.wrap_sgr("\x1b[1;32m" + "你好ab" * 5 + "\x1b[0m tail", 9)
    assert len(wr) > 2
    assert all(common.cw(strip(r)) <= 9 for r in wr)
    assert all(r.endswith("\x1b[0m") for r in wr[:-1])
    assert all(r.startswith("\x1b[1;32m") for r in wr[:3])
    assert wr[-1].endswith(" tail\x1b[0m")


def test_wrap_by_display_width_expands_tabs_and_drops_controls():
    assert markdown.wrap("一二三四五", 4) == ["一二", "三四", "五"]
    assert markdown.wrap("a\tb\x1b[31m", 9) == ["a   b[31m"]


def test_headings_gold_bold_marker_dropped():
    assert md("# T\n###### s", 20) == [fgc("gold", True) + "T" + R, fgc("gold", True) + "s" + R]


def test_bold():
    assert md("a **b** c", 20) == ["a " + B + "b" + R + " c"]


def test_italic_not_underscores_inside_a_word():
    assert md("*x* _y_ snake_case_name", 30) == [I + "x" + R + " " + I + "y" + R + " snake_case_name"]


def test_inline_code_is_literal_in_code_colour():
    assert md("a `**x**` b", 20) == ["a " + fgc("code") + "**x**" + R + " b"]


def test_lists_and_hanging_wrapped_items():
    assert plain("- a\n* b\n1. c", 20) == ["• a", "• b", "1. c"]
    assert plain("- 一二三四五", 6) == ["• 一二", "  三四", "  五"]


def test_fenced_code_is_literal_fences_dropped_long_lines_wrap():
    assert md("```py\n**x**\n```\nabcdef", 20) == [fgc("green") + "**x**" + R, "abcdef"]
    assert plain("```\nabcdef", 4) == ["abcd", "ef"]


def test_link_shows_text_and_url():
    expected = "see " + fgc("blue") + "\033[4m" + "doc" + R + fgc("dim") + " (http://u/x)" + R + " ok"
    assert md("see [doc](http://u/x) ok", 40) == [expected]


def test_rule_as_wide_as_the_pane():
    assert md("---", 10) == [fgc("dim") + "─" * 10 + R]


def test_every_source_line_stays_a_line():
    assert plain("a\nb\n\nc", 5) == ["a", "b", "", "c"]


def test_cjk_two_columns_combining_marks_zero():
    assert plain("一二三éf", 5) == ["一二", "三éf"]
    assert all(common.cw(r) <= 5 for r in plain("一二三éf", 5))


def test_numbered_list_keeps_number_and_hangs_rows():
    assert plain("1. abcdefgh", 6) == ["1. abc", "   def", "   gh"]


def test_five_combining_marks_fit_in_width_five():
    assert plain("é" * 5, 5) == ["é" * 5]


def test_styled_text_wraps_with_style_and_reset_per_row():
    wr = md("**aaa bbb ccc**", 5)
    assert len(wr) == 3
    assert all(r.startswith(B) and r.endswith(R) and common.cw(strip(r)) <= 5 for r in wr)


def test_cache_never_returns_rows_for_other_text_or_widths():
    a1 = md(MIXED, 30, 40)
    assert md(MIXED + "x", 30, 40) != a1
    assert md(MIXED, 12, 40) != a1
    assert md(MIXED, 30, 20) != a1
    assert md(MIXED, 30, 40) == a1


def test_no_code_width_means_width():
    assert md(MIXED, 30) == md(MIXED, 30, 30)


def test_editing_returned_rows_leaves_the_cache_unchanged():
    a1 = md(MIXED, 30, 40)
    expected = list(a1)
    a1.append("junk")
    a1[0] = "junk"
    assert md(MIXED, 30, 40) == expected


def test_same_input_twice_is_a_cache_hit():
    md(MIXED, 30, 40)
    h0 = markdown._markdown_rows.cache_info().hits
    md(MIXED, 30, 40)
    assert markdown._markdown_rows.cache_info().hits == h0 + 1


def test_nested_lists_images_and_html_stay_raw():
    raw = ["  - **x**", "  - nested", "| a | b |", "![img](u.png)", "<b>x</b>"]
    assert md("\n".join(raw), 30) == raw


def test_table_that_fits_is_aligned_columns():
    tr = md(TABLE, 20)
    assert [strip(r) for r in tr] == ["名稱 │ k", "─────┼───", "一二 │ x", "ab   │ yy"]
    assert tr[1] == fgc("dim") + "─────┼───" + R
    assert tr[0].startswith(B + "名稱")


def test_table_too_wide_becomes_name_value_groups():
    tn = md(TABLE, 8)
    assert [strip(r) for r in tn] == ["名稱：一", "  二", "k：x", "", "名稱：ab", "k：yy"]
    assert tn[0].startswith(fgc("dim") + "名稱：")


def test_long_table_cells_wrap_and_no_row_is_wider_than_width():
    assert plain("| 名稱 | v |\n|--|--|\n| 一二三四五六 | `ab cd` |", 12) == ["名稱：一二三", "  四五六", "v：ab cd"]
    assert all(common.cw(r) <= w for w in (1, 2, 3, 5, 12) for r in plain(TABLE, w))


def test_short_table_row_is_padded():
    assert plain("| a | b |\n|--|--|\n| 1 |", 20) == ["a │ b", "──┼──", "1 │ "]


def test_pipe_line_without_separator_is_plain_text():
    assert md("| a | b |\nplain", 30) == ["| a | b |", "plain"]


def test_english_wraps_at_last_space():
    assert plain("Haven't seen the report yet", 12) == ["Haven't seen", "the report", "yet"]


def test_word_wider_than_row_is_cut():
    assert plain("ab abcdefghij", 6) == ["ab", "abcdef", "ghij"]


def test_closing_punctuation_never_starts_a_row():
    assert plain("一二三，四五。六", 6) == ["一二", "三，四", "五。六"]
    assert all(common.cw(r) <= 6 for r in plain("一二三，四五。六", 6))


def test_quote_gets_dim_edge_per_level():
    qr = md("> a **b**\n> > c", 20)
    assert [strip(r) for r in qr] == ["▎ a b", "▎▎ c"]
    assert all(r.startswith(fgc("dim") + "▎") for r in qr)
    assert md("> x", 20)[0].endswith(fgc("dim") + "x" + R)


def test_wrapped_quote_rows_keep_the_edge():
    assert plain("> aaa bbb ccc", 7) == ["▎ aaa", "▎ bbb", "▎ ccc"]


@pytest.mark.parametrize(
    ("text", "width"),
    [("a。。。", 5), ("a" + "，" * 9 + "。", 21), ("- 一" + "）" * 8 + "。", 20), ("> > > > > x", 4), ("> abc", 1)],
)
def test_no_row_wider_than_width_and_no_text_lost(text, width):
    rows = plain(text, width)
    assert all(common.cw(r) <= width for r in rows)
    kept = "".join(rows).replace("▎", "").replace("•", "").replace(" ", "")
    assert kept == text.replace("> ", "").replace("- ", "").replace(" ", "")


def test_wrapping_leaves_no_leading_space_or_empty_row():
    assert plain("see README.md 」", 14) == ["see README.md", "」"]
    assert plain("abcd   ef", 4) == ["abcd", "ef"]
    assert plain("word 。。。", 6) == ["word", "。。。"]
    assert plain("   abcdef", 3) == ["abc", "def"]


def test_closing_punctuation_carries_the_whole_english_word():
    assert plain("aa bcd，", 6) == ["aa", "bcd，"]
    assert plain("- aa bcd，", 8) == ["• aa", "  bcd，"]


def test_carried_word_keeps_its_own_punctuation():
    assert plain("see README.md」", 14) == ["see", "README.md」"]
    assert plain("> see README.md」", 16) == ["▎ see", "▎ README.md」"]


def test_quote_too_narrow_for_the_edge_drops_the_edge():
    assert "".join(plain("> 中文", 3)) == "中文"
    assert all(common.cw(r) <= 3 for r in plain("> 中文", 3))
