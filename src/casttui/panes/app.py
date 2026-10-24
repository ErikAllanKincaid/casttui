"""The paned, keyboard-first casttui (urwid).

One screen of panes: Devices, Source, Now playing, Config, History. Every
action is a key (``keys.py``); the mouse only focuses a pane or a row, and a
double click acts on a row. The layout follows the terminal size: three
columns from 150 columns, two from 80, one pane at a time below that.

Blocking catt calls run on a small thread pool (:meth:`PanesApp.bg`); their
results come back to the UI thread through a queue drained by the main loop,
so widgets are only ever touched on the UI thread. Tests pass ``inline=True``
to run the same calls synchronously, then drive :meth:`press` and read
:meth:`screen_text`.
"""
from __future__ import annotations

import os
import queue
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import urwid

from .. import labels as lab
from ..cli import is_url
from ..config import Config
from ..media import has_ffmpeg, unsupported_warning
from ..service import CastService, content_type, is_address, model_name, served_url
from ..settings import BY_KEY, SETTINGS, parse, show
from .keys import PANES, bar_items, help_lines, keymap
from .widgets import PALETTE, ClickRow, Live, ListPane, Pane

# Direct media by extension goes straight to the default receiver; any other
# URL goes through yt-dlp (YouTube natively, other sites resolved).
MEDIA_EXT = (".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi", ".mp3", ".m4a",
             ".aac", ".flac", ".ogg", ".opus", ".wav", ".m3u8", ".mpd",
             ".jpg", ".jpeg", ".png", ".gif", ".webp")
WIDE, NARROW, SHORT = 150, 80, 18
MIN_OTHER = 6  # rows kept for Source/History beside a tall Now playing


@dataclass
class Playing:
    kind: str          # file, url, stream, page
    target: str        # path or URL
    title: str
    mode: str = ""     # direct, transcode 720p, yt-dlp, web page ...


@dataclass
class Entry:
    when: str
    text: str
    kind: str = ""     # file, url, page: recastable; "" is information only
    target: str = ""


def fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    s = int(seconds)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def human(n: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if n < 1024 or unit == "G":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return str(n)


def tilde(path: str) -> str:
    home = str(Path.home())
    return "~" + path[len(home):] if path.startswith(home + os.sep) else path


class PanesApp:
    def __init__(self, service: CastService | None = None, config: Config | None = None,
                 source: str | None = None, device: str | None = None,
                 env: dict | None = None, inline: bool = False) -> None:
        self.service = service or CastService()
        self.cfg = config or Config.load()
        self.env = dict(os.environ) if env is None else env
        self.source = source            # cast once a device is connected
        self.device_arg = device
        self.inline = inline
        self.found = []                 # discovered CattDevices
        self.scanning = False
        self.connecting = False
        self.playing: Playing | None = None
        self.history: list[Entry] = []
        self.show_hidden = False
        self.focus = 0
        self.zoom = False
        self.help_open = False
        self.prompt = None              # (caption, on_submit) while typing
        self.loop = None
        self.wake_fd = None
        self.pending: queue.Queue = queue.Queue()
        self.pool = None if inline else ThreadPoolExecutor(max_workers=4)
        self.keys, problems = keymap(self.cfg.keys)
        self.labels = lab.pick_icons(self.cfg.icons, self.env)
        self.depth = lab.pick_depth(self.cfg.colors, self.env)
        self.last_click = (None, None, 0.0)
        self.tab_spans = []
        self.bar = []                   # key bar segments: (text, action)
        self.button_click = False
        self.test_size = (120, 32)      # the size screen_text and tests assume
        self._build()
        if problems:
            self.say("; ".join(problems), error=True)
        else:
            self.say("Scanning for Chromecasts. ? shows every key.")
        start = Path(source).parent if source and not is_url(source) else (
            Path(self.cfg.start_dir).expanduser() if self.cfg.start_dir else Path.cwd())
        self.chdir(start if start.is_dir() else Path.cwd())

    # -- widgets -------------------------------------------------------------

    def _build(self) -> None:
        box = self.labels["box"]
        self.devices = ListPane()
        self.files = ListPane()
        self.where = urwid.Text("", wrap="clip")
        self.rule = urwid.Divider(box.get("tline", "\u2500"))
        self.source_buttons = ClickRow(lambda: [
            ("[u: URL or YouTube]", "url"), (" ", None), ("[w: web page]", "page")],
            self.button)
        source_body = urwid.Pile([("pack", self.where), ("pack", self.source_buttons),
                                  ("pack", self.rule), self.files], focus_item=3)
        self.np = Live(self.now_playing_text)
        self.np_details = Live(self.now_playing_details)
        self.controls = ClickRow(self.control_segments, self.button)
        self.np_pile = urwid.Pile([self.np, self.controls, self.np_details])
        self.config_list = ListPane()
        self.history_list = ListPane()
        self.panes = [
            Pane(1, "devices", "Devices", self.devices, box),
            Pane(2, "source", "Source", source_body, box),
            Pane(3, "nowplaying", "Now playing", urwid.Filler(self.np_pile, valign="top"), box),
            Pane(4, "config", "Config", self.config_list, box),
            Pane(5, "history", "History", self.history_list, box),
        ]
        self.message = urwid.Text("", wrap="clip")
        self.keybar = urwid.Text("", wrap="clip")
        self.edit = urwid.Edit()
        self.footer = urwid.Pile([self.message, urwid.AttrMap(self.keybar, "key")])
        self.body = Responsive(self)
        self.frame = urwid.Frame(self.body, footer=self.footer)
        self.top = Top(self)
        self.refresh_devices()
        self.refresh_config()
        self.refresh_history()
        self.layout()

    def layout(self) -> None:
        for n, p in enumerate(self.panes):
            p.set_focus(n == self.focus)
        if self.prompt is None:
            self.bar = [(" ", None), *bar_items(self.keys, PANES[self.focus])]
            self.keybar.set_text("".join(t for t, _ in self.bar))
        self.body._invalidate()

    def build(self, cols: int, rows_: int):
        """The body widget for this size, with urwid focus on our pane."""
        i = self.focus
        if self.help_open:
            text = urwid.Text("\n".join(help_lines(self.keys) + ["", "Any key closes this help."]))
            return urwid.LineBox(urwid.Filler(text, "top"), title="help", **self.labels["box"])
        if cols < NARROW or rows_ < SHORT or self.zoom:
            spans, tabs, x = [], [], 0
            for n, p in enumerate(self.panes):
                label = f" {p.num} {p.title} "
                tabs.append(("frame_focus" if n == i else "frame", label))
                spans.append((x, x + len(label), n))
                x += len(label)
            self.tab_spans = spans
            return urwid.Pile([("pack", urwid.Text(tabs, wrap="clip")), self.panes[i]],
                              focus_item=1)
        self.tab_spans = []
        dev_h = min(len(self.devices.body) + 2, max(4, rows_ // 3))
        left = urwid.Pile([(dev_h, self.panes[0]), self.panes[3]])
        # Now playing is as tall as what it shows; the pane above or below it
        # (Source, History) gets the rest but keeps at least MIN_OTHER rows.
        left_w = max(30, min(44, cols // 3))
        np_w = (60 if cols >= WIDE else cols - left_w) - 2
        np_h = max(5, min(self.np_pile.rows((np_w,)) + 2, rows_ - MIN_OTHER))
        if cols >= WIDE:
            right = urwid.Pile([(np_h, self.panes[2]), self.panes[4]])
            cols_w = urwid.Columns([(58, left), self.panes[1], (60, right)])
            where = {0: (0, 0), 3: (0, 1), 1: (1, None), 2: (2, 0), 4: (2, 1)}
        else:
            if i == 4:  # History has no room at this width: show it alone
                return self.panes[4]
            right = urwid.Pile([self.panes[1], (np_h, self.panes[2])])
            cols_w = urwid.Columns([(left_w, left), right])
            where = {0: (0, 0), 3: (0, 1), 1: (1, 0), 2: (1, 1)}
        col, row = where[i]
        cols_w.focus_position = col
        if row is not None:
            cols_w.contents[col][0].focus_position = row
        return cols_w

    # -- pane contents ---------------------------------------------------------

    def refresh_devices(self) -> None:
        cur = self.service.device
        cur_ip = getattr(cur, "ip_addr", None)
        items, seen = [], set()
        for d in self.found:
            seen.add(d.ip_addr)
            mark = "*" if d.ip_addr == cur_ip else " "
            saved = " saved" if d.ip_addr in self.cfg.devices else ""
            items.append((f"{mark} {d.name:<18} {d.ip_addr:<16} {model_name(d)}{saved}", ("dev", d)))
        for ip in self.cfg.devices:
            if ip in seen:
                continue
            if cur is not None and ip == cur_ip:
                items.append((f"* {cur.name:<18} {ip:<16} {model_name(cur)} saved", ("dev", cur)))
            else:
                items.append((f"  {'(saved address)':<18} {ip:<16} not seen in scan", ("ip", ip)))
        if cur is not None and cur_ip not in seen and cur_ip not in self.cfg.devices:
            items.append((f"* {cur.name:<18} {cur_ip:<16} {model_name(cur)}", ("dev", cur)))
        items.append(("  + add by address (a)", ("add", None)))
        self.devices.set_items(items)
        self.panes[0].set_note("scanning" if self.scanning else
                               "connecting" if self.connecting else "")

    def chdir(self, path: Path, select: str | None = None) -> None:
        path = path.resolve()
        try:
            names = sorted(os.listdir(path), key=str.lower)
        except OSError as exc:
            self.say(f"Can not open {path}: {exc.strerror}", error=True)
            return
        self.cwd = path
        if not self.show_hidden:
            names = [n for n in names if not n.startswith(".")]
        dirs, files = [], []
        for n in names:
            p = path / n
            (dirs if p.is_dir() else files).append(p)
        items = [("../", ("dir", path.parent))] if path.parent != path else []
        items += [(f"{p.name}/", ("dir", p)) for p in dirs]
        for p in files:
            try:
                size = human(p.stat().st_size)
            except OSError:
                size = "?"
            items.append((f"{p.name:<40} {size:>7}", ("file", p)))
        self.files.set_items(items, keep=False)
        if select:
            self.files.select(("dir", path / select))
        self.where.set_text(tilde(str(path)))

    def now_playing_text(self, cols: int):
        dev = self.service.device
        if dev is None:
            return [("dim", "No device. 1 opens Devices, a adds one by address.")]
        if self.playing is None:
            return [f"Connected to {dev.name}.\n\n", ("dim", "Nothing playing. 2 opens Source, u casts a URL.")]
        p = self.playing
        if p.kind == "page":
            return [f"{p.title}\n", ("state", "WEB PAGE"), "   (no playback status)\n\n",
                    f"device  {dev.name}\nshown   {p.target}"]
        s = self.service.snapshot()
        vol = f"vol {int(s.volume * 100)}%" if s.volume is not None else "vol --"
        vol += " (muted)" if s.muted else ""
        times = f"  {fmt_time(s.position)} / {fmt_time(s.duration)}"
        width = max(10, cols - len(times) - 2)
        return [f"{s.title or p.title}\n", ("state", f"{s.state:<10}"), f" {vol}\n\n",
                f"[{lab.bar(self.labels, s.position, s.duration, width)}]{times}"]

    def now_playing_details(self, cols: int):
        dev, p = self.service.device, self.playing
        if dev is None or p is None or p.kind == "page":
            return ""
        s = self.service.snapshot()
        out = [f"\ndevice  {dev.name} {model_name(dev)}\n",
               f"source  {tilde(p.target)}\n",
               f"mode    {p.mode}"]
        url = served_url(self.service)
        if url:
            out.append(f"\nserved  {url}")
        if s.error:
            out.append(("error", f"\nERROR: {s.error}"))
        return out

    def control_segments(self) -> list:
        """The clickable transport row under the progress bar. Always shown
        with a device, so the mouse can play, stop and change the volume."""
        if self.service.device is None:
            return []
        playing = self.service.snapshot().state == "PLAYING"
        seg = [("[<<]", "rewind"), (" ", None), ("[pause]" if playing else "[play]", "playpause"),
               (" ", None), ("[>>]", "ffwd"), (" ", None), ("[stop]", "stop"), (" ", None),
               ("[>|]", "skip"), (" vol", None), ("[-]", "voldown"),
               ("[+]", "volup"), (" ", None), ("[mute]", "mute")]
        return seg

    def refresh_config(self) -> None:
        items = []
        for s in SETTINGS:
            value = show(getattr(self.cfg, s.key))
            items.append((f"{s.key:<16}{value:<15} {s.help}", s.key))
        self.config_list.set_items(items)

    def refresh_history(self) -> None:
        items = [(f"{e.when}  {e.text}", i) for i, e in enumerate(self.history)]
        self.history_list.set_items(items or [("(nothing yet)", None)])

    def note(self, text: str, kind: str = "", target: str = "") -> None:
        self.history.insert(0, Entry(time.strftime("%H:%M"), text, kind, target))
        del self.history[200:]
        self.refresh_history()

    def say(self, text: str, error: bool = False) -> None:
        self.message.set_text(("error", f"ERROR: {text}") if error else ("msg", text))

    # -- threads -----------------------------------------------------------------

    def bg(self, fn, *args, done=None, fail: str = "Failed", always=None) -> None:
        """Run a blocking call off the UI thread; ``done(result)`` or the
        error message, then ``always()``, run back on the UI thread."""
        def work():
            try:
                result = fn(*args)
            except Exception as exc:  # noqa: BLE001
                text = f"{fail}: {exc}"  # exc is unbound once the block ends
                self.post(lambda: self.say(text, error=True))
                if always:
                    self.post(always)
                return
            if done:
                self.post(lambda: done(result))
            if always:
                self.post(always)
        if self.pool is None:
            work()
        else:
            self.pool.submit(work)

    def post(self, callback) -> None:
        self.pending.put(callback)
        if self.pool is None:
            self.drain()
        elif self.wake_fd is not None:
            try:
                os.write(self.wake_fd, b"x")
            except OSError:
                pass

    def drain(self, _data=None) -> bool:
        while True:
            try:
                callback = self.pending.get_nowait()
            except queue.Empty:
                break
            callback()
        self.layout()
        return True

    # -- devices -------------------------------------------------------------------

    def start(self) -> None:
        """Connect to --device or a remembered address, and scan."""
        target = self.device_arg or (self.cfg.last_device if is_address(self.cfg.last_device or "") else None)
        if target:
            self.connect_to(target, by_address=is_address(target))
        self.scan()

    def scan(self) -> None:
        if self.scanning:
            return
        self.scanning = True
        self.refresh_devices()

        def done(found):
            self.found = found
            n = len(found)
            self.say(f"{n} Chromecast{'s' if n != 1 else ''} found." if n else
                     "No Chromecasts found. a adds one by address, r scans again.")
            self.note(f"scan: {n} found")
            if self.service.device is None and not self.connecting:
                match = next((d for d in found if d.name == self.cfg.last_device), None)
                if match is None and self.source and n == 1:
                    match = found[0]
                if match is not None:
                    self.select(match, remembered=match.name == self.cfg.last_device)
                elif self.source and n:
                    self.say(f"{n} found: pick one (enter) to cast {Path(self.source).name}.")

        def always():
            self.scanning = False
            self.refresh_devices()

        self.bg(self.service.discover, done=done, fail="Scan failed", always=always)

    def connect_to(self, target: str, by_address: bool = True) -> None:
        self.connecting = True
        self.refresh_devices()
        self.say(f"Connecting to {target}...")

        def always():
            self.connecting = False
            self.refresh_devices()

        self.bg(self.service.connect, target, fail=f"Could not reach {target}", always=always,
                done=lambda dev: self.select(dev, by_address=by_address))

    def select(self, device, remembered: bool = False, by_address: bool = False) -> None:
        def done(_):
            # A device reached by address is remembered by address, so the
            # next start connects to it without needing discovery.
            self.cfg.last_device = device.ip_addr if by_address else device.name
            self.cfg.save()
            self.say(f"{'Reconnected to' if remembered else 'Connected to'} {device.name}.")
            self.note(f"connected {device.name} ({device.ip_addr})")
            self.refresh_devices()
            if self.focus == 0:
                self.focus = 1
            self.run_source()

        self.bg(self.service.select, device, done=done, fail=f"Could not connect to {device.name}")

    def act_connect(self) -> None:
        value = self.devices.current()
        if value is None:
            return
        kind, thing = value
        if kind == "add":
            self.act_add_ip()
        elif kind == "ip":
            self.connect_to(thing)
        else:
            self.select(thing)

    def act_add_ip(self) -> None:
        def submit(text):
            ip = text.strip()
            if not is_address(ip):
                self.say(f"Not an address: {ip!r} (like 192.168.1.50)", error=True)
                return
            if ip not in self.cfg.devices:
                self.cfg.devices = [*self.cfg.devices, ip]
                self.cfg.save()
                self.refresh_config()
            self.refresh_devices()
            self.connect_to(ip)

        self.ask("address: ", submit)

    def act_forget(self) -> None:
        value = self.devices.current()
        ip = value[1] if value and value[0] == "ip" else getattr(value[1], "ip_addr", None) if value else None
        if ip not in self.cfg.devices:
            self.say("Only saved addresses can be forgotten.", error=True)
            return
        self.cfg.devices = [d for d in self.cfg.devices if d != ip]
        self.cfg.save()
        self.say(f"Forgot {ip}.")
        self.refresh_devices()
        self.refresh_config()

    # -- casting ---------------------------------------------------------------------

    def need_device(self) -> bool:
        if self.service.device is None:
            self.say("No device: pick one in Devices (1) or add one by address (a).", error=True)
            self.focus = 0
            return False
        return True

    def run_source(self) -> None:
        source, self.source = self.source, None
        if source:
            self.cast(source)

    def cast(self, target: str) -> None:
        if is_url(target):
            self.cast_url(target)
        else:
            self.cast_file(Path(target))

    def cast_file(self, path: Path) -> None:
        if not self.need_device():
            return
        self.say(f"Serving and casting {path.name}...")

        def work():
            warning = unsupported_warning(str(path))
            transcode = bool(warning) and self.cfg.transcode and has_ffmpeg()
            scale = self.cfg.transcode_scale or None
            title = self.service.play_file(str(path), transcode=transcode, scale=scale)
            return title, warning, transcode

        def done(result):
            title, warning, transcode = result
            mode = (f"transcode {self.cfg.transcode_scale}p" if transcode and self.cfg.transcode_scale
                    else "transcode" if transcode
                    else "picture" if (content_type(path.name) or "").startswith("image/")
                    else "direct")
            self.started(Playing("file", str(path), title or path.name, mode))
            self.note(f"cast {path.name}" + (" (transcode)" if transcode else ""), "file", str(path))
            if transcode:
                self.say(f"Converting {path.name} on the fly (uses CPU), casting.")
            elif warning:
                self.say(f"{path.name}: {warning}", error=True)
            else:
                self.say(f"Casting {path.name}.")

        self.bg(work, done=done, fail="Playback failed")

    def cast_url(self, url: str) -> None:
        if not self.need_device():
            return
        direct = url.lower().split("?")[0].endswith(MEDIA_EXT)
        self.say(f"{'Casting' if direct else 'Resolving'} {url}...")
        fn = self.service.play_url if direct else self.service.play_stream

        def done(_):
            self.started(Playing("url", url, url.rstrip("/").rsplit("/", 1)[-1],
                                 "direct URL" if direct else "yt-dlp / YouTube"))
            self.note(f"cast {url}", "url", url)
            self.say(f"Casting {url}.")

        self.bg(fn, url, done=done, fail="Could not play")

    def cast_page(self, url: str) -> None:
        if not self.need_device():
            return
        self.say(f"Showing {url} as a web page...")

        def done(_):
            self.started(Playing("page", url, url, "web page"))
            self.note(f"page {url}", "page", url)
            self.say(f"Showing {url}.")

        self.bg(self.service.cast_site, url, done=done, fail="Could not show page")

    def started(self, playing: Playing) -> None:
        self.playing = playing
        # One pane at a time: show what is now playing.
        if self.single_pane():
            self.focus = 2

    def single_pane(self) -> bool:
        cols, rows_ = self.size()
        return cols < NARROW or rows_ < SHORT or self.zoom

    def size(self) -> tuple[int, int]:
        if self.loop is not None:
            return self.loop.screen.get_cols_rows()
        return self.test_size

    # -- playback ----------------------------------------------------------------

    def act(self, fn, *args, done=None) -> None:
        if not self.need_device():
            return
        self.bg(fn, *args, done=done, fail=f"{getattr(fn, '__name__', 'action')} failed")

    def act_playpause(self) -> None:
        playing = self.service.snapshot().state == "PLAYING"
        self.act(self.service.pause if playing else self.service.play)

    def act_stop(self) -> None:
        def done(_):
            if self.playing:
                self.note(f"stop {Path(self.playing.target).name}")
            self.playing = None
            self.say("Stopped.")
        self.act(self.service.stop, done=done)

    def act_skip(self) -> None:
        dur = self.service.snapshot().duration
        if dur:
            self.act(self.service.seek, int(dur) - 1)

    # -- config ------------------------------------------------------------------

    def set_setting(self, key: str, value) -> None:
        setattr(self.cfg, key, value)
        self.cfg.save()
        self.apply(key)
        self.refresh_config()
        self.say(f"{key} = {show(value)} (saved)")

    def apply(self, key: str) -> None:
        if key == "icons":
            self.labels = lab.pick_icons(self.cfg.icons, self.env)
            for p in self.panes:
                p.relabel(self.labels["box"])
            self.rule.div_char = self.labels["box"].get("tline", "\u2500")
            self.rule._invalidate()
        elif key == "colors":
            self.depth = lab.pick_depth(self.cfg.colors, self.env)
            if self.loop is not None:
                self.loop.screen.set_terminal_properties(colors=self.depth)
                self.loop.screen.register_palette(PALETTE)
                self.loop.screen.clear()
        elif key == "ui":
            self.say("ui takes effect at the next start.")

    def cycle(self, step: int) -> None:
        key = self.config_list.current()
        s = BY_KEY.get(key)
        if s is None:
            return
        if not s.choices:
            self.change()
            return
        values = list(s.choices)
        cur = getattr(self.cfg, key)
        i = values.index(cur) if cur in values else -1
        self.set_setting(key, values[(i + step) % len(values)])

    def change(self) -> None:
        key = self.config_list.current()
        s = BY_KEY.get(key)
        if s is None:
            return
        if s.choices:
            self.cycle(1)
        elif not s.editable:
            where = {"devices": "Devices: a adds, d forgets", "last_device": "set on connect",
                     "keys": "edit [keys] in config.toml"}.get(key, "")
            self.say(f"{key} is not edited here ({where}).")
        else:
            self.ask(f"{key}: ", lambda text: self.set_typed(key, text),
                     str(getattr(self.cfg, key) or ""))

    def set_typed(self, key: str, text: str) -> None:
        try:
            value = parse(BY_KEY[key], text)
        except ValueError as exc:
            self.say(str(exc), error=True)
            return
        self.set_setting(key, value)

    # -- prompt and commands --------------------------------------------------------

    def ask(self, caption: str, on_submit, text: str = "") -> None:
        self.prompt = (caption, on_submit)
        self.edit.set_caption(("prompt", caption))
        self.edit.set_edit_text(text)
        self.edit.set_edit_pos(len(text))
        self.footer.contents[1] = (self.edit, ("pack", None))
        self.footer.focus_position = 1
        self.frame.focus_position = "footer"

    def end_prompt(self, submit: bool) -> None:
        _, on_submit = self.prompt
        text = self.edit.get_edit_text()
        self.prompt = None
        self.footer.contents[1] = (urwid.AttrMap(self.keybar, "key"), ("pack", None))
        self.frame.focus_position = "body"
        if submit and text.strip():
            on_submit(text)
        self.layout()

    def command(self, text: str) -> None:
        word, _, rest = text.strip().partition(" ")
        rest = rest.strip()
        if word == "set":
            key, _, value = rest.partition(" ")
            if key not in BY_KEY or not BY_KEY[key].editable:
                self.say(f"No setting {key!r} to set. See the Config pane (4).", error=True)
            else:
                self.set_typed(key, value)
        elif word == "cast" and rest:
            self.cast(rest if is_url(rest) else str(Path(rest).expanduser()))
        elif word == "page" and rest:
            self.cast_page(rest)
        elif word == "connect" and rest:
            self.connect_to(rest, by_address=is_address(rest))
        elif word == "scan":
            self.scan()
        elif word in ("help", "?"):
            self.help_open = True
        elif word in ("q", "quit"):
            self.quit()
        else:
            self.say("Commands: set KEY VALUE, cast PATH|URL, page URL, connect NAME|IP, scan, quit",
                     error=True)

    # -- keys --------------------------------------------------------------------

    def press(self, key: str) -> None:
        """Handle one key (also the test entry point)."""
        if self.prompt is not None:
            if key == "enter":
                self.end_prompt(True)
            elif key == "esc":
                self.end_prompt(False)
            else:
                self.edit.keypress((200,), key)
            return
        if self.help_open:
            self.help_open = False
            self.layout()
            return
        pane = PANES[self.focus]
        action = self.keys.get(pane, {}).get(key) or self.keys["global"].get(key)
        if action is None:
            nav = {"j": "down", "k": "up"}.get(key, key)
            if nav in ("up", "down", "page up", "page down", "home", "end"):
                self.body.keypress(self.size(), nav)
            return
        self.run_action(action)

    def run_action(self, action: str) -> None:
        getattr(self, "do_" + action)()
        self.layout()

    def click_bar(self, col: int) -> None:
        """A click on the key bar runs the action under the pointer."""
        x = 0
        for text, action in self.bar:
            if x <= col < x + len(text):
                if action is not None:
                    self.run_action(action)
                return
            x += len(text)

    def do_focus_devices(self): self.focus = 0
    def do_focus_source(self): self.focus = 1
    def do_focus_nowplaying(self): self.focus = 2
    def do_focus_config(self): self.focus = 3
    def do_focus_history(self): self.focus = 4
    def do_next_pane(self): self.focus = (self.focus + 1) % len(PANES)
    def do_prev_pane(self): self.focus = (self.focus - 1) % len(PANES)
    def do_zoom(self): self.zoom = not self.zoom
    def do_help(self): self.help_open = True
    def do_playpause(self): self.act_playpause()
    def do_rewind(self): self.act(self.service.rewind, self.cfg.seek_step)
    def do_ffwd(self): self.act(self.service.ffwd, self.cfg.seek_step)
    def do_volup(self): self.act(self.service.volumeup, self.cfg.volume_step)
    def do_voldown(self): self.act(self.service.volumedown, self.cfg.volume_step)
    def do_mute(self): self.act(self.service.mute, not self.service.snapshot().muted)
    def do_stop(self): self.act_stop()
    def do_skip(self): self.act_skip()
    def do_url(self): self.ask("URL or YouTube link (paste, enter casts, esc cancels): ",
                               lambda t: self.cast_url(t.strip()))
    def do_page(self): self.ask("web page to show (enter, esc cancels): ",
                                lambda t: self.cast_page(t.strip()))
    def do_command(self): self.ask(":", self.command)
    def do_quit(self): self.quit()
    def do_stop_quit(self): self.quit(stop=True)
    def do_connect(self): self.act_connect()
    def do_rescan(self): self.scan()
    def do_add_ip(self): self.act_add_ip()
    def do_forget(self): self.act_forget()
    def do_change(self): self.change()
    def do_next_value(self): self.cycle(1)
    def do_prev_value(self): self.cycle(-1)

    def do_open(self) -> None:
        value = self.files.current()
        if value is None:
            return
        kind, path = value
        if kind == "dir":
            came_from = self.cwd.name if path == self.cwd.parent else None
            self.chdir(path, select=came_from)
        else:
            self.cast_file(path)

    def do_parent(self) -> None:
        if self.cwd.parent != self.cwd:
            self.chdir(self.cwd.parent, select=self.cwd.name)

    def do_hidden(self) -> None:
        self.show_hidden = not self.show_hidden
        self.chdir(self.cwd)
        self.say("Showing dot files." if self.show_hidden else "Hiding dot files.")

    def do_recast(self) -> None:
        i = self.history_list.current()
        if i is None:
            return
        e = self.history[i]
        if e.kind == "file":
            self.cast_file(Path(e.target))
        elif e.kind == "url":
            self.cast_url(e.target)
        elif e.kind == "page":
            self.cast_page(e.target)
        else:
            self.say("Nothing to cast again in this entry.")

    def do_delete(self) -> None:
        i = self.history_list.current()
        if i is not None:
            del self.history[i]
            self.refresh_history()

    # -- mouse -----------------------------------------------------------------

    def button(self, action: str) -> None:
        """A ClickRow button: run it, and tell :meth:`clicked` this click is
        not half of a double click on a list row."""
        self.button_click = True
        self.run_action(action)

    def clicked(self, col: int, row: int) -> None:
        """After urwid moved its focus for a click: follow it to our pane,
        and treat a second click on the same row as Enter."""
        if self.tab_spans and row == 0:
            for a, b, n in self.tab_spans:
                if a <= col < b:
                    self.focus = n
            self.layout()
            return
        w = self.body.current
        while w is not None and not isinstance(w, Pane):
            w = getattr(w, "focus", None)
        if isinstance(w, Pane):
            self.focus = self.panes.index(w)
        pane = PANES[self.focus]
        lists = {"devices": self.devices, "source": self.files, "config": self.config_list,
                 "history": self.history_list}
        lst = lists.get(pane)
        if self.button_click:
            self.button_click = False
            self.last_click = (None, None, 0.0)
            self.layout()
            return
        value = lst.current() if lst is not None else None
        now = time.monotonic()
        last_pane, last_value, last_t = self.last_click
        if lst is not None and (pane, value) == (last_pane, last_value) and now - last_t < 0.5:
            self.last_click = (None, None, 0.0)
            self.press("enter")
            return
        self.last_click = (pane, value, now)
        self.layout()

    # -- run -------------------------------------------------------------------

    def screen_text(self, cols: int = 120, rows_: int = 32) -> list[str]:
        """The whole screen as text (tests)."""
        self.test_size = (cols, rows_)
        canvas = self.frame.render((cols, rows_), focus=True)
        return [line.decode("utf-8") for line in canvas.text]

    def quit(self, stop: bool = False) -> None:
        if stop and self.service.device is not None:
            try:
                if self.pool is None:
                    self.service.stop()
                else:
                    self.pool.submit(self.service.stop).result(timeout=8)
            except Exception:  # noqa: BLE001
                pass
            self.playing = None
        raise urwid.ExitMainLoop()

    def tick(self, loop=None, _data=None) -> None:
        if self.playing is not None:
            self.np._invalidate()
            self.controls._invalidate()
            self.np_details._invalidate()
        if loop is not None:
            loop.set_alarm_in(0.5, self.tick)

    def run(self) -> None:
        self.loop = urwid.MainLoop(self.top, PALETTE, handle_mouse=True)
        self.loop.screen.set_terminal_properties(colors=self.depth)
        self.wake_fd = self.loop.watch_pipe(self.drain)
        self.loop.set_alarm_in(0.5, self.tick)
        self.start()
        try:
            self.loop.run()
        finally:
            playing = self.playing
            self.service.close()
            if self.pool is not None:
                self.pool.shutdown(wait=False, cancel_futures=True)
            dev = self.service.device
            if playing is not None and dev is not None:
                note = (" A local file is no longer served, so it stops once the device's buffer runs out."
                        if playing.kind == "file" else "")
                print(f"casttui: {playing.title} continues on {dev.name}.{note}")


class Responsive(urwid.Widget):
    """Builds the layout for the size it is given, at every render."""
    _sizing = frozenset(["box"])
    _selectable = True

    def __init__(self, app: PanesApp):
        super().__init__()
        self.app = app
        self.current = None

    def _for(self, size):
        self.current = self.app.build(*size)
        return self.current

    def render(self, size, focus=False):
        return self._for(size).render(size, focus)

    def keypress(self, size, key):
        return self._for(size).keypress(size, key)

    def mouse_event(self, size, event, button, col, row, focus):
        return self._for(size).mouse_event(size, event, button, col, row, focus)


class Top(urwid.WidgetWrap):
    """Every key goes to :meth:`PanesApp.press`; mouse events go to urwid,
    then the app follows the new focus."""

    def __init__(self, app: PanesApp):
        self.app = app
        super().__init__(app.frame)

    def keypress(self, size, key):
        self.app.press(key)
        return None

    def mouse_event(self, size, event, button, col, row, focus):
        press = event == "mouse press" and button == 1
        if press and row == size[1] - 1 and self.app.prompt is None:
            self.app.click_bar(col)
            return True
        if press and self.app.help_open:
            self.app.press("esc")  # any click closes the help, like any key
            return True
        handled = self.app.frame.mouse_event(size, event, button, col, row, focus)
        if press and row < size[1] - 2:
            self.app.clicked(col, row)
        return handled


def run(config: Config | None = None, source: str | None = None, device: str | None = None) -> None:
    PanesApp(config=config, source=source, device=device).run()
