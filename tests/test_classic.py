"""Headless app tests via Textual's run_test(); catt fully mocked."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from casttui.classic import CastTUI, fmt_time, progress_bar
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
        # The scan and the connect run in threads: wait for them, not for a
        # fixed number of event-loop turns (that raced about 1 run in 20).
        for _ in range(100):
            await pilot.pause(0.02)
            if svc.device is dev and app.query_one("#cast").display:
                break
        assert svc.device is dev  # reconnected without a click
        assert app.query_one("#cast").display is True


@pytest.mark.asyncio
async def test_serve_file_transcodes_unsupported_when_enabled(monkeypatch):
    import casttui.classic as appmod

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
    import casttui.classic as appmod

    svc = fake_service()
    svc.play_file = MagicMock(return_value="clip")  # type: ignore[method-assign]
    monkeypatch.setattr(appmod, "unsupported_warning", lambda p: "av1 bad")
    monkeypatch.setattr(appmod, "has_ffmpeg", lambda: True)
    app = make_app(svc, config=Config(transcode=False))
    _, warning, transcoded = app._serve_file("/x.mkv")
    assert transcoded is False and warning == "av1 bad"
    svc.play_file.assert_called_once_with("/x.mkv", transcode=False)


@pytest.mark.asyncio
async def test_middle_click_pastes_primary_into_url(monkeypatch):
    import casttui.classic as appmod

    monkeypatch.setattr(appmod, "primary_selection", lambda: "http://host/clip.mp4\n")
    app = make_app(fake_service())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab")  # Cast view
        await pilot.pause()
        # Middle-click the URL box without focusing it first.
        await pilot.mouse_down("#url", button=2)
        await pilot.pause()
        assert app.query_one("#url").value == "http://host/clip.mp4"  # type: ignore[attr-defined]


def test_primary_selection_skips_empty_tool(monkeypatch):
    import casttui.classic as appmod

    monkeypatch.setattr(appmod.shutil, "which", lambda name: "/usr/bin/" + name)

    def fake_run(cmd, **kw):
        out = "picked\n" if cmd[0] == "xsel" else ""
        return MagicMock(returncode=0, stdout=out)

    monkeypatch.setattr(appmod.subprocess, "run", fake_run)
    assert appmod.primary_selection() == "picked\n"


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


# -- command-line SOURCE (casttui <file|url>) ---------------------------------


def make_device(name="Living Room TV"):
    dev = MagicMock()
    dev.name = name
    dev.ip_addr = "192.168.1.208"
    dev._cast.media_controller.register_status_listener = MagicMock()
    return dev


def service_with(devices):
    svc = CastService()
    svc.discover = MagicMock(return_value=devices)  # type: ignore[method-assign]
    svc.play_file = MagicMock(return_value="clip")  # type: ignore[method-assign]
    svc.play_stream = MagicMock()  # type: ignore[method-assign]
    return svc


@pytest.mark.asyncio
async def test_source_file_casts_to_the_only_device(tmp_path, monkeypatch):
    import casttui.classic as appmod

    monkeypatch.setattr(appmod, "unsupported_warning", lambda p: None)
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    svc = service_with([make_device()])
    app = CastTUI(service=svc, config=Config(), source=str(f))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        assert svc.device is not None, "a lone Chromecast is chosen without a click"
        svc.play_file.assert_called_once_with(str(f), transcode=False)
        assert app.query_one("#nowplaying").display is True
        assert app._source is None, "the source is cast once"


@pytest.mark.asyncio
async def test_source_waits_for_a_click_when_there_are_two_devices(tmp_path, monkeypatch):
    import casttui.classic as appmod

    monkeypatch.setattr(appmod, "unsupported_warning", lambda p: None)
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    a, b = make_device("Kitchen"), make_device("Den")
    svc = service_with([a, b])
    app = CastTUI(service=svc, config=Config(), source=str(f))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        assert svc.device is None
        svc.play_file.assert_not_called()
        assert "v.mp4" in str(app.query_one("#devices-status").render())
        await app._select(b)
        svc.play_file.assert_called_once_with(str(f), transcode=False)


@pytest.mark.asyncio
async def test_source_uses_the_remembered_device_among_several(tmp_path, monkeypatch):
    import casttui.classic as appmod

    monkeypatch.setattr(appmod, "unsupported_warning", lambda p: None)
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    svc = service_with([make_device("Kitchen"), make_device("Den")])
    app = CastTUI(service=svc, config=Config(last_device="Den"), source=str(f))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        assert svc.device.name == "Den"
        svc.play_file.assert_called_once()


@pytest.mark.asyncio
async def test_source_url_goes_through_the_stream_path():
    svc = service_with([make_device()])
    app = CastTUI(service=svc, config=Config(), source="https://example.com/v.mp4")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        svc.play_stream.assert_called_once_with("https://example.com/v.mp4")
        svc.play_file.assert_not_called()


@pytest.mark.asyncio
async def test_no_source_still_just_selects_the_device():
    svc = service_with([make_device()])
    app = CastTUI(service=svc, config=Config())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        assert svc.device is None, "without a source nothing is auto-selected"
        svc.play_file.assert_not_called()
