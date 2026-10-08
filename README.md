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

Browsers and VLC still play such a file by decoding it on the PC and sending
the device re-encoded H.264 (tab mirroring / "conversion") — the device never
sees the original codec. CastTUI does the same, optionally: with `transcode`
enabled (the default), a file whose codec the device cannot decode is streamed
through a live **ffmpeg** H.264/AAC transcode instead of being skipped. This
uses CPU (a modern desktop handles 1080p in real time, like VLC's warning says)
and the stream is not seekable. It needs `ffmpeg` on `$PATH`. Set
`transcode = false` to warn-and-skip instead.

## Config

`~/.config/casttui/config.toml` (override dir with `$XDG_CONFIG_HOME`). Written
automatically when you pick a device; a missing or malformed file falls back to
defaults.

```toml
last_device = "Living Room TV"
seek_step = 10      # seconds for ←/→
volume_step = 0.1   # 0.0–1.0 step for ↑/↓
transcode = true    # ffmpeg-transcode unsupported codecs instead of skipping
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
