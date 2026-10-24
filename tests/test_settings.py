"""The settings table, and the label/colour choices."""
from __future__ import annotations

import pytest

from casttui import labels
from casttui.config import Config
from casttui.settings import BY_KEY, SETTINGS, parse, show, valid


def test_every_default_is_valid_and_every_choice_too():
    for s in SETTINGS:
        if s.default is not None:
            assert valid(s, s.default), s.key
        for c in s.choices:
            assert valid(s, c), (s.key, c)


def test_config_has_an_attribute_per_setting():
    cfg = Config()
    for s in SETTINGS:
        assert getattr(cfg, s.key) == s.default
    with pytest.raises(TypeError):
        Config(nonsense=1)


def test_mutable_defaults_are_not_shared():
    a, b = Config(), Config()
    a.devices.append("1.2.3.4")
    assert b.devices == []


def test_parse_typed_values():
    assert parse(BY_KEY["transcode"], "off") is False
    assert parse(BY_KEY["seek_step"], " 30 ") == 30
    assert parse(BY_KEY["volume_step"], "0.2") == 0.2
    assert parse(BY_KEY["start_dir"], "~/Videos") == "~/Videos"
    for key, text in [("seek_step", "x"), ("seek_step", "-5"), ("transcode", "maybe"),
                      ("icons", "emoji")]:
        with pytest.raises(ValueError):
            parse(BY_KEY[key], text)


def test_show():
    assert show(True) == "on" and show(None) == "-" and show(["a", "b"]) == "a, b"


def test_icons_auto_is_ascii_on_a_console_or_without_utf8():
    assert labels.pick_icons("auto", {"TERM": "linux", "LANG": "en_US.UTF-8"}) is labels.ASCII
    assert labels.pick_icons("auto", {"TERM": "xterm", "LANG": "C"}) is labels.ASCII
    assert labels.pick_icons("auto", {"TERM": "xterm", "LANG": "en_US.UTF-8"}) is labels.UNICODE
    assert labels.pick_icons("unicode", {"TERM": "xterm", "CASTTUI_ICONS": "ascii"}) is labels.ASCII


def test_ascii_labels_are_ascii():
    text = "".join(v if isinstance(v, str) else "".join(v.values()) for v in labels.ASCII.values())
    assert text.isascii()


def test_colour_depth_order():
    assert labels.pick_depth("256", {"NO_COLOR": "1"}) == 1
    assert labels.pick_depth("auto", {"CASTTUI_COLORS": "16", "TERM": "xterm-256color"}) == 16
    assert labels.pick_depth("mono", {"TERM": "xterm-256color"}) == 1
    assert labels.pick_depth("auto", {"TETRON_WM_COLORS": "mono"}) == 1
    assert labels.pick_depth("auto", {"TERM": "linux"}) == 16
    assert labels.pick_depth("auto", {"TERM": "vt100"}) == 1
    assert labels.pick_depth("auto", {"TERM": "xterm-256color"}) == 256


def test_bar():
    assert labels.bar(labels.ASCII, 50, 100, 10) == "#####-----"
    assert labels.bar(labels.ASCII, 5, None, 4) == "===="
