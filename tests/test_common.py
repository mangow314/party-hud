"""common.cw, the display width every card line is measured with."""

import unicodedata

from party_hud import art, common


def plain_width(s):
    return sum(0 if unicodedata.combining(ch) else 2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


BMP = [chr(c) for c in range(0x10000) if not 0xD800 <= c < 0xE000]
ASTRAL = [
    chr(c)
    for c in (
        0x1F600,
        0x1F468,
        0x1F1E6,
        0x20000,
        0x2FFFD,
        0xE0001,
        0xF0000,
        0xF0953,
        0xF1841,
        0xFFFFD,
        0x10EEEE,
        0x10FFFF,
    )
]
MIXED = [
    "",
    "abc",
    "a一b" + chr(0x301) + "c",
    "\x00\x1f\x7f",
    "ab一́\U0001f600x",
    chr(0x10EEEE) + chr(art.DIAC[1]) + chr(art.DIAC[2]),
    "plain ascii " * 20,
]


def test_cw_matches_the_per_character_algorithm_and_repeated_calls_agree():
    samples = (
        BMP + ASTRAL + [chr(c) for c in art.DIAC] + MIXED + ["".join(BMP[i : i + 50]) for i in range(0, len(BMP), 50)]
    )
    wrong = [s[:20] for s in samples if not common.cw(s) == common.cw(s) == plain_width(s)]
    assert wrong == []


def test_cw_char_cache_stays_within_its_bound():
    cache = common._char_width
    maxsize = cache.cache_info().maxsize
    assert maxsize is not None
    for i in range(maxsize + 500):
        common.cw(chr(0x4E00 + i))
    assert cache.cache_info().currsize <= maxsize
