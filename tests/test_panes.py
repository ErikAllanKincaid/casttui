"""The paned UI, headless: keys go in through PanesApp.press, the screen comes
out as text, catt is mocked and every background call runs inline."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import casttui.panes.app as appmod
from casttui.config import Config
from casttui.panes import PanesApp
from casttui.panes.keys import ACTIONS, bar_text, keymap
from casttui.service import CastService, Status

ENV = {"TERM": "xterm-256color", "LANG": "C.UTF-8"}


def device(name="Living Room TV", ip="192.168.1.208"):
    d = MagicMock()
    d.name, d.ip_addr = name, ip
    d._cast.cast_info.model_name = "Chromecast"
    return d


def service(found=()):
    svc = CastService()
    svc.discover = MagicMock(return_value=list(found))
    svc.select = MagicMock(side_effect=lambda d: setattr(svc, "device", d))
    svc.connect = MagicMock(side_effect=lambda t: device("Office", t))
    for name in ("play_file", "play_url", "play_stream", "cast_site", "play", "pause",
                 "stop", "ffwd", "rewind", "volumeup", "volumedown", "mute", "seek"):
        setattr(svc, name, MagicMock(return_value="clip"))
    return svc


@pytest.fixture
def media(tmp_path):
    (tmp_path / "shows").mkdir()
    (tmp_path / "clip.mp4").write_bytes(b"x" * 2048)
    (tmp_path / ".hidden.mp4").write_bytes(b"x")
    return tmp_path


def make(svc=None, cfg=None, env=ENV, **kw):
    cfg = cfg or Config()
    cfg.path = Path(kw.pop("cfg_path", "/nonexistent/casttui.toml"))
    return PanesApp(service=svc or service(), config=cfg, env=env, inline=True, **kw)


def screen(app, cols=120, rows=32):
    return "\n".join(app.screen_text(cols, rows))


def keys(app, *seq):
    for k in seq:
        app.press(k)


@pytest.fixture(autouse=True)
def _no_probe(monkeypatch):
    monkeypatch.setattr(appmod, "unsupported_warning", lambda p: None)
    monkeypatch.setattr(appmod, "has_ffmpeg", lambda: True)


def test_layouts_follow_the_size():
    app = make()
    wide, medium, narrow = screen(app, 200, 40), screen(app, 120, 32), screen(app, 70, 20)
    assert all(t in wide for t in ("1 Devices", "Source", "Now playing", "4 Config", "5 History"))
    assert "5 History" not in medium and "4 Config" in medium
    # One pane at a time, with a tab strip naming them all.
    assert narrow.splitlines()[0].split() == ["1", "Devices", "2", "Source", "3", "Now",
                                              "playing", "4", "Config", "5", "History"]


def test_number_keys_tab_and_zoom_move_focus():
    app = make()
    keys(app, "4")
    assert app.focus == 3 and ">4 Config" in screen(app)
    keys(app, "tab", "tab")
    assert app.focus == 0
    keys(app, "shift tab")
    assert app.focus == 4
    keys(app, "2", "z")
    assert screen(app).splitlines()[0].lstrip().startswith("1 Devices  2 Source")
    keys(app, "z")
    assert not app.zoom


def test_scan_reconnects_to_the_remembered_device(media):
    dev = device()
    svc = service([dev])
    app = make(svc, Config(last_device="Living Room TV", start_dir=str(media)))
    app.start()
    assert svc.device is dev
    assert "Reconnected to Living Room TV" in screen(app)
    assert app.focus == 1  # moved on to Source
    assert "* Living Room TV" in screen(app)


def test_remembered_address_connects_without_waiting_for_a_scan():
    svc = service([])
    app = make(svc, Config(last_device="10.0.5.20"))
    app.start()
    svc.connect.assert_called_once_with("10.0.5.20")
    assert svc.device.ip_addr == "10.0.5.20"
    assert app.cfg.last_device == "10.0.5.20"


def test_add_by_address_saves_and_connects(tmp_path):
    svc = service([])
    app = make(svc, cfg_path=tmp_path / "c.toml")
    keys(app, "1", "a", *"192.168.7.9", "enter")
    assert app.cfg.devices == ["192.168.7.9"]
    assert svc.device.ip_addr == "192.168.7.9"
    assert "192.168.7.9" in (tmp_path / "c.toml").read_text()


def test_add_by_address_rejects_a_name():
    app = make()
    keys(app, "a", *"kitchen", "enter")
    assert app.cfg.devices == [] and "ERROR: Not an address" in screen(app)


def test_forget_a_saved_address():
    app = make(cfg=Config(devices=["10.0.0.5"]))
    keys(app, "1")
    assert app.devices.current() == ("ip", "10.0.0.5")
    keys(app, "d")
    assert app.cfg.devices == []


def test_cast_without_a_device_says_so_and_goes_to_devices(media):
    svc = service()
    app = make(svc, cfg=Config(start_dir=str(media)))
    keys(app, "2", "j", "j", "enter")  # ../  shows/  clip.mp4
    svc.play_file.assert_not_called()
    assert app.focus == 0 and "ERROR: No device" in screen(app)


def test_browse_and_cast_a_file(media):
    svc = service([device()])
    app = make(svc, Config(last_device="Living Room TV", start_dir=str(media)))
    app.start()
    text = screen(app)
    assert "shows/" in text and "clip.mp4" in text and ".hidden" not in text
    keys(app, "j", "j", "enter")  # ../  shows/  clip.mp4
    svc.play_file.assert_called_once_with(str(media / "clip.mp4"), transcode=False, scale=None)
    svc.snapshot = MagicMock(return_value=Status(state="PLAYING", title="clip", position=50,
                                                 duration=100, volume=0.5))
    text = screen(app)
    assert "PLAYING" in text and "vol 50%" in text and "mode    direct" in text
    assert "cast clip.mp4" in "\n".join(e.text for e in app.history)


def test_folders_open_and_backspace_returns(media):
    app = make(cfg=Config(start_dir=str(media)))
    keys(app, "2", "j", "enter")
    assert app.cwd == media / "shows"
    keys(app, "backspace")
    assert app.cwd == media and app.files.current() == ("dir", media / "shows")
    keys(app, ".")
    assert ".hidden.mp4" in screen(app)


def test_unsupported_codec_transcodes_at_the_set_height(media, monkeypatch):
    monkeypatch.setattr(appmod, "unsupported_warning", lambda p: "av1")
    svc = service([device()])
    app = make(svc, Config(last_device="Living Room TV", transcode_scale=720))
    app.start()
    app.cast_file(media / "clip.mp4")
    svc.play_file.assert_called_once_with(str(media / "clip.mp4"), transcode=True, scale=720)
    assert app.playing.mode == "transcode 720p"


def test_command_line_source_casts_once_connected(media):
    svc = service([device()])
    app = make(svc, source=str(media / "clip.mp4"))
    app.start()  # the only device found: used without asking
    svc.play_file.assert_called_once()
    assert app.source is None


def test_urls_direct_media_vs_yt_dlp_vs_page():
    svc = service([device()])
    app = make(svc, Config(last_device="Living Room TV"))
    app.start()
    keys(app, "u", *"http://h/a.mp4", "enter")
    svc.play_url.assert_called_once_with("http://h/a.mp4")
    keys(app, "u", *"https://youtu.be/x", "enter")
    svc.play_stream.assert_called_once_with("https://youtu.be/x")
    keys(app, "w", *"https://example.com", "enter")
    svc.cast_site.assert_called_once_with("https://example.com")
    assert "WEB PAGE" in screen(app)


def test_esc_cancels_the_prompt():
    svc = service([device()])
    app = make(svc, Config(last_device="Living Room TV"))
    app.start()
    keys(app, "u", *"http://x", "esc")
    svc.play_url.assert_not_called()
    assert app.prompt is None


def test_playback_keys_use_the_steps():
    svc = service([device()])
    app = make(svc, Config(last_device="Living Room TV", seek_step=30, volume_step=0.05))
    app.start()
    svc.snapshot = MagicMock(return_value=Status(state="PLAYING"))
    keys(app, " ", "l", "h", "+", "-", "m", "s")
    svc.pause.assert_called_once()
    svc.ffwd.assert_called_once_with(30)
    svc.rewind.assert_called_once_with(30)
    svc.volumeup.assert_called_once_with(0.05)
    svc.volumedown.assert_called_once_with(0.05)
    svc.mute.assert_called_once_with(True)
    svc.stop.assert_called_once()


def test_config_pane_cycles_and_saves(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("# mine\n")
    app = make(cfg_path=p)
    keys(app, "4", "j")  # ui, transcode
    keys(app, "enter")
    assert app.cfg.transcode is False
    keys(app, "j", "j", "+")  # seek_step 10 -> 15
    assert app.cfg.seek_step == 15
    assert "# mine" in p.read_text() and "seek_step = 15" in p.read_text()
    # + and - change the setting in Config, not the volume.
    assert app.service.volumeup.call_count == 0


def test_typed_setting_and_colon_set():
    app = make()
    app.config_list.select("start_dir")
    keys(app, "4", "enter", *"/tmp", "enter")
    assert app.cfg.start_dir == "/tmp"
    keys(app, ":", *"set seek_step 45", "enter")
    assert app.cfg.seek_step == 45
    keys(app, ":", *"set seek_step lots", "enter")
    assert app.cfg.seek_step == 45 and "ERROR" in screen(app)


def test_icons_setting_relabels_live():
    app = make(env={"TERM": "xterm", "LANG": "C.UTF-8"})
    assert "│" in screen(app)
    app.set_setting("icons", "ascii")
    assert screen(app).isascii()


def test_console_screen_is_pure_ascii(media):
    svc = service([device()])
    app = make(svc, Config(last_device="Living Room TV", start_dir=str(media)),
               env={"TERM": "linux", "LANG": "en_US.UTF-8"})
    app.start()
    app.cast_file(media / "clip.mp4")
    svc.snapshot = MagicMock(return_value=Status(state="PLAYING", position=5, duration=10))
    for size in ((200, 40), (100, 30), (60, 20)):
        assert screen(app, *size).isascii(), size
    keys(app, "?")
    assert screen(app).isascii() and "Play or pause" in screen(app)


def test_history_recasts(media):
    svc = service([device()])
    app = make(svc, Config(last_device="Living Room TV"))
    app.start()
    app.cast_file(media / "clip.mp4")
    keys(app, "5", "enter")
    assert svc.play_file.call_count == 2


def test_quit_and_stop_quit():
    import urwid

    svc = service([device()])
    app = make(svc, Config(last_device="Living Room TV"))
    app.start()
    with pytest.raises(urwid.ExitMainLoop):
        app.press("q")
    svc.stop.assert_not_called()
    with pytest.raises(urwid.ExitMainLoop):
        app.press("Q")
    svc.stop.assert_called_once()


def test_key_overrides_and_conflicts():
    table, problems = keymap({"quit": "x", "mute": "space"})
    assert table["global"]["x"] == "quit" and "q" not in table["global"]
    assert any("space is both" in p for p in problems)
    _, problems = keymap({"nope": "k"})
    assert problems == ["[keys] unknown action 'nope'"]


def test_default_keys_have_no_conflicts_and_avoid_ctrl_and_f_keys():
    _, problems = keymap({})
    assert problems == []
    for a in ACTIONS:
        for k in a.keys.split(","):
            k = k.strip()
            assert not k.startswith(("ctrl", "meta")) and not (k.startswith("f") and k[1:].isdigit())


def test_every_pane_has_a_key_bar():
    table, _ = keymap({})
    for pane in ("devices", "source", "nowplaying", "config", "history"):
        assert "? help" in bar_text(table, pane)
    assert "h/l seek" in bar_text(table, "nowplaying")


def test_a_failed_call_shows_its_error():
    svc = service([device()])
    svc.play_url = MagicMock(side_effect=RuntimeError("receiver said no"))
    app = make(svc, Config(last_device="Living Room TV"))
    app.start()
    keys(app, "u", *"http://h/a.mp4", "enter")
    assert "ERROR: Could not play: receiver said no" in screen(app)
    assert app.playing is None
