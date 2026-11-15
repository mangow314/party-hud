# pyright: reportOptionalSubscript=false, reportOptionalMemberAccess=false
"""Tests index results they expect to exist; a None there fails the test, so the Optional checks are off."""

import builtins
import os

import pytest
from screen import strip

from party_hud import art, collect, common, render

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "sidebar.json")


@pytest.fixture
def towns():
    return collect.collect(FIXTURE)["towns"]


@pytest.fixture
def agents(towns):
    return [a for t in towns for a in t["agents"]]


@pytest.fixture
def done(agents):
    return dict(agents[0], status="done", hp_left=410000, hp_max=1000000)


def test_no_images_in_art_dir_gives_the_text_version(tmp_path, monkeypatch):
    monkeypatch.setattr(art, "ART_DIR", str(tmp_path))
    assert art.load_art() is None


@pytest.fixture
def art_dir(tmp_path, monkeypatch):
    """All 56 image files under a temp ART_DIR, each a few bytes that say which it is."""
    folder = tmp_path / "art"
    folder.mkdir()
    monkeypatch.setattr(art, "ART_DIR", str(folder))
    flat_banners = [f"{n}-{k}x1" for k in range(5, 9) for n in art.BANNER_FILES]
    names = (
        art.PORTRAIT_FILES
        + art.CREST_FILES
        + art.BANNER_FILES
        + art.PORTRAIT_FILES
        + flat_banners
        + list(art.LABEL_COLS)
    )
    for i, n in enumerate(names):
        prefix = (
            "portrait-"
            if i < 8
            else "crest-"
            if i < 16
            else "banner-"
            if i < 20 or i >= 28 and i < 44
            else "label-"
            if i >= 44
            else "portrait-big-"
        )
        (folder / (prefix + n + ".png")).write_bytes(b"PNG" + bytes([i]))
    for j, n in enumerate(["select"] + [f"select-{k}x1" for k in range(5, 9)]):
        (folder / ("banner-" + n + ".png")).write_bytes(b"PNG" + bytes([51 + j]))
    return folder


def test_all_56_images_present(art_dir):
    imgs = art.load_art()

    def rd(k):
        with open(imgs[k][0], "rb") as f:
            return (f.read(), *imgs[k][1:])

    assert imgs
    assert len(imgs) == 56
    assert rd(art.select_banner_id(7)) == (b"PNG" + bytes([51 + 3]),)
    assert rd(art.label_id("running")) == (b"PNG" + bytes([50]),)
    assert rd(art.banner_id("waiting", True, False, 7)) == (b"PNG" + bytes([28 + 2 * 4 + 1]),)
    assert rd(art.BIG_PORTRAIT_ID + 3) == (b"PNG\x17",)
    assert rd(art.PORTRAIT_ID + 2) == (b"PNG\x02", 6, 3)
    assert rd(art.CREST_ID + 7) == (b"PNG\x0f", 4, 2)
    assert rd(art.BANNER_ID + 2) == (b"PNG\x12",)


def test_a_file_is_read_when_it_is_sent_and_an_unreadable_one_is_logged(art_dir, tmp_path, monkeypatch):
    """An unreadable file must not raise: send_image is called bare, so an exception fails the test."""
    reads, real_open = [], builtins.open

    class Spy:
        def __init__(self, f, path):
            self.f, self.path = f, path

        def __enter__(self):
            return self

        def __exit__(self, *e):
            self.f.close()

        def read(self, *n):
            reads.append(self.path)
            return self.f.read(*n)

    monkeypatch.setattr(
        builtins,
        "open",
        lambda path, *a, **k: (
            Spy(real_open(path, *a, **k), path) if str(path).startswith(str(art_dir)) else real_open(path, *a, **k)
        ),
    )
    loaded = art.load_art()
    n_load = len(reads)
    sent_one = art.send_image(loaded, art.PORTRAIT_ID + 2, 6, 3)
    n_one = len(reads)
    os.remove(loaded[art.LABEL_ID][0])
    monkeypatch.setattr(common, "PARTY_DIR", str(tmp_path))
    monkeypatch.setattr(common, "ERROR_LOG", str(tmp_path / "err.log"))
    sent_lost = art.send_image(loaded, art.LABEL_ID, 8, 1)
    assert loaded
    assert not any(isinstance(x, bytes) for v in loaded.values() for x in v)
    assert n_load == 0
    assert sent_one == art.kitty_image(art.PORTRAIT_ID + 2, b"PNG\x02", 6, 3)
    assert n_one == 1
    assert reads == [loaded[art.PORTRAIT_ID + 2][0]]
    assert sent_lost == ""
    with real_open(tmp_path / "err.log") as f:
        assert "FileNotFoundError" in f.read()


def test_select_banner_ids_are_its_own():
    old_ids = (
        [art.BANNER_ID + 4 * j + i for j in range(5) for i in range(4)]
        + [art.BIG_PORTRAIT_ID + i for i in range(8)]
        + [art.LABEL_ID + i for i in range(7)]
    )
    sel_ids = [art.select_banner_id(k) for k in range(4, 9)]
    assert len(set(sel_ids)) == 5
    assert not set(sel_ids) & set(old_ids)
    assert not set(sel_ids) & set(range(art.PORTRAIT_ID, art.PORTRAIT_ID + 8))
    assert not set(sel_ids) & set(range(art.CREST_ID, art.CREST_ID + 8))
    assert art.select_banner_id() == art.SELECT_BANNER_ID == 7996928


def test_report_banner_ids_stay_as_they_were():
    assert [
        art.banner_id(s, r, m)
        for s, r, m in (
            ("done", True, False),
            ("waiting", True, False),
            ("working", True, False),
            ("done", False, False),
        )
    ] == [7996160, 7996161, 7996162, 7996163]
    assert art.banner_id("waiting", True, False, 8) == 7996177


