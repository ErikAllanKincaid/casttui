"""Command line parsing and the UI choice."""
from __future__ import annotations

import pytest

from casttui.cli import parse_args, parse_source, pick_ui


def test_parse_source_none_url_and_file(tmp_path, monkeypatch):
    f = tmp_path / "a clip.mp4"
    f.write_bytes(b"x")
    assert parse_source([]) is None
    assert parse_source(["https://x/y.mp4"]) == "https://x/y.mp4"
    monkeypatch.chdir(tmp_path)
    assert parse_source(["a clip.mp4"]) == str(f)  # made absolute


def test_parse_source_rejects_a_missing_file_and_extra_args(tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        parse_source([str(tmp_path / "nope.mp4")])
    assert e.value.code == 2 and "not a file" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        parse_source(["a", "b"])


def test_device_and_ui_flags():
    args = parse_args(["--classic", "-d", "192.168.1.50", "https://x/y"])
    assert (args.ui, args.device, args.source) == ("classic", "192.168.1.50", "https://x/y")
    assert parse_args(["--panes"]).ui == "panes"
    with pytest.raises(SystemExit):
        parse_args(["--panes", "--classic"])


def test_ui_choice_order():
    assert pick_ui("classic", {"CASTTUI_UI": "panes"}, "panes") == "classic"
    assert pick_ui(None, {"CASTTUI_UI": "classic"}, "panes") == "classic"
    assert pick_ui(None, {}, "classic") == "classic"
    assert pick_ui(None, {"CASTTUI_UI": "bogus"}, "bogus") == "panes"


def test_help_lists_every_setting(capsys):
    from casttui.settings import SETTINGS

    with pytest.raises(SystemExit):
        parse_args(["--help"])
    out = capsys.readouterr().out
    for s in SETTINGS:
        assert s.key in out


def test_version(capsys):
    from casttui import __version__

    with pytest.raises(SystemExit):
        parse_args(["--version"])
    assert capsys.readouterr().out.strip() == f"casttui {__version__}"
