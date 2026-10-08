#!/usr/bin/env python3
"""casttui Milestone 1 spike.

Proves the catt library path + the pychromecast status bridge before any UI:

  1. discover() Chromecasts on the LAN
  2. pick one (by --name, else the first found)
  3. cast a media URL (--url, else a known public test video)
  4. register a media-status listener and print LIVE status (state, position,
     duration, volume), with the position interpolated between pushes.

Run (needs a real Chromecast on the same network):

    uv run spike/cast_spike.py --scan        # just list devices and exit
    uv run spike/cast_spike.py               # cast a test video to the first device
    uv run spike/cast_spike.py --name "Living Room TV" --url https://.../clip.mp4

Throwaway proof-of-concept: library path only, minimal error handling.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time

from catt.api import discover
from pychromecast.controllers.media import MediaStatusListener

# A small (~1 MB, 10 s), public, directly-playable MP4 (no yt-dlp needed) for
# the spike. The old gtv-videos-bucket BigBuckBunny.mp4 now 403s (dead bucket),
# which the receiver reports as idle_reason=ERROR → catt "Playback failed".
DEFAULT_URL = (
    "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360/"
    "Big_Buck_Bunny_360_10s_1MB.mp4"
)


class StatusPrinter(MediaStatusListener):
    """Capture pychromecast media-status pushes behind a lock.

    pychromecast fires these on its own background thread, so everything here
    stays behind a lock — exactly the thread boundary the real UI will cross
    with Textual's ``call_from_thread``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state = "UNKNOWN"
        self.title: str | None = None
        self.duration: float | None = None
        self.position = 0.0
        self.volume: float | None = None
        self.muted = False
        self._updated_at = time.monotonic()

    def new_media_status(self, status) -> None:
        with self._lock:
            self.state = status.player_state or "UNKNOWN"
            self.title = status.title
            self.duration = status.duration
            self.position = status.current_time or 0.0
            self.volume = status.volume_level
            self.muted = status.volume_muted
            self._updated_at = time.monotonic()

    def load_media_failed(self, item, error_code) -> None:
        with self._lock:
            self.state = f"LOAD FAILED (item={item}, code={error_code})"
            self._updated_at = time.monotonic()

    def snapshot(self) -> dict:
        """Latest status with the position interpolated to wall-clock now."""
        with self._lock:
            pos = self.position
            if self.state == "PLAYING":
                pos += time.monotonic() - self._updated_at
            if self.duration:
                pos = min(pos, self.duration)
            return {
                "state": self.state,
                "title": self.title,
                "position": pos,
                "duration": self.duration,
                "volume": self.volume,
                "muted": self.muted,
            }


def fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def pick_device(name: str | None):
    print("Discovering Chromecasts…", flush=True)
    devices = discover()
    if not devices:
        print("No Chromecasts found on the network.", file=sys.stderr)
        return None, []
    for d in devices:
        print(f"  • {d.name}  ({d.ip_addr})")
    if name:
        for d in devices:
            if d.name.lower() == name.lower():
                return d, devices
        print(f"Device named {name!r} not found.", file=sys.stderr)
        return None, devices
    return devices[0], devices


def main() -> int:
    ap = argparse.ArgumentParser(description="casttui Milestone 1 spike")
    ap.add_argument("--name", help="Chromecast friendly name (default: first found)")
    ap.add_argument("--url", default=DEFAULT_URL, help="media URL to cast")
    ap.add_argument("--seconds", type=int, default=30, help="how long to watch status")
    ap.add_argument("--scan", action="store_true", help="list devices and exit")
    args = ap.parse_args()

    device, devices = pick_device(args.name)
    if args.scan:
        return 0 if devices else 1
    if device is None:
        return 1

    print(f"\nSelected: {device.name} ({device.ip_addr})")

    # Register the listener BEFORE playback so we catch the first PLAYING push.
    listener = StatusPrinter()
    device._cast.media_controller.register_status_listener(listener)

    print(f"Casting: {args.url}")
    try:
        device.play_url(args.url)
    except Exception as exc:  # noqa: BLE001 — spike: surface anything
        print(f"play_url failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"\nWatching status for {args.seconds}s "
        "(Ctrl-C stops watching; playback keeps running on the Chromecast):\n"
    )
    try:
        end = time.monotonic() + args.seconds
        while time.monotonic() < end:
            s = listener.snapshot()
            vol = f"{int(s['volume'] * 100)}%" if s["volume"] is not None else "--"
            mute = " (muted)" if s["muted"] else ""
            line = (
                f"[{s['state']:<9}] "
                f"{fmt_time(s['position'])} / {fmt_time(s['duration'])}  "
                f"vol {vol}{mute}  {s['title'] or ''}"
            )
            print("\r" + line.ljust(79), end="", flush=True)
            time.sleep(0.5)
        print()
    except KeyboardInterrupt:
        print("\nStopped watching.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
