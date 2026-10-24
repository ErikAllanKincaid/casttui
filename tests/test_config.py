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


def test_save_keeps_comments_order_and_unknown_keys(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('# my casttui\nseek_step = 30  # thirty\nfuture_key = "x"\n\n[keys]\nquit = "x"\n')
    cfg = Config.load(p)
    assert cfg.seek_step == 30 and cfg.keys == {"quit": "x"}
    cfg.transcode = False
    cfg.seek_step = 15
    cfg.save()
    text = p.read_text()
    assert "# my casttui" in text and "# thirty" in text and 'future_key = "x"' in text
    again = Config.load(p)
    assert again.seek_step == 15 and again.transcode is False and again.keys == {"quit": "x"}


def test_a_bad_value_falls_back_for_that_key_only(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('seek_step = "lots"\ntranscode = false\ndevices = ["10.0.0.5"]\n')
    cfg = Config.load(p)
    assert cfg.seek_step == 10 and cfg.transcode is False and cfg.devices == ["10.0.0.5"]


def test_a_malformed_file_is_kept_aside_on_save(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("this is : not = valid [toml")
    Config.load(p).save()
    assert (tmp_path / "config.toml.bad").read_text() == "this is : not = valid [toml"
