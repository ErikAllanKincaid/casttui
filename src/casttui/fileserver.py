"""A shutdownable ranged HTTP server for casting a single local file.

The Chromecast fetches media by URL, so a local file must be served over the
LAN for the life of the cast (SCOPE_CastTUI.md §8). catt ships this logic in
``catt.http_server.serve_file``, but that function builds its ``TCPServer``
internally and never returns it — so it cannot be stopped, only abandoned.
A long-lived TUI must tear the server down on stop, on switching media, and on
quit, so we own the ``TCPServer`` here and reuse catt's byte-range and
mime helpers for the fiddly part (SCOPE §12: reuse catt, do not reinvent).
"""
from __future__ import annotations

import socketserver
import subprocess
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import List, Optional

from catt.http_server import copy_byte_range, parse_byte_range
from catt.util import guess_mime


class _ThreadingTCPServer(socketserver.ThreadingTCPServer):
    # The Chromecast opens several parallel range connections; serve each on
    # its own thread. Reuse the address so a quick re-cast does not hit a
    # lingering TIME_WAIT socket.
    daemon_threads = True
    allow_reuse_address = True


class FileServer:
    """Serve one file with HTTP range support until :meth:`stop`."""

    def __init__(
        self,
        path: str,
        address: str,
        port: int,
        content_type: Optional[str] = None,
    ) -> None:
        self.path = Path(path)
        self.address = address
        self.port = port
        self.content_type = content_type or guess_mime(str(path))
        self.url = f"http://{address}:{port}/?loaded_from_casttui"
        self._httpd = _ThreadingTCPServer((address, port), self._make_handler())
        self._thread: Optional[threading.Thread] = None

    def _make_handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # silence stdout spam
                pass

            def do_GET(self) -> None:  # noqa: N802
                size = server.path.stat().st_size
                rng = self.headers.get("Range")
                if rng:
                    try:
                        first, last = parse_byte_range(rng)
                    except ValueError:
                        self.send_error(400, "Invalid byte range")
                        return
                else:
                    first, last = 0, size
                if last is None or last >= size:
                    last = size - 1
                length = last - first + 1
                try:
                    self.send_response(206 if rng else 200)
                    if rng:
                        self.send_header(
                            "Content-Range", f"bytes {first}-{last}/{size}"
                        )
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-type", server.content_type)
                    self.send_header("Content-Length", str(length))
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    with open(server.path, "rb") as f:
                        copy_byte_range(f, self.wfile, first, last)
                except (ConnectionResetError, BrokenPipeError):
                    # Normal when the Chromecast seeks, switches, or stops.
                    pass

        return Handler

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread:
            self._thread.join(timeout=2)


def ffmpeg_transcode_cmd(path: str, scale: Optional[int] = None) -> List[str]:
    """ffmpeg args to transcode ``path`` to a Chromecast-safe fragmented MP4
    on stdout (H.264 + AAC), streamable live over HTTP.

    ``scale`` (future resize option) caps the output height, preserving aspect
    (e.g. 720); None keeps the source resolution. Audio is re-encoded to AAC
    so odd source audio codecs never block playback. H.264 high-ish defaults;
    ``veryfast`` keeps 1080p real-time on a modern desktop CPU.
    """
    vfilter = ["-vf", f"scale=-2:{scale}"] if scale else []
    return [
        "ffmpeg", "-nostdin", "-loglevel", "error",
        "-i", str(path),
        "-map", "0:v:0", "-map", "0:a:0?",
        *vfilter,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-g", "60",
        "-c:a", "aac", "-b:a", "160k", "-ac", "2",
        "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "-f", "mp4", "pipe:1",
    ]


class TranscodeServer:
    """Stream a live ffmpeg transcode of one file over HTTP.

    For files the Chromecast cannot decode (AV1, HEVC, …), ffmpeg decodes on
    this host and emits H.264/AAC, exactly as a browser's tab-mirroring or
    VLC's conversion does — the device only ever receives a codec it supports.
    The stream is not seekable (no byte ranges, growing duration). ffmpeg is
    spawned per GET and all children are killed on :meth:`stop`.
    """

    def __init__(
        self, path: str, address: str, port: int, scale: Optional[int] = None
    ) -> None:
        self.path = Path(path)
        self.address = address
        self.port = port
        self.scale = scale
        self.url = f"http://{address}:{port}/stream.mp4"
        self._lock = threading.Lock()
        self._procs: List[subprocess.Popen] = []
        self._httpd = _ThreadingTCPServer((address, port), self._make_handler())
        self._thread: Optional[threading.Thread] = None

    def _make_handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            # HTTP/1.0 + no Content-Length: the client reads until we close,
            # which is how a live (unknown-length) stream is delivered.
            protocol_version = "HTTP/1.0"

            def log_message(self, *args) -> None:
                pass

            def do_GET(self) -> None:  # noqa: N802
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Accept-Ranges", "none")
                    self.end_headers()
                except (BrokenPipeError, ConnectionResetError):
                    return
                proc = subprocess.Popen(
                    ffmpeg_transcode_cmd(str(server.path), server.scale),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                with server._lock:
                    server._procs.append(proc)
                try:
                    assert proc.stdout is not None
                    while True:
                        buf = proc.stdout.read(65536)
                        if not buf:
                            break
                        self.wfile.write(buf)
                except (BrokenPipeError, ConnectionResetError):
                    # Chromecast stopped/seeked/switched — expected.
                    pass
                finally:
                    proc.kill()

        return Handler

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        with self._lock:
            for proc in self._procs:
                proc.kill()
            self._procs.clear()
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread:
            self._thread.join(timeout=2)
