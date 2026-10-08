"""Service-layer tests: no real Chromecast, catt mocked (SCOPE §13)."""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from casttui.service import CastService, Status, _Listener


def make_device() -> MagicMock:
    """A CattDevice stand-in with a mockable media_controller."""
    dev = MagicMock()
    dev.name = "Test TV"
    dev._cast.media_controller.register_status_listener = MagicMock()
    return dev


def test_select_registers_listener():
    svc = CastService()
    dev = make_device()
    svc.select(dev)
    assert svc.device is dev
    dev._cast.media_controller.register_status_listener.assert_called_once()


def test_actions_delegate_to_device():
    svc = CastService()
    dev = make_device()
    svc.select(dev)

    svc.play_url("http://x/y.mp4")
    svc.play()
    svc.pause()
    svc.stop()
    svc.seek(42)
    svc.ffwd(10)
    svc.rewind(10)
    svc.mute(True)

    dev.play_url.assert_called_once_with("http://x/y.mp4")
    dev.play.assert_called_once()
    dev.pause.assert_called_once()
    dev.stop.assert_called_once()
    dev.seek.assert_called_once_with(42)
    dev.ffwd.assert_called_once_with(10)
    dev.rewind.assert_called_once_with(10)
    dev.volumemute.assert_called_once_with(True)


def test_volume_is_clamped():
    svc = CastService()
    dev = make_device()
    svc.select(dev)
    svc.volume(2.5)
    dev.volume.assert_called_once_with(1.0)
    svc.volume(-1.0)
    dev.volume.assert_called_with(0.0)


def test_require_without_device_raises():
    svc = CastService()
    try:
        svc.play()
    except RuntimeError as exc:
        assert "no device" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError")


# -- status bridge ----------------------------------------------------------


def synthetic_status(**kw):
    base = dict(
        player_state="PLAYING",
        title="Clip",
        current_time=12.0,
        duration=100.0,
        volume_level=0.5,
        volume_muted=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_listener_maps_fields():
    captured: list[Status] = []
    lst = _Listener(captured.append)
    lst.new_media_status(synthetic_status())
    s = captured[0]
    assert s.state == "PLAYING"
    assert s.title == "Clip"
    assert s.position == 12.0
    assert s.duration == 100.0
    assert s.volume == 0.5
    assert s.muted is False


def test_load_failed_maps_to_error():
    captured: list[Status] = []
    lst = _Listener(captured.append)
    lst.load_media_failed(object(), 905)
    assert captured[0].state == "ERROR"
    assert "905" in (captured[0].error or "")


def test_snapshot_interpolates_while_playing():
    svc = CastService()
    svc.select(make_device())
    svc._handle_push(Status(state="PLAYING", position=10.0, duration=100.0))
    time.sleep(0.05)
    assert svc.snapshot().position > 10.0


def test_snapshot_static_when_paused():
    svc = CastService()
    svc.select(make_device())
    svc._handle_push(Status(state="PAUSED", position=10.0, duration=100.0))
    time.sleep(0.05)
    assert svc.snapshot().position == 10.0


def test_snapshot_position_capped_at_duration():
    svc = CastService()
    svc.select(make_device())
    svc._handle_push(Status(state="PLAYING", position=99.99, duration=100.0))
    time.sleep(0.05)
    assert svc.snapshot().position <= 100.0


def test_error_push_keeps_last_known_title():
    svc = CastService()
    svc.select(make_device())
    svc._handle_push(Status(state="PLAYING", title="Clip", volume=0.5))
    svc._handle_push(Status(state="ERROR", error="load failed (code=905)"))
    s = svc.snapshot()
    assert s.state == "ERROR"
    assert s.title == "Clip"
    assert s.volume == 0.5


def test_on_update_callback_fires():
    svc = CastService()
    seen: list[Status] = []
    svc.select(make_device(), on_update=seen.append)
    svc._handle_push(Status(state="BUFFERING"))
    assert seen and seen[-1].state == "BUFFERING"


# -- local-file casting -----------------------------------------------------


class FakeStream:
    def __init__(self, local=True, ip="192.168.1.5"):
        self.is_local_file = local
        self.local_ip = ip
        self.port = 46000
        self.guessed_content_type = "video/mp4"
        self.video_title = "clip"


class FakeServer:
    instances: list["FakeServer"] = []

    def __init__(self, path, ip, port, ctype):
        self.url = f"http://{ip}:{port}/?loaded_from_casttui"
        self.started = False
        self.stopped = False
        FakeServer.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def patch_file(monkeypatch, stream=None):
    import casttui.service as svcmod

    FakeServer.instances = []
    monkeypatch.setattr(svcmod, "StreamInfo", lambda *a, **k: stream or FakeStream())
    monkeypatch.setattr(svcmod, "FileServer", FakeServer)


def test_play_file_serves_and_casts(monkeypatch):
    patch_file(monkeypatch)
    svc = CastService()
    dev = make_device()
    svc.select(dev)
    title = svc.play_file("/home/u/clip.mp4")
    assert title == "clip"
    server = FakeServer.instances[-1]
    assert server.started
    dev.play_url.assert_called_once_with(server.url)
    assert svc._fileserver is server


def test_stop_tears_down_fileserver(monkeypatch):
    patch_file(monkeypatch)
    svc = CastService()
    svc.select(make_device())
    svc.play_file("/x.mp4")
    server = FakeServer.instances[-1]
    svc.stop()
    assert server.stopped
    assert svc._fileserver is None


def test_switching_media_stops_previous_server(monkeypatch):
    patch_file(monkeypatch)
    svc = CastService()
    svc.select(make_device())
    svc.play_file("/a.mp4")
    first = FakeServer.instances[-1]
    svc.play_url("http://remote/x.mp4")  # switch to a remote URL
    assert first.stopped
    assert svc._fileserver is None


def test_play_file_rejects_non_local(monkeypatch):
    patch_file(monkeypatch, stream=FakeStream(local=False))
    svc = CastService()
    svc.select(make_device())
    try:
        svc.play_file("http://remote/x.mp4")
    except RuntimeError as exc:
        assert "not a local file" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError")


def test_play_file_requires_lan_ip(monkeypatch):
    patch_file(monkeypatch, stream=FakeStream(ip=None))
    svc = CastService()
    svc.select(make_device())
    try:
        svc.play_file("/x.mp4")
    except RuntimeError as exc:
        assert "LAN IP" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError")
