"""FileServer: real HTTP range requests against a temp file."""
from __future__ import annotations

import urllib.request

from casttui.fileserver import FileServer


def _get(url: str, rng: str | None = None):
    req = urllib.request.Request(url)
    if rng:
        req.add_header("Range", rng)
    with urllib.request.urlopen(req, timeout=3) as r:
        return r.status, r.headers, r.read()


def test_serves_whole_file(tmp_path):
    f = tmp_path / "clip.mp4"
    data = b"0123456789" * 100
    f.write_bytes(data)
    srv = FileServer(str(f), "127.0.0.1", 46555)
    srv.start()
    try:
        status, headers, body = _get(srv.url)
        assert status == 200
        assert body == data
        assert headers["Content-type"] == "video/mp4"
        assert headers["Content-Length"] == str(len(data))
    finally:
        srv.stop()


def test_serves_byte_range(tmp_path):
    f = tmp_path / "clip.bin"
    f.write_bytes(bytes(range(256)))
    srv = FileServer(str(f), "127.0.0.1", 46556)
    srv.start()
    try:
        status, headers, body = _get(srv.url, rng="bytes=10-19")
        assert status == 206
        assert body == bytes(range(10, 20))
        assert headers["Content-Range"] == "bytes 10-19/256"
    finally:
        srv.stop()


def test_stop_frees_the_port(tmp_path):
    f = tmp_path / "x.mp3"
    f.write_bytes(b"hi")
    srv = FileServer(str(f), "127.0.0.1", 46557)
    srv.start()
    srv.stop()
    # Re-binding the same port must succeed once stopped.
    srv2 = FileServer(str(f), "127.0.0.1", 46557)
    srv2.start()
    srv2.stop()
