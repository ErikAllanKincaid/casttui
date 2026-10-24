"""Service layer over ``catt.api``.

Owns the selected :class:`~catt.api.CattDevice`, exposes the playback actions
as thin synchronous wrappers (the caller decides threading — see ``app.py``'s
threaded workers), and bridges pychromecast's background-thread status pushes
into a thread-safe :class:`Status` holder with wall-clock position
interpolation for a smooth progress bar.

Every catt call here can block (connect, wait-for-state), so callers run them
off the UI thread. The status callback fires on pychromecast's thread; the UI
hops back with Textual's ``call_from_thread``.
"""
from __future__ import annotations

import ipaddress
import threading
import time
from dataclasses import dataclass, replace
from typing import Callable, List, Optional

from catt.api import CattDevice, discover
from catt.controllers import get_app, get_controller
from catt.stream_info import StreamInfo
from catt.util import guess_mime
from pychromecast.controllers.media import MediaStatusListener

from .fileserver import FileServer, TranscodeServer


@dataclass(frozen=True)
class Status:
    """A flattened, thread-safe snapshot of the receiver's media status."""

    state: str = "UNKNOWN"
    title: Optional[str] = None
    position: float = 0.0
    duration: Optional[float] = None
    volume: Optional[float] = None
    muted: bool = False
    error: Optional[str] = None


class _Listener(MediaStatusListener):
    """Forward pychromecast media-status pushes into a callback.

    pychromecast fires these on its own thread; the callback is responsible
    for crossing back to the UI thread.
    """

    def __init__(self, on_update: Callable[[Status], None]) -> None:
        self._on_update = on_update

    def new_media_status(self, status) -> None:
        self._on_update(
            Status(
                state=status.player_state or "UNKNOWN",
                title=status.title,
                position=status.current_time or 0.0,
                duration=status.duration,
                volume=status.volume_level,
                muted=status.volume_muted,
            )
        )

    def load_media_failed(self, item, error_code) -> None:
        self._on_update(
            Status(state="ERROR", error=f"load failed (code={error_code})")
        )


def is_address(text: str) -> bool:
    try:
        ipaddress.ip_address(text.strip())
    except ValueError:
        return False
    return True


def content_type(name: str) -> Optional[str]:
    """MIME type from a file name or URL path, or None (catt then says video/mp4).
    catt maps .webp to the non-type "image/web"; fixed here."""
    path = name.split("?")[0]
    if path.lower().endswith(".webp"):
        return "image/webp"
    return guess_mime(path)


def model_name(device: CattDevice) -> str:
    """The device model (e.g. "Chromecast"), or "" when unknown."""
    try:
        return device._cast.cast_info.model_name or ""
    except AttributeError:
        return ""


def served_url(service: "CastService") -> Optional[str]:
    server = service._fileserver
    return server.url if server is not None else None


