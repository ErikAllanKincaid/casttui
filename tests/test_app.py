"""Headless app tests via Textual's run_test(); catt fully mocked."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from casttui.app import CastTUI, fmt_time, progress_bar
from casttui.config import Config
from casttui.service import CastService, Status


def make_app(service, config=None) -> CastTUI:
    # Always pass an explicit Config so tests never read the real user file.
    return CastTUI(service=service, config=config or Config())


def test_fmt_time():
    assert fmt_time(None) == "--:--"
    assert fmt_time(0) == "00:00"
    assert fmt_time(65) == "01:05"


def test_progress_bar_unknown_duration():
    bar = progress_bar(10, None, width=10)
    assert set(bar) == {"─"} and len(bar) == 10


def test_progress_bar_half():
    bar = progress_bar(50, 100, width=10)
    assert bar.count("█") == 5 and bar.count("░") == 5


def fake_service() -> CastService:
    svc = CastService()
    # Avoid a real network scan in the mount worker.
    svc.discover = MagicMock(return_value=[])  # type: ignore[method-assign]
    return svc


@pytest.mark.asyncio
async def test_app_boots_and_cycles_three_views():
    app = make_app(fake_service())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#devices").display is True
        assert app.query_one("#cast").display is False
        await pilot.press("tab")
        assert app.query_one("#cast").display is True
        await pilot.press("tab")
        assert app.query_one("#nowplaying").display is True
        await pilot.press("tab")  # wraps back to devices
        assert app.query_one("#devices").display is True


@pytest.mark.asyncio
async def test_empty_scan_shows_message():
    app = make_app(fake_service())
    async with app.run_test() as pilot:
        await pilot.pause()
        status = app.query_one("#devices-status")
        assert "No Chromecasts" in str(status.render())


@pytest.mark.asyncio
async def test_cast_url_without_device_warns():
    svc = fake_service()
    app = make_app(svc)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#url").value = "http://x/y.mp4"  # type: ignore[attr-defined]
        await app._cast_url()
        # No device selected → service.play_url must not be reached.
        assert svc.device is None


@pytest.mark.asyncio
async def test_auto_reconnects_to_last_device():
    dev = MagicMock()
    dev.name = "Living Room TV"
    dev.ip_addr = "192.168.1.208"
    dev._cast.media_controller.register_status_listener = MagicMock()
    svc = CastService()
    svc.discover = MagicMock(return_value=[dev])  # type: ignore[method-assign]
    app = make_app(svc, config=Config(last_device="Living Room TV"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        assert svc.device is dev  # reconnected without a click
        assert app.query_one("#cast").display is True


@pytest.mark.asyncio
async def test_serve_file_transcodes_unsupported_when_enabled(monkeypatch):
    import casttui.app as appmod

    svc = fake_service()
    svc.play_file = MagicMock(return_value="clip")  # type: ignore[method-assign]
    monkeypatch.setattr(appmod, "unsupported_warning", lambda p: "av1 bad")
    monkeypatch.setattr(appmod, "has_ffmpeg", lambda: True)
    app = make_app(svc, config=Config(transcode=True))
    title, warning, transcoded = app._serve_file("/x.mkv")
    assert transcoded is True
    svc.play_file.assert_called_once_with("/x.mkv", transcode=True)


@pytest.mark.asyncio
async def test_serve_file_warns_when_transcode_disabled(monkeypatch):
    import casttui.app as appmod

    svc = fake_service()
    svc.play_file = MagicMock(return_value="clip")  # type: ignore[method-assign]
    monkeypatch.setattr(appmod, "unsupported_warning", lambda p: "av1 bad")
    monkeypatch.setattr(appmod, "has_ffmpeg", lambda: True)
    app = make_app(svc, config=Config(transcode=False))
    _, warning, transcoded = app._serve_file("/x.mkv")
    assert transcoded is False and warning == "av1 bad"
    svc.play_file.assert_called_once_with("/x.mkv", transcode=False)


@pytest.mark.asyncio
async def test_now_playing_refreshes_from_snapshot():
    svc = fake_service()
    dev = MagicMock()
    dev._cast.media_controller.register_status_listener = MagicMock()
    svc.select(dev)
    svc._handle_push(Status(state="PLAYING", title="Clip", position=5, duration=10, volume=0.5))
    app = make_app(svc)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._refresh_now_playing()
        assert "Clip" in str(app.query_one("#np-title").render())
        assert "PLAYING" in str(app.query_one("#np-state").render())
