"""Every action of the paned UI with its default keys, in one table.

The table drives key dispatch, the key bar, the help overlay and the
``[keys]`` overrides in config.toml (``action = "key, key2"``, urwid key
names: ``space``, ``enter``, ``backspace``, ``tab``, ``shift tab``, ``left`` ...).
No Ctrl, no F-keys: terminals and tetron-wm own those.
"""
from __future__ import annotations

from dataclasses import dataclass

PANES = ("devices", "source", "nowplaying", "config", "history")


@dataclass(frozen=True)
class Action:
    name: str
    keys: str        # comma separated urwid key names
    scope: str       # "global" or a pane name
    label: str       # short, for the key bar
    help: str


ACTIONS: tuple[Action, ...] = (
    Action("focus_devices", "1", "global", "devices", "Focus Devices"),
    Action("focus_source", "2", "global", "source", "Focus Source"),
    Action("focus_nowplaying", "3", "global", "playing", "Focus Now playing"),
    Action("focus_config", "4", "global", "config", "Focus Config"),
    Action("focus_history", "5", "global", "history", "Focus History"),
    Action("next_pane", "tab", "global", "next", "Next pane"),
    Action("prev_pane", "shift tab", "global", "prev", "Previous pane"),
    Action("zoom", "z", "global", "zoom", "Zoom the focused pane (again to unzoom)"),
    Action("playpause", "space", "global", "pause", "Play or pause"),
    Action("rewind", "h, left", "global", "seek", "Seek back (seek_step)"),
    Action("ffwd", "l, right", "global", "seek", "Seek forward (seek_step)"),
    Action("volup", "+, =", "global", "vol", "Volume up (volume_step)"),
    Action("voldown", "-", "global", "vol", "Volume down"),
    Action("mute", "m", "global", "mute", "Mute or unmute"),
    Action("stop", "s", "global", "stop", "Stop playback and the file server"),
    Action("skip", "n", "global", "skip", "Skip to the end"),
    Action("url", "u", "global", "url", "Cast a URL (media, YouTube, yt-dlp sites)"),
    Action("page", "w", "global", "page", "Show a web page on the device"),
    Action("command", ":", "global", "cmd", "Command line (set, cast, page, connect, scan)"),
    Action("help", "?", "global", "help", "This help"),
    Action("quit", "q", "global", "quit", "Quit, playback continues on the device"),
    Action("stop_quit", "Q", "global", "stop+quit", "Stop playback, then quit"),
    Action("connect", "enter", "devices", "connect", "Connect to the device"),
    Action("rescan", "r", "devices", "rescan", "Scan the network again"),
    Action("add_ip", "a", "devices", "add IP", "Add a device by address and connect"),
    Action("forget", "d", "devices", "forget", "Forget a saved address"),
    Action("open", "enter", "source", "cast/open", "Cast the file or open the folder"),
    Action("parent", "backspace", "source", "up", "Parent folder"),
    Action("hidden", ".", "source", "hidden", "Show or hide dot files"),
    Action("change", "enter", "config", "change", "Change the setting"),
    Action("next_value", "+, =", "config", "+/-", "Next value"),
    Action("prev_value", "-", "config", "+/-", "Previous value"),
    Action("recast", "enter", "history", "recast", "Cast this entry again"),
    Action("delete", "d", "history", "delete", "Remove this entry"),
)

BY_NAME = {a.name: a for a in ACTIONS}

# Keys shown in the bar for each pane, after the pane's own actions.
BAR_GLOBALS = {
    "nowplaying": ("playpause", "rewind", "volup", "mute", "stop", "skip", "help", "quit"),
}
DEFAULT_GLOBALS = ("playpause", "url", "help", "quit")


def keymap(overrides: dict) -> tuple[dict, list[str]]:
    """``{scope: {key: action}}`` plus a list of problems (unknown actions,
    two actions on one key in one scope) for the message line."""
    problems = []
    for name in overrides:
        if name not in BY_NAME:
            problems.append(f"[keys] unknown action {name!r}")
    table: dict[str, dict[str, str]] = {}
    for a in ACTIONS:
        scope = table.setdefault(a.scope, {})
        for k in parse_keys(overrides.get(a.name, a.keys)):
            if k in scope and scope[k] != a.name:
                problems.append(f"[keys] {show_key(k)} is both {scope[k]} and {a.name}")
            scope[k] = a.name
    return table, problems


def parse_keys(text: str) -> list[str]:
    keys = (k.strip() for k in text.split(","))
    return [" " if k == "space" else k for k in keys if k]


def keys_of(table: dict, action: str) -> list[str]:
    scope = table.get(BY_NAME[action].scope, {})
    return [k for k, a in scope.items() if a == action]


def show_key(k: str) -> str:
    return {" ": "space", "shift tab": "S-tab", "backspace": "bksp"}.get(k, k)


def bar_text(table: dict, pane: str) -> str:
    """The key bar for ``pane``: its own actions, then the main globals."""
    parts, seen = [], set()
    names = [a.name for a in ACTIONS if a.scope == pane]
    names += BAR_GLOBALS.get(pane, DEFAULT_GLOBALS)
    for name in names:
        a = BY_NAME[name]
        if a.label in seen:
            continue
        seen.add(a.label)
        if a.label in ("seek", "vol", "+/-"):
            pair = [x.name for x in ACTIONS if x.label == a.label and x.scope == a.scope]
            keys = "/".join(show_key(keys_of(table, n)[0]) for n in pair if keys_of(table, n))
        else:
            ks = keys_of(table, name)
            keys = show_key(ks[0]) if ks else ""
        if keys:
            parts.append(f"{keys} {a.label}")
    return "  ".join(parts)


def help_lines(table: dict) -> list[str]:
    lines, scope = [], None
    for a in ACTIONS:
        if a.scope != scope:
            scope = a.scope
            lines.append("")
            lines.append("all panes" if scope == "global" else f"in {scope}")
        keys = " ".join(show_key(k) for k in keys_of(table, a.name)) or "(unbound)"
        lines.append(f"  {keys:<14}{a.help}")
    return lines[1:]
