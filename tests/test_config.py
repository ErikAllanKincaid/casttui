"""Config persistence: roundtrip, defaults, and corruption tolerance."""
from __future__ import annotations

from casttui.config import Config


def test_defaults_when_missing(tmp_path):
    cfg = Config.load(tmp_path / "nope.toml")
    assert cfg.last_device is None
    assert cfg.seek_step == 10
    assert cfg.volume_step == 0.1


def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "config.toml"
    Config(
        last_device="Living Room TV", seek_step=30, volume_step=0.25,
        transcode=False,
    ).save(p)
    cfg = Config.load(p)
    assert cfg.last_device == "Living Room TV"
    assert cfg.seek_step == 30
    assert cfg.volume_step == 0.25
    assert cfg.transcode is False


def test_transcode_defaults_true(tmp_path):
    assert Config.load(tmp_path / "nope.toml").transcode is True


def test_save_creates_parent_dirs(tmp_path):
    p = tmp_path / "a" / "b" / "config.toml"
    Config(last_device="TV").save(p)
    assert p.exists()


def test_malformed_file_yields_defaults(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("this is : not = valid [toml")
    cfg = Config.load(p)
    assert cfg.last_device is None


def test_none_device_is_omitted(tmp_path):
    p = tmp_path / "config.toml"
    Config().save(p)
    assert "last_device" not in p.read_text()