class CastService:
    """Owns one selected device and brokers actions + status.

    The last :class:`Status` is held under a lock and refreshed on every push;
    :meth:`snapshot` interpolates the position to wall-clock ``now`` so the
    progress bar advances smoothly between pushes. An optional ``on_update``
    callback (set in :meth:`select`) also fires on every push for event-driven
    UI refreshes.
    """

    def __init__(self) -> None:
        self.device: Optional[CattDevice] = None
        self._listener: Optional[_Listener] = None
        self._on_update: Optional[Callable[[Status], None]] = None
        self._lock = threading.Lock()
        self._status = Status()
        self._updated_at = time.monotonic()
        self._fileserver: Optional[FileServer | TranscodeServer] = None

    # -- discovery / selection -------------------------------------------

    def discover(self) -> List[CattDevice]:
        """Blocking network scan. Run off the UI thread."""
        return discover()

    def connect(self, name_or_ip: str) -> CattDevice:
        """Reach one device directly, by address or by name. Blocking.

        An address skips discovery entirely, which is the way to reach a
        Chromecast mDNS can not see (another subnet, a VLAN, blocked multicast).
        """
        target = name_or_ip.strip()
        if is_address(target):
            return CattDevice(ip_addr=target)
        return CattDevice(name=target)

    def select(
        self, device: CattDevice, on_update: Optional[Callable[[Status], None]] = None
    ) -> None:
        """Make ``device`` current and register the status listener."""
        self.device = device
        self._on_update = on_update
        with self._lock:
            self._status = Status()
            self._updated_at = time.monotonic()
        self._listener = _Listener(self._handle_push)
        device._cast.media_controller.register_status_listener(self._listener)

    def _handle_push(self, status: Status) -> None:
        # ERROR pushes carry no title/volume; keep the last known good ones.
        with self._lock:
            if status.state == "ERROR":
                status = replace(status, title=self._status.title,
                                 volume=self._status.volume, muted=self._status.muted)
            self._status = status
            self._updated_at = time.monotonic()
        if self._on_update is not None:
            self._on_update(status)

    def snapshot(self) -> Status:
        """Latest status with position interpolated to wall-clock now."""
        with self._lock:
            s = self._status
            pos = s.position
            if s.state == "PLAYING":
                pos += time.monotonic() - self._updated_at
            if s.duration:
                pos = min(pos, s.duration)
            return replace(s, position=pos)

    # -- playback actions (thin wrappers; all may block) -----------------

    def play_url(self, url: str) -> None:
        # Switching media: drop any local-file server from a previous cast.
        self._stop_fileserver()
        self._cast(self._require(), url, content_type(url))

    @staticmethod
    def _cast(dev: CattDevice, url: str, ctype: Optional[str], title: Optional[str] = None) -> None:
        """Load ``url`` on the default media receiver with its real type.

        ``CattDevice.play_url`` always says video/mp4 and then waits for
        PLAYING, so a picture fails twice: the receiver is told it is a video,
        and a shown picture never reaches PLAYING. catt's own CLI passes the
        type and does not wait for images; so does this.
        """
        dev.controller.prep_app()
        dev.controller.play_media_url(url, content_type=ctype, title=title)
        if ctype and ctype.startswith("image/"):
            return
        if not dev.controller.wait_for(["PLAYING"], timeout=10):
            raise RuntimeError("the device did not start playing (format not supported?)")

    def play_file(
        self, path: str, transcode: bool = False, scale: Optional[int] = None
    ) -> str:
        """Serve ``path`` over the LAN and cast it. Returns the media title.

        With ``transcode``, ffmpeg re-encodes to Chromecast-safe H.264/AAC on
        the fly (for AV1/HEVC/etc. the device cannot decode); ``scale`` caps
        the output height. Otherwise the raw file is served with range support.

        Raises RuntimeError if the path is not a playable local file or if the
        host's LAN IP (reachable by the Chromecast) could not be determined.
        """
        dev = self._require()
        stream = StreamInfo(str(path), cast_info=dev._cast.cast_info)
        if not stream.is_local_file:
            raise RuntimeError("not a local file")
        if not stream.local_ip:
            raise RuntimeError(
                "could not find a LAN IP the Chromecast can reach "
                "(same subnet?)"
            )
        self._stop_fileserver()
        if transcode:
            server: FileServer | TranscodeServer = TranscodeServer(
                str(path), stream.local_ip, stream.port, scale
            )
        else:
            server = FileServer(
                str(path),
                stream.local_ip,
                stream.port,
                stream.guessed_content_type,
            )
        server.start()
        self._fileserver = server
        ctype = "video/mp4" if transcode else stream.guessed_content_type
        if ctype == "image/web":
            ctype = "image/webp"
        try:
            self._cast(dev, server.url, ctype, stream.video_title)
        except Exception:
            self._stop_fileserver()
            raise
        return stream.video_title

    def play_stream(self, url: str) -> None:
        """Cast a YouTube video or a yt-dlp-supported site URL.

        YouTube goes through the native YouTube receiver (full quality, and
        catt's ``best`` progressive format rarely exists on modern YouTube, so
        the resolve path fails with "No suitable format was found"). Other
        sites are resolved to a direct stream via yt-dlp and played on the
        default media receiver. The native YouTube *queue* is a later phase.
        """
        dev = self._require()
        self._stop_fileserver()
        stream = StreamInfo(url, cast_info=dev._cast.cast_info)
        if stream.extractor == "youtube":
            app = get_app("youtube", cast_type=dev._cast.cast_type)
            if app.name != "youtube":
                raise RuntimeError("this device does not support the YouTube app")
            ctrl = get_controller(dev._cast, app, action="play_media_id")
            if stream.is_playlist:
                ctrl.play_playlist(
                    stream.playlist_id,
                    video_id=stream.video_id or stream.playlist_all_ids[0],
                )
            else:
                ctrl.play_media_id(stream.video_id)
        else:
            dev.play_url(url, resolve=True)

    def cast_site(self, url: str) -> None:
        """Display an arbitrary web page on the device (DashCast)."""
        dev = self._require()
        self._stop_fileserver()
        app = get_app("dashcast", cast_type=dev._cast.cast_type)
        if app.name != "dashcast":
            raise RuntimeError("this device does not support casting web pages")
        ctrl = get_controller(dev._cast, app, action="load_url")
        ctrl.prep_app()
        ctrl.load_url(url)

    def _stop_fileserver(self) -> None:
        if self._fileserver is not None:
            self._fileserver.stop()
            self._fileserver = None

    def play(self) -> None:
        self._require().play()

    def pause(self) -> None:
        self._require().pause()

    def stop(self) -> None:
        self._require().stop()
        self._stop_fileserver()

    def close(self) -> None:
        """Release resources (the local-file server) on app shutdown."""
        self._stop_fileserver()

    def seek(self, seconds: int) -> None:
        self._require().seek(seconds)

    def ffwd(self, seconds: int = 10) -> None:
        self._require().ffwd(seconds)

    def rewind(self, seconds: int = 10) -> None:
        self._require().rewind(seconds)

    def volume(self, level: float) -> None:
        self._require().volume(max(0.0, min(1.0, level)))

    def volumeup(self, delta: float = 0.1) -> None:
        self._require().volumeup(delta)

    def volumedown(self, delta: float = 0.1) -> None:
        self._require().volumedown(delta)

    def mute(self, muted: bool) -> None:
        self._require().volumemute(muted)

    def _require(self) -> CattDevice:
        if self.device is None:
            raise RuntimeError("no device selected")
        return self.device
