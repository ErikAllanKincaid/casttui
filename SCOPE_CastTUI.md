# casttui scope

Status: scope / design (2026-10-07). A terminal UI for casting media to a Chromecast, built as a wrapper around catt (Cast All The Things). This document defines what casttui is, what it will and will not do, how it is built, and the order of work.

## 1. Purpose

Casting to a Chromecast from a terminal today means remembering catt's subcommands (`catt cast`, `catt seek`, `catt volume`, and so on) and running them one at a time with no live feedback. casttui turns that into a single interactive screen: pick a device, pick or paste something to play, and drive playback with a live progress bar and a few keys. It is aimed at a keyboard-and-mouse terminal user who wants a "remote control" for the living-room Chromecast without leaving the terminal, and it is a natural app for the tetron-wm terminal desktop.

## 2. Goals and non-goals

Goals: a responsive single-binary-feel TUI that discovers Chromecasts, casts local files, direct media URLs, YouTube videos, and arbitrary web pages, and controls playback (play, pause, seek, volume, mute, stop, skip) with a live status display. It must reuse catt's proven casting logic rather than reimplement the Cast protocol, and it should run well both standalone and inside tetron-wm.

Non-goals (at least for v1): a media library or database, transcoding, multi-room or audio-group orchestration, a mobile or web frontend, and support for cast targets other than Chromecast and Chromecast-compatible receivers that catt already handles. casttui is a controller, not a media server or a content catalog.

## 3. Background: what catt provides

