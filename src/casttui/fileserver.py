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
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

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