def test_images_are_on_for_ghostty_and_kitty():
    assert art.art_supported("", "xterm-ghostty")
    assert art.art_supported("", "xterm-kitty")
    assert not art.art_supported("", "xterm-256color")
    assert not art.art_supported("", "wezterm")
    assert art.art_supported("on", "xterm-256color")
    assert not art.art_supported("off", "xterm-ghostty")


def test_one_image_missing_falls_back_to_text(art_dir):
    os.remove(art_dir / "crest-moon.png")
    assert art.load_art() is None


def test_placeholder_row_is_6_cells():
    assert common.cw(strip(art.image_row(art.PORTRAIT_ID, 2, 6))) == 6
    assert art.image_row(art.PORTRAIT_ID, 2, 6).count("\U0010eeee") == 6


def test_placeholders_have_297_distinct_diacritics():
    assert len(art.DIAC) >= 80
    assert art.DIAC[:3] == [773, 781, 782]
    assert len(set(art.DIAC)) == len(art.DIAC)
    assert common.cw(strip(art.image_row(art.BANNER_ID, 9, 297))) == 297
    assert len(art.DIAC) == 297


def test_big_portrait_has_its_own_image_id(done):
    bp = art.big_portrait_id(done)
    assert bp != art.portrait_id(done)
    assert bp not in range(art.PORTRAIT_ID, art.PORTRAIT_ID + 8)
    assert bp >> 8 != art.BANNER_ID >> 8


def test_placeholder_foreground_and_diacritics():
    row = art.image_row(0x7A0103, 1, 2)
    assert row.startswith("\x1b[38;2;122;1;3m")
    assert "\U0010eeee̍̅\U0010eeee̍̍" in row


def test_image_upload_is_chunked_and_wrapped_in_passthrough(monkeypatch):
    monkeypatch.setenv("TMUX", "x")
    seq = art.kitty_image(7, b"x" * 5000, 6, 3)
    assert seq.startswith("\x1bPtmux;\x1b\x1b_Ga=T,U=1,f=100,i=7,c=6,r=3,q=2,m=1;")
    assert seq.count("\x1bPtmux;") == 2
    assert seq.endswith("m=0;" + __import__("base64").b64encode(b"x" * 5000).decode()[4096:] + "\x1b\x1b\\\x1b\\")


def test_image_delete(monkeypatch):
    monkeypatch.setenv("TMUX", "x")
    assert art.kitty_delete(5) == "\x1bPtmux;\x1b\x1b_Ga=d,d=I,i=5,q=2\x1b\x1b\\\x1b\\"


def test_crests_are_unique_for_up_to_8_squads():
    cr = art.crest_ids(["dotfiles", "homelab", "notes", "projects", "scratch"])
    assert len(set(cr.values())) == 5


def test_crests_repeat_from_the_9th_squad():
    assert len(set(art.crest_ids(f"s{i}" for i in range(8)).values())) == 8
    nine = art.crest_ids([f"s{i}" for i in range(9)])
    assert len(nine) == 9
    assert set(nine.values()) == {art.CREST_ID + k for k in range(len(art.CREST_FILES))}
    assert len(art.CREST_FILES) == 8


def test_portrait_chosen_by_class(towns, agents):
    fe = next(a for a in agents if a["pane"] == "%1")
    pid = art.portrait_id(fe)
    assert f"\x1b[38;2;{pid >> 16 & 255};{pid >> 8 & 255};{pid & 255}m" in render.render(towns, 33, "%1", art=True)
    assert pid == art.PORTRAIT_ID + fe["cls"]


def test_classes_are_unique_within_a_squad(towns):
    assert all(len({a["cls"] for a in t["agents"]}) == len(t["agents"]) for t in towns)
    assert len(set(common.spread([f"sess-{i}" for i in range(6)], 8).values())) == 6


REPO_ART = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "art")


def png_head(name):
    """(width, height, bit depth and color type) from a PNG's IHDR."""
    with open(os.path.join(REPO_ART, name), "rb") as f:
        b = f.read(33)
    assert b[:8] == b"\x89PNG\r\n\x1a\n"
    return int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big"), b[24:26]


RGBA8 = bytes([8, 6])


def test_the_8_big_portraits_are_384x432_rgba_so_the_corners_and_glow_stay_transparent():
    names = [n for n in os.listdir(REPO_ART) if n.startswith("portrait-big-") and n.endswith(".png")]
    assert len(names) == 8
    assert {png_head(n) for n in names} == {(384, 432, RGBA8)}


def test_the_8_small_portraits_are_192x216_rgba_so_the_corners_stay_transparent():
    names = [n for n in os.listdir(REPO_ART) if n.startswith("portrait-") and "-big-" not in n and n.endswith(".png")]
    assert len(names) == 8
    assert {png_head(n) for n in names} == {(192, 216, RGBA8)}


@pytest.mark.parametrize(
    ("label", "cells"),
    [("took", 8), ("waited", 10), ("asked", 9), ("files", 9), ("work", 8), ("where", 9), ("running", 11)],
)
def test_heading_labels_are_rgba_44_px_high_and_20_px_per_cell(label, cells):
    assert png_head(f"label-{label}.png") == (cells * 20, 44, RGBA8)


@pytest.mark.parametrize(("suffix", "height"), [("", 240), ("-5x1", 192), ("-6x1", 159), ("-7x1", 138), ("-8x1", 120)])
def test_select_banners_are_960_px_wide_at_their_heights(suffix, height):
    assert png_head(f"banner-select{suffix}.png")[:2] == (960, height)