catt (https://github.com/skorokithakis/catt, local clone at `~/code/catt/`) is a Python tool built on pychromecast (https://github.com/home-assistant-libs/pychromecast). It gives casttui two surfaces, and casttui uses the library, not the command line.

- A high-level API, `catt.api` (`~/code/catt/catt/api.py`): `discover() -> List[CattDevice]`, and `CattDevice` with `play_url`, `play`, `pause`, `stop`, `seek`, `rewind`, `ffwd`, `volume`, `volumeup`, `volumedown`, and `volumemute`.
- Controllers and status, `catt.controllers` (`~/code/catt/catt/controllers.py`): a `CastStatusListener` and a `MediaStatusListener` (subclassing pychromecast's listener), an `info()` view of the current status, and a `wait_for(states, ...)` helper. These are the hook for live updates.
- A local-file HTTP server, `catt.http_server` (`serve_file`, and `create_server_thread` in `catt/cli.py`): catt serves a local file over HTTP for the duration of playback, because the Chromecast fetches media by URL. casttui reuses this so local files can be cast, and must keep that server thread alive while the file plays.

Using the library directly (not `subprocess catt ...`) is a hard design choice: it is the only way to get push status updates for a smooth progress bar, and it avoids the latency and parsing fragility of scraping CLI output.

## 4. Architecture

casttui is a Python application built with Textual (https://textual.textualize.io), chosen because catt is Python so the casting library is in-process, and because Textual provides an async event loop, real widgets (progress bars, lists, modal dialogs), and mouse support that a casting remote needs. urwid is the fallback if a lighter dependency is wanted.

The core pieces:

- A thin service layer over `catt.api` that owns the selected `CattDevice`, exposes the playback actions, and starts or stops the local-file HTTP server around local playback.
- A status bridge. pychromecast delivers media and cast status on its own background thread through the listeners in `catt.controllers`. casttui registers a listener on the device's underlying `media_controller` and forwards each update into Textual's event loop with `call_from_thread`, so the UI never touches Cast state from the wrong thread. The progress bar advances from the last known position plus elapsed wall-clock time between pushes, and resyncs on each real update, so it stays smooth without polling.
- A small persistence file (for example `~/.config/casttui/config.toml`) holding the last-used device and a few preferences, so casttui reconnects to the usual Chromecast on launch.

## 5. Features

v1 (the minimum that makes it worth using):

- Device discovery and selection. List Chromecasts from `discover()`, select one, remember the last choice, and allow rescanning.
- Now-playing. Title, a live progress bar with position and duration, play or pause or buffering state, and a volume indicator, all updated from status pushes.
- Media sources: a local file browser to cast a file from disk (served over the local HTTP server), a field to paste a direct media URL, a YouTube search box and URL field, and a "cast this web page" action (catt's `cast_site`).
- Playback controls: play and pause toggle, stop, seek backward and forward, set and step volume, mute, and skip to the end of the current item.
- Clear error surfaces: a device that goes away, a URL that will not play, or a missing dependency should show a readable message, never a stack trace.

Later (explicitly deferred past v1):

- Queue management for YouTube (catt supports add, play-next, and clear), shown as an editable list.
- Subtitle selection and toggling (catt lists and toggles captions for non-YouTube media).
- Recent-media history and simple favorites.
- Casting a playlist or a folder of local files in sequence.
- A compact "mini" mode that shows only the now-playing bar, for embedding.

## 6. Screens and layout

A single window with a few views, switched by tab or hotkey:

- Devices: a list of discovered Chromecasts with their names and addresses, a rescan action, and the current selection highlighted.
- Now playing: the main view. A title line, a wide progress bar with elapsed and total time, a state glyph, a volume bar, and a row of control hints. This is where the app opens once a device is chosen and something is playing.
- Cast: the input view. A file browser pane, a URL field, a YouTube field, and a "cast web page" field, each with its own confirm action. Picking a source starts playback and returns to Now playing.
- Queue and Subtitles are added in the later phase as additional views.

The layout targets a normal terminal and degrades gracefully on a narrow one by stacking panes. It should render on a plain truecolor terminal and inside tetron-wm without special support.

## 7. Keybindings

Eyes-free controls, chosen so the hand can stay on the arrows:

- Space: play or pause toggle.
- Left and Right: seek backward and forward by a fixed step (for example ten seconds).
- Up and Down, or plus and minus: volume up and down.
- m: mute toggle. s: stop. n: skip to end. r: rescan devices.
- Tab: switch view. Enter: confirm the focused input or activate the focused item. q: quit (leaving playback running on the Chromecast, since stopping is a separate, explicit action).

Every binding is also a visible, clickable control, so the app is usable by mouse alone.

## 8. Technical details and gotchas

- Threading. pychromecast listeners fire off the UI thread. All Cast state reaches the UI through `call_from_thread`, and all catt calls that block (connecting, waiting for a state) run off the UI thread so the interface never freezes. catt's own `wait_for` and the event waits in `controllers.py` are blocking and must not run on the Textual loop.
- Local files. Casting a local file means starting catt's HTTP server thread bound to a reachable address on the LAN, handing the Chromecast the server URL, and keeping the thread alive until playback ends or is stopped. casttui must tear the server down on stop, on quitting, and on switching media, or it will leak threads and ports. Remote URLs and YouTube do not need the server.
- Discovery timing. `discover()` blocks while it scans the network, so it runs off the UI thread with a spinner, and the UI stays responsive. A device list can be empty on a slow network, so rescanning is always available.
- Volume model. catt uses a 0.0 to 1.0 float for `volume`, with separate step helpers; the UI shows 0 to 100 and converts.
- YouTube and streams. catt resolves YouTube and many sites through yt-dlp, which can fail or change behavior as sites change; those failures surface as a friendly message, and yt-dlp is a dependency to keep updated.

## 9. Dependencies and footprint

Runtime: Python 3, `catt` (which brings in pychromecast and yt-dlp), and `textual`. This is a non-trivial install footprint for a terminal tool, mostly from pychromecast and yt-dlp, which is acceptable for a casting app but should be stated plainly in any catalog entry. Packaging as a `pipx`-installable console script keeps it isolated from the system Python.

## 10. tetron-wm integration

casttui is a good tetron-wm store app and should ship as one: a catalog entry plus a launcher entry, so it opens in a window on the terminal desktop. It needs nothing special from tetron-wm beyond a normal terminal, and it benefits from the desktop's mouse support. tetron-wm also gives a convenient test environment, since a window on the desktop can drive the living-room Chromecast while other work continues. The catalog entry should note the pychromecast and yt-dlp dependencies and that first launch may scan the network.

## 11. Milestones

1. Spike: from a plain script, `discover()`, cast a known URL to a chosen device, and read back live status through a listener. This proves the library path and the status bridge before any UI.
2. v1 skeleton: the Devices and Now-playing views with live status and the core controls, casting direct URLs only.
3. v1 sources: add the local-file browser (with the HTTP server lifecycle), the YouTube field, and `cast_site`.
4. Polish: error surfaces, last-device persistence, narrow-terminal layout, and a tetron-wm catalog and launcher entry.
5. Later phases: queue, subtitles, history and favorites, folder and playlist casting, mini mode.

## 12. Risks and open questions

- Dependency weight and brittleness: yt-dlp changes often and pychromecast is large; the app's reliability is partly tied to theirs.
- Local-file reachability: serving a file requires the Chromecast to reach the host over the LAN, which can fail behind client isolation on some routers or when casting from a machine on a different subnet.
- Status completeness: not every receiver app reports the same fields (position and duration can be missing for some streams), so the progress bar must handle an unknown duration gracefully.
- DECIDED (2026-10-07): v1 ships local-file casting. The HTTP server lifecycle (start on local play, tear down on stop, quit, and media switch) is therefore in scope for v1, not deferred.
- DECIDED (2026-10-07): casttui depends on catt as a library (import `catt.api` and `catt.controllers`), tracking upstream, rather than vendoring the HTTP server and listeners. Revisit only if the dependency surface becomes a problem.

## 13. Testing

The service layer is tested without a real Chromecast by mocking `catt.api` and the listeners, asserting that actions call the right device methods and that status pushes update the model. The status bridge is tested by feeding synthetic status objects through the forwarding path. A small set of manual, device-in-the-loop checks covers real discovery, local-file serving, URL, YouTube, and `cast_site`, since the Cast protocol itself cannot be meaningfully faked end to end.

## 14. References

catt, Cast All The Things, https://github.com/skorokithakis/catt (local clone `~/code/catt/`); pychromecast, the underlying Chromecast library, https://github.com/home-assistant-libs/pychromecast; Textual, the TUI framework, https://textual.textualize.io; yt-dlp, used by catt to resolve YouTube and many sites, https://github.com/yt-dlp/yt-dlp.
