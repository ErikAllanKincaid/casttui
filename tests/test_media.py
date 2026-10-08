"""Codec-warning logic (ffprobe mocked via video_codec)."""
from __future__ import annotations

import casttui.media as media


def test_warns_on_av1(monkeypatch):
    monkeypatch.setattr(media, "video_codec", lambda p: "av1")
    w = media.unsupported_warning("/x.mp4")
    assert w and "av1" in w


def test_no_warning_for_h264(monkeypatch):
    monkeypatch.setattr(media, "video_codec", lambda p: "h264")
    assert media.unsupported_warning("/x.mp4") is None


def test_no_warning_when_codec_unknown(monkeypatch):
    monkeypatch.setattr(media, "video_codec", lambda p: None)
    assert media.unsupported_warning("/x.mp4") is None


def test_video_codec_none_without_ffprobe(monkeypatch):
    monkeypatch.setattr(media.shutil, "which", lambda _: None)
    assert media.video_codec("/x.mp4") is None


def test_has_ffmpeg(monkeypatch):
    monkeypatch.setattr(media.shutil, "which", lambda n: "/usr/bin/ffmpeg")
    assert media.has_ffmpeg() is True
    monkeypatch.setattr(media.shutil, "which", lambda n: None)
    assert media.has_ffmpeg() is False
