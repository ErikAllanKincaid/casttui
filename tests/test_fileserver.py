"""FileServer / TranscodeServer: real HTTP against temp files."""
from __future__ import annotations

import shutil
import subprocess
import urllib.request

import pytest

from casttui.fileserver import FileServer, TranscodeServer, ffmpeg_transcode_cmd


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


def test_ffmpeg_cmd_basic():
    cmd = ffmpeg_transcode_cmd("/x.mkv")
    assert cmd[0] == "ffmpeg"
    assert "libx264" in cmd and "pipe:1" in cmd
    assert "-vf" not in cmd  # no scaling by default


def test_ffmpeg_cmd_scale():
    cmd = ffmpeg_transcode_cmd("/x.mkv", scale=720)
    i = cmd.index("-vf")
    assert cmd[i + 1] == "scale=-2:720"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_transcode_server_streams_mp4(tmp_path):
    # A tiny real source to transcode (any codec; here mpeg4 from the test src).
    src = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=duration=1:size=128x72:rate=10",
         "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "1",
         str(src)],
        check=True,
    )
    srv = TranscodeServer(str(src), "127.0.0.1", 46560)
    srv.start()
    try:
        with urllib.request.urlopen(srv.url, timeout=10) as r:
            assert r.status == 200
            assert r.headers["Content-Type"] == "video/mp4"
            head = r.read(4096)
        # Fragmented MP4 begins with an ftyp box.
        assert b"ftyp" in head and len(head) > 0
    finally:
        srv.stop()
