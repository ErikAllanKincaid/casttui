"""casttui Textual app — Milestone 3.

Three views cycled with Tab (SCOPE_CastTUI.md §6):

- **Devices**: discovered Chromecasts as clickable buttons + rescan.
- **Cast**: sources — a local-file browser (served over catt's HTTP server,
  see ``fileserver.py``) and a direct-URL field.
- **Now playing**: live progress bar, state + volume, and control buttons.

Blocking catt calls (discover, play_url, play_file, connect) run in threads via
``asyncio.to_thread`` so the UI never freezes. Status reaches the UI by a
0.25 s timer that reads :meth:`CastService.snapshot`, which the pychromecast
background thread keeps fresh.

Messages (info, warnings, errors) render on a persistent one-line bar above the
footer rather than as overlay toasts, so they never cover the controls.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    DirectoryTree,
    Footer,
    Header,
    Input,
    Static,
)

from .config import Config
from .media import has_ffmpeg, unsupported_warning
from .service import CastService, Status

VIEWS = ("devices", "cast", "nowplaying")
NARROW_WIDTH = 60  # columns below which the compact layout kicks in


def fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"


def progress_bar(position: float, duration: float | None, width: int = 40) -> str:
    """A plain-text bar; handles unknown duration gracefully."""
    if not duration or duration <= 0:
        return "─" * width  # stream with no known length
    filled = max(0, min(width, round(width * position / duration)))
    return "█" * filled + "░" * (width - filled)


def primary_selection() -> str:
    """The local PRIMARY selection (middle-click paste source), or ''.

    Only works when casttui runs on the same machine as the X/Wayland
    session that owns the selection. Over SSH the selection lives on the
    *client's* display, unreachable from here — use Shift+middle-click so
    the terminal itself pastes it (see the Cast-view hint). Tries X11
    (xclip/xsel) then Wayland (wl-paste), first non-empty result wins.
    """
    for cmd in (
        ["xclip", "-o", "-selection", "primary"],
        ["xsel", "-o", "-p"],
        ["wl-paste", "-p", "-n"],
    ):
        if shutil.which(cmd[0]):
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=1)
            except Exception:  # noqa: BLE001
                continue
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout
    return ""


class DevicesView(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Static("Devices", classes="view-title")
        yield Static("Scanning the network…", id="devices-status", markup=False)
        yield Vertical(id="device-list")
        yield Button("Rescan (r)", id="rescan", variant="primary")


class CastView(Vertical):
    def compose(self) -> ComposeResult:
        yield Static("Cast", classes="view-title")
        yield Static(
            "Pick a local file, or paste a URL — then a button: Cast URL "
            "(direct media), YouTube / site (yt-dlp), or Web page (show the "
            "site). Paste with Shift+Ctrl+V (clipboard) or Shift+middle-click "
            "(selection); plain middle-click only works running locally.",
            id="cast-hint",
            markup=False,
        )
        yield DirectoryTree(str(Path.home()), id="files")
        # Docked to the view bottom so they never scroll out of reach.
        with Vertical(id="cast-actions"):
            yield Input(
                placeholder="URL — Shift+Ctrl+V or Shift+middle-click to paste",
                id="url",
            )
            with Horizontal(id="url-row"):
                yield Button("Cast URL", id="cast-url", variant="primary")
                yield Button("YouTube / site", id="cast-stream")
                yield Button("Web page", id="cast-site")


class NowPlayingView(Vertical):
    def compose(self) -> ComposeResult:
        yield Static("Now playing", classes="view-title")
        # markup=False: titles / state text may contain "[" that Textual would
        # otherwise parse as console markup.
        with VerticalScroll(id="np-info"):
            yield Static("Nothing playing.", id="np-title", markup=False)
            yield Static("", id="np-bar", markup=False)
            yield Static("", id="np-state", markup=False)
        # Docked to the view bottom so the controls are always visible.
        with Horizontal(id="controls"):
            yield Button("⏮", id="rewind")
            yield Button("⏯", id="playpause")
            yield Button("⏹", id="stop")
            yield Button("⏭", id="ffwd")
            yield Button("🔉", id="voldown")
            yield Button("🔊", id="volup")
            yield Button("🔇", id="mute")
            yield Button("↦end", id="skip")


class CastTUI(App):
    CSS = """
    #body { height: 1fr; }
    #devices, #cast, #nowplaying { height: 100%; }
    .view-title { text-style: bold; color: $accent; padding: 1 0 0 1; }
    #devices-status, #cast-hint { padding: 0 1; color: $text-muted; }
    #device-list { padding: 1; height: auto; }
    #device-list Button { width: 100%; margin-bottom: 1; }
    #files { height: 1fr; margin: 1; border: round $panel; }
    #cast-actions { dock: bottom; height: auto; background: $surface; }
    #url { margin: 0 1; }
    #url-row { height: auto; padding: 0 1 1 1; }
    #url-row Button { margin-right: 1; }
    #np-info { height: 1fr; }
    #np-title { padding: 1 1 0 1; text-style: bold; }
    #np-bar { padding: 0 1; color: $success; }
    #np-state { padding: 0 1; color: $text-muted; }
    #controls { dock: bottom; height: auto; padding: 1; align: center middle;
                background: $surface; }
    #controls Button { margin: 0 1; min-width: 6; }
    #message { dock: bottom; height: 1; padding: 0 1; background: $panel;
               color: $text-muted; }

    /* Compact layout for narrow terminals: tighten the control row so the
       eight buttons still fit, and drop decorative padding. */
    .-narrow .view-title { padding: 0 0 0 1; }
    .-narrow #controls { padding: 1 0; }
    .-narrow #controls Button { min-width: 3; margin: 0; }
    .-narrow #files { margin: 0 1; }
    /* Stack the wide source buttons so they do not overflow a narrow width. */
    .-narrow #url-row { layout: vertical; height: auto; }
    .-narrow #url-row Button { width: 100%; margin: 0 0 1 0; }
    """

    BINDINGS = [
        Binding("tab", "switch_view", "Switch view", priority=True),
        ("r", "rescan", "Rescan"),
        ("space", "playpause", "Play/Pause"),
        ("left", "rewind", "Seek −"),
        ("right", "ffwd", "Seek +"),
        ("up", "volup", "Vol +"),
        ("down", "voldown", "Vol −"),
        ("plus", "volup", "Vol +"),
        ("minus", "voldown", "Vol −"),
        ("m", "mute", "Mute"),
        ("s", "stop", "Stop"),
        ("n", "skip", "Skip"),
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        service: CastService | None = None,
        config: Config | None = None,
    ) -> None:
        super().__init__()
        self.service = service or CastService()
        self.cfg = config or Config.load()
        self._view = "devices"
        self._muted = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="body"):
            yield DevicesView(id="devices")
            yield CastView(id="cast")
            yield NowPlayingView(id="nowplaying")
        yield Static("", id="message", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "casttui"
        self._show("devices")
        self.set_interval(0.25, self._refresh_now_playing)
        self.run_worker(self._scan(), exclusive=True)

    def on_unmount(self) -> None:
        self.service.close()

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < NARROW_WIDTH, "-narrow")

    # -- messages (persistent line, not overlay toasts) ------------------

    def message(self, text: str, error: bool = False) -> None:
        line = self.query_one("#message", Static)
        line.update(text)
        line.styles.color = "red" if error else None

    # -- view switching ---------------------------------------------------

    def _show(self, view: str) -> None:
        self._view = view
        for v in VIEWS:
            self.query_one(f"#{v}").display = v == view
        self.sub_title = view.replace("nowplaying", "now playing")

    def action_switch_view(self) -> None:
        self._show(VIEWS[(VIEWS.index(self._view) + 1) % len(VIEWS)])

    # -- discovery --------------------------------------------------------

    async def _scan(self) -> None:
        status = self.query_one("#devices-status", Static)
        status.update("Scanning the network…")
        try:
            devices = await asyncio.to_thread(self.service.discover)
        except Exception as exc:  # noqa: BLE001
            status.update(f"Discovery failed: {exc}")
            return
        lst = self.query_one("#device-list", Vertical)
        await lst.remove_children()
        if not devices:
            status.update("No Chromecasts found. Press r to rescan.")
            return
        status.update(f"{len(devices)} device(s) found — click one to select:")
        for d in devices:
            btn = Button(f"{d.name}  ({d.ip_addr})", classes="device")
            btn.cast_device = d  # type: ignore[attr-defined]
            await lst.mount(btn)
        # Auto-reconnect to the last-used device, but only on the first scan
        # (not on a manual rescan, which the user drives themselves).
        if self.service.device is None and self.cfg.last_device:
            match = next(
                (d for d in devices if d.name == self.cfg.last_device), None
            )
            if match is not None:
                await self._select(match, remembered=True)

    def action_rescan(self) -> None:
        self.run_worker(self._scan(), exclusive=True)

    async def _select(self, device, remembered: bool = False) -> None:
        try:
            await asyncio.to_thread(self.service.select, device)
        except Exception as exc:  # noqa: BLE001
            self.message(f"Could not connect: {exc}", error=True)
            return
        self.cfg.last_device = device.name
        self.cfg.save()
        verb = "Reconnected to" if remembered else "Connected to"
        self.message(f"{verb} {device.name}")
        self._show("cast")

    # -- casting ----------------------------------------------------------

    def _need_device(self) -> bool:
        if self.service.device is None:
            self.message("Select a device first (Tab → Devices).", error=True)
            self._show("devices")
            return False
        return True

    async def _cast_url(self) -> None:
        if not self._need_device():
            return
        url = self.query_one("#url", Input).value.strip()
        if not url:
            return
        self.message(f"Casting {url}")
        try:
            await asyncio.to_thread(self.service.play_url, url)
        except Exception as exc:  # noqa: BLE001
            self.message(f"Playback failed: {exc}", error=True)
            return
        self.query_one("#np-title", Static).update(url.rsplit("/", 1)[-1])
        self._show("nowplaying")

    async def _cast_stream(self) -> None:
        if not self._need_device():
            return
        url = self.query_one("#url", Input).value.strip()
        if not url:
            return
        self.message(f"Resolving {url}…")
        try:
            await asyncio.to_thread(self.service.play_stream, url)
        except Exception as exc:  # noqa: BLE001
            self.message(f"Could not play: {exc}", error=True)
            return
        self.message(f"Casting {url}")
        self._show("nowplaying")

    async def _cast_site(self) -> None:
        if not self._need_device():
            return
        url = self.query_one("#url", Input).value.strip()
        if not url:
            return
        self.message(f"Showing {url} as a web page…")
        try:
            await asyncio.to_thread(self.service.cast_site, url)
        except Exception as exc:  # noqa: BLE001
            self.message(f"Could not show page: {exc}", error=True)
            return
        self.query_one("#np-title", Static).update(url)
        self.query_one("#np-bar", Static).update("")
        self.query_one("#np-state", Static).update("WEB PAGE (no playback status)")
        self.message(f"Showing {url}")
        self._show("nowplaying")

    async def _cast_file(self, path: Path) -> None:
        if not self._need_device():
            return
        self.message(f"Serving and casting {path.name}…")
        try:
            title, warning, transcoded = await asyncio.to_thread(
                self._serve_file, str(path)
            )
        except Exception as exc:  # noqa: BLE001
            self.message(f"Playback failed: {exc}", error=True)
            return
        self.query_one("#np-title", Static).update(title or path.name)
        if transcoded:
            # VLC-style notice: conversion is CPU-heavy but works on a capable PC.
            self.message(f"Converting {path.name} on the fly (uses CPU) — casting")
        elif warning:
            self.message(f"{path.name}: {warning}", error=True)
        else:
            self.message(f"Casting {path.name}")
        self._show("nowplaying")

    def _serve_file(self, path: str) -> tuple[str, str | None, bool]:
        """Probe for an unplayable codec, then cast (runs off the UI thread).

        If the codec is unsupported and transcoding is enabled and ffmpeg is
        present, cast a live H.264 transcode instead of warning-and-skipping.
        """
        warning = unsupported_warning(path)
        transcode = bool(warning) and self.cfg.transcode and has_ffmpeg()
        title = self.service.play_file(path, transcode=transcode)
        return title, warning, transcode

    # -- live now-playing refresh ----------------------------------------

    def _refresh_now_playing(self) -> None:
        if self.service.device is None:
            return
        s = self.service.snapshot()
        bar = progress_bar(s.position, s.duration)
        self.query_one("#np-bar", Static).update(
            f"{bar}  {fmt_time(s.position)} / {fmt_time(s.duration)}"
        )
        if s.title:
            self.query_one("#np-title", Static).update(s.title)
        vol = f"{int(s.volume * 100)}%" if s.volume is not None else "--"
        mute = " (muted)" if s.muted else ""
        err = f"   ⚠ {s.error}" if s.error else ""
        self.query_one("#np-state", Static).update(
            f"{s.state}  ·  vol {vol}{mute}{err}"
        )
        self._muted = s.muted

    # -- playback actions (threaded; guard on no device) -----------------

    def _act(self, fn, *args) -> None:
        if self.service.device is None:
            self.message("No device selected.", error=True)
            return

        async def run():
            try:
                await asyncio.to_thread(fn, *args)
            except Exception as exc:  # noqa: BLE001
                self.message(f"{fn.__name__} failed: {exc}", error=True)

        self.run_worker(run())

    def action_playpause(self) -> None:
        state = self.service.snapshot().state
        self._act(self.service.pause if state == "PLAYING" else self.service.play)

    def action_rewind(self) -> None:
        self._act(self.service.rewind, self.cfg.seek_step)

    def action_ffwd(self) -> None:
        self._act(self.service.ffwd, self.cfg.seek_step)

    def action_volup(self) -> None:
        self._act(self.service.volumeup, self.cfg.volume_step)

    def action_voldown(self) -> None:
        self._act(self.service.volumedown, self.cfg.volume_step)

    def action_mute(self) -> None:
        self._act(self.service.mute, not self._muted)

    def action_stop(self) -> None:
        if self.service.device is None:
            self.message("No device selected.", error=True)
            return

        async def run():
            try:
                await asyncio.to_thread(self.service.stop)
            except Exception as exc:  # noqa: BLE001
                self.message(f"stop failed: {exc}", error=True)
                return
            self.query_one("#np-title", Static).update("Nothing playing.")
            self.query_one("#np-bar", Static).update("")
            self.query_one("#np-state", Static).update("")
            self.message("Stopped.")

        self.run_worker(run())

    def action_skip(self) -> None:
        dur = self.service.snapshot().duration
        if dur:
            self._act(self.service.seek, int(dur) - 1)

    # -- widget events ----------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn = event.button
        if getattr(btn, "cast_device", None) is not None:
            self.run_worker(self._select(btn.cast_device))
            return
        actions = {
            "rescan": self.action_rescan,
            "cast-url": lambda: self.run_worker(self._cast_url()),
            "cast-stream": lambda: self.run_worker(self._cast_stream()),
            "cast-site": lambda: self.run_worker(self._cast_site()),
            "rewind": self.action_rewind,
            "playpause": self.action_playpause,
            "stop": self.action_stop,
            "ffwd": self.action_ffwd,
            "voldown": self.action_voldown,
            "volup": self.action_volup,
            "mute": self.action_mute,
            "skip": self.action_skip,
        }
        action = actions.get(btn.id or "")
        if action:
            action()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "url":
            self.run_worker(self._cast_url())

    def on_directory_tree_file_selected(
        self, event: DirectoryTree.FileSelected
    ) -> None:
        self.run_worker(self._cast_file(Path(event.path)))

    def on_mouse_down(self, event: events.MouseDown) -> None:
        # Middle-click pastes the PRIMARY selection into the Input. Clicking a
        # focusable widget focuses it first, so self.focused is the Input here;
        # fall back to the widget under the pointer for the rare timing miss.
        if event.button != 2:
            return
        target = self.focused
        if not isinstance(target, Input):
            try:
                under = self.screen.get_widget_at(event.screen_x, event.screen_y)[0]
            except Exception:  # noqa: BLE001
                under = None
            target = under if isinstance(under, Input) else None
        if isinstance(target, Input):
            text = primary_selection().strip()
            if text:
                target.focus()
                target.insert_text_at_cursor(text)


def main() -> None:
    CastTUI().run()


if __name__ == "__main__":
    main()
