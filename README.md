# casttui

A terminal UI for casting media to a Chromecast, built as a wrapper around
[catt](https://github.com/skorokithakis/catt) (Cast All The Things). Pick a
device, pick or paste something to play, and drive playback with a live
progress bar and a few keys — a "remote control" for the living-room Chromecast
without leaving the terminal. Fits the tetron-wm terminal desktop.

Full design in [`SCOPE_CastTUI.md`](SCOPE_CastTUI.md).

Status: **paned interface**. A one-screen, keyboard-first interface (urwid) with Devices, Source, Now playing, Config and History panes, live status, in-app settings, and plain ASCII and low-colour support for a bare console. The original Textual interface is kept as `casttui --classic`. Casts **local files** (served over a managed HTTP server, transcoded when the device can not decode them), **direct media URLs**, **YouTube** (native receiver), other **yt-dlp sites**, and arbitrary **web pages** (DashCast). Remembers the last device and reconnects on launch, also by address. tetron-wm integration entries live in [`docs/TETRON_WM_INTEGRATION.md`](docs/TETRON_WM_INTEGRATION.md).

## Setup

Uses [uv](https://docs.astral.sh/uv/). catt pulls in pychromecast and yt-dlp.

```sh
uv sync
```

## Run

Needs a real Chromecast on the same network, or its address (`-d`).

```sh
uv run casttui
uv run casttui ~/Videos/clip.mp4        # cast a file as soon as a device is connected
uv run casttui https://example.com/v    # or a URL (YouTube and other sites too)
uv run casttui -d 192.168.1.50          # connect by address, no discovery needed
uv run casttui --classic                # the classic Textual interface
uv run casttui --help                   # every option and setting
```

With a file or URL, casttui casts it to the remembered device, or to the only Chromecast on the network. With several devices and none remembered, pick one and the cast starts. This is what tetron-wm's right-click **Open with… casttui** runs.

### The paned interface (default)

One screen of panes, all driven from the keyboard, in plain ASCII on a bare console:

```
+ 1 Devices ----------------++ 2 Source -----------------------------------------+
|* Living Room TV   192.168.||~/Videos                                           |
|  + add by address (a)     ||---------------------------------------------------|
+ 4 Config -----------------+|clip.mp4                                    41.2M  |
|transcode       on         |+ 3 Now playing -----------------------------------+
|seek_step       10         ||clip.mp4   PLAYING   vol 60%                       |
|icons           auto       ||[#############---------------------]  02:10 / 05:40|
+---------------------------++---------------------------------------------------+
 enter cast/open  bksp up  . hidden  space pause  u url  ? help  q quit
```

- **Devices** (1): scan results and saved addresses. `enter` connects, `a` adds a device by address (for a Chromecast that discovery can not see, such as on another subnet), `d` forgets a saved address, `r` scans again.
- **Source** (2): a file browser. `enter` casts a file or opens a folder, `backspace` goes up, `.` shows dot files. `u` casts a URL from any pane (direct media, YouTube, or any yt-dlp site) and `w` shows a web page on the device.
- **Now playing** (3): title, state, volume, progress, the device, and whether the file plays directly or is transcoded.
- **Config** (4): every setting with its value. `enter` or `+`/`-` changes it, and the change is saved at once.
- **History** (5): what was cast this session. `enter` casts an entry again.

From any pane: `space` play/pause, `h`/`l` or arrows seek, `+`/`-` volume, `m` mute, `s` stop, `n` skip, `tab` next pane, `z` zoom a pane, `:` command line (`set KEY VALUE`, `cast PATH|URL`, `page URL`, `connect NAME|IP`, `scan`), `?` every key, `q` quit (playback continues), `Q` stop and quit. Lists move with arrows or `j`/`k`. A click focuses a pane or row and a double click acts on it, but nothing needs the mouse.

The layout follows the terminal: three columns from 150 columns wide, two from 80, one pane at a time (with a tab strip) below that.

### The classic interface

`casttui --classic`, `casttui-classic`, `CASTTUI_UI=classic` or `ui = "classic"` start the original Textual interface: Devices, Cast and Now playing views cycled with Tab, with a button for every action.

Local files are served to the Chromecast over HTTP from this host, so the two
must share a LAN subnet (SCOPE §8/§12). `xclip` or `xsel` enables middle-click
paste into the URL field.

casttui casts through catt/pychromecast's **Default Media Receiver**, whose
codec support is narrower than a device's native decoder. H.264 video +
AAC/MP3 audio is the safe combination. A file whose video codec the receiver
does not accept (AV1, HEVC, …) may play as **audio only**; if `ffprobe` is
installed, casttui warns about this before playing. casttui does not transcode
(SCOPE §2).

Browsers and VLC still play such a file by decoding it on the PC and sending
the device re-encoded H.264 (tab mirroring / "conversion") — the device never
sees the original codec. casttui does the same, optionally: with `transcode`
enabled (the default), a file whose codec the device cannot decode is streamed
through a live **ffmpeg** H.264/AAC transcode instead of being skipped. This
uses CPU (a modern desktop handles 1080p in real time, like VLC's warning says)
and the stream is not seekable. It needs `ffmpeg` on `$PATH`. Set
`transcode = false` to warn-and-skip instead.

## Config

`~/.config/casttui/config.toml` (override dir with `$XDG_CONFIG_HOME`). The Config pane edits it in place and keeps your comments; a missing or malformed file falls back to defaults, and a bad value falls back for that key only. `casttui --help` lists every setting.

```toml
ui = "panes"            # or "classic"
transcode = true        # ffmpeg-transcode unsupported codecs instead of skipping
transcode_scale = 0     # height of the transcoded stream, 0 keeps the source
seek_step = 10          # seconds per seek key
volume_step = 0.1       # 0.0-1.0 per volume key
icons = "auto"          # ascii, unicode; auto is ascii on a bare console
colors = "auto"         # mono, 16, 256; NO_COLOR and TETRON_WM_COLORS are honoured
start_dir = ""          # Source pane folder, empty is the current folder
last_device = "Living Room TV"   # set on connect (an address when added by address)
devices = ["10.0.5.20"]          # saved addresses

[keys]                  # rebind any action, see ? in the app
quit = "x"
rewind = "h, left"
```

## Test

```sh
uv run pytest        # service, config and headless UI tests, no Chromecast needed
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
