# CastTUI

A terminal UI for casting media to a Chromecast, built as a wrapper around
[catt](https://github.com/skorokithakis/catt) (Cast All The Things). Pick a
device, pick or paste something to play, and drive playback with a live
progress bar and a few keys — a "remote control" for the living-room Chromecast
without leaving the terminal. Fits the tetron-wm terminal desktop.

Full design in [`SCOPE_CastTUI.md`](SCOPE_CastTUI.md).

Status: **Milestone 3 complete (sources)**. Runnable TUI with Devices, Cast,
and Now-playing views, live status, and the core controls. Casts **local
files** (served over a managed HTTP server), **direct media URLs**, **YouTube**
(native receiver), other **yt-dlp sites**, and arbitrary **web pages**
(DashCast). Remembers the last device and reconnects on launch, and adapts to
narrow terminals. tetron-wm integration entries live in
[`docs/TETRON_WM_INTEGRATION.md`](docs/TETRON_WM_INTEGRATION.md).

## Setup

Uses [uv](https://docs.astral.sh/uv/). catt pulls in pychromecast and yt-dlp.

```sh
uv sync
```

## Run

Needs a real Chromecast on the same network.

```sh
uv run casttui
```

Pick a device (click it, or Tab to Devices and click). The **Cast** view has a
local-file browser (click a file to cast it) and a URL field (type or
middle-click to paste) with three buttons: **Cast URL** (direct media),
**YouTube / site** (YouTube native receiver, or any yt-dlp-supported site), and
**Web page** (display a page via DashCast). Playback lands in **Now playing**.

Keys: **Space** play/pause · **←/→** seek · **↑/↓** or **+/−** volume ·
**m** mute · **s** stop (also tears down the file server) · **n** skip to end ·
**r** rescan · **Tab** cycle view · **q** quit (leaves playback running on the
Chromecast). Every key also has a clickable button.

Local files are served to the Chromecast over HTTP from this host, so the two
must share a LAN subnet (SCOPE §8/§12). `xclip` or `xsel` enables middle-click
paste into the URL field.

CastTUI casts through catt/pychromecast's **Default Media Receiver**, whose
codec support is narrower than a device's native decoder. H.264 video +
AAC/MP3 audio is the safe combination. A file whose video codec the receiver
does not accept (AV1, HEVC, …) may play as **audio only**; if `ffprobe` is
installed, CastTUI warns about this before playing. CastTUI does not transcode
(SCOPE §2).

Chrome can still play such a file, but not through the device's decoder: when
the device lacks the codec, Chrome falls back to **tab mirroring**, decoding the
video itself and re-encoding the rendered output to H.264/VP8 in real time, so
the device only ever receives a codec it supports. (This is why Chrome plays
AV1 — it bundles a software AV1 decoder — but not HEVC on Linux, where it has no
HEVC decoder.) catt/CastTUI has no such decode-and-mirror pipeline. The warning
is a best-effort heuristic; a device with native support (e.g. Chromecast with
Google TV) can play more than it predicts, and a basic Chromecast (H.264/VP8
only) less.

## Config

`~/.config/casttui/config.toml` (override dir with `$XDG_CONFIG_HOME`). Written
automatically when you pick a device; a missing or malformed file falls back to
defaults.

```toml
last_device = "Living Room TV"
seek_step = 10      # seconds for ←/→
volume_step = 0.1   # 0.0–1.0 step for ↑/↓
```

## Test

```sh
uv run pytest        # service + headless-app tests, no Chromecast needed
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
