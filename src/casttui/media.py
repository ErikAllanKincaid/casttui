"""Best-effort local-media probing to warn about unplayable codecs.

The Chromecast default media receiver decodes a limited codec set. CastTUI does
not transcode (SCOPE_CastTUI.md §2), so a file the device cannot decode plays
wrong — most visibly, an unsupported *video* codec with a supported *audio*
codec plays as audio only. We probe with ffprobe (if present) and surface a
clear warning rather than letting playback fail silently. No ffprobe → no
probe, no warning.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional

# Video codecs the Chromecast default receiver cannot decode on most devices.
# H.264 is the universally safe one; VP8/VP9 usually work, so they are not
# warned about. AV1 is Chromecast-with-Google-TV only; HEVC/H.265 and the
# older Windows/MPEG codecs are generally unsupported. See
# https://developers.google.com/cast/docs/media
LIKELY_UNSUPPORTED_VIDEO = {
    "av1",
    "hevc",
    "h265",
    "mpeg2video",
    "mpeg4",
    "wmv3",
    "vc1",
    "msmpeg4v3",
}


def has_ffmpeg() -> bool:
    """Whether ffmpeg is on PATH (required for the transcode option)."""
    return shutil.which("ffmpeg") is not None


def video_codec(path: str) -> Optional[str]:
    """The file's video codec name (lowercase), or None if unknown."""
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name",
                "-of", "json",
                str(path),
            ],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode != 0:
            return None
        streams = json.loads(out.stdout).get("streams", [])
        if streams and streams[0].get("codec_name"):
            return str(streams[0]["codec_name"]).lower()
    except Exception:  # noqa: BLE001 — probing is best-effort
        pass
    return None


def unsupported_warning(path: str) -> Optional[str]:
    """A warning string if the file's video codec likely will not play."""
    codec = video_codec(path)
    if codec and codec in LIKELY_UNSUPPORTED_VIDEO:
        return (
            f"video codec '{codec}' is not supported by most Chromecasts — "
            f"it may play as audio only (CastTUI does not transcode)"
        )
    return None
