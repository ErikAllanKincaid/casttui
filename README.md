# CastTUI

A terminal UI for casting media to a Chromecast, built as a wrapper around
[catt](https://github.com/skorokithakis/catt) (Cast All The Things). Pick a
device, pick or paste something to play, and drive playback with a live
progress bar and a few keys — a "remote control" for the living-room Chromecast
without leaving the terminal. Fits the tetron-wm terminal desktop.

Full design in [`SCOPE_CastTUI.md`](SCOPE_CastTUI.md).

Status: **Milestone 1 (spike)**. No UI yet — proving the catt library path and
the pychromecast status bridge first.

## Setup

Uses [uv](https://docs.astral.sh/uv/). catt pulls in pychromecast and yt-dlp.

```sh
uv sync
```

## Spike

Needs a real Chromecast on the same network.

```sh
uv run spike/cast_spike.py --scan                 # list devices and exit
uv run spike/cast_spike.py                        # cast a test video to the first device
uv run spike/cast_spike.py --name "Living Room" --url https://example.com/clip.mp4
```

It discovers devices, casts a URL, and prints live status (state, position,
duration, volume) from a pychromecast status listener — the push-based path the
real UI's progress bar will use.
