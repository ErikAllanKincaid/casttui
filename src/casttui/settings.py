"""The one table of user settings.

Each :class:`Setting` drives the config file (load, validate, save), the
Config pane in the paned UI, and the ``--help`` text, so adding an option is
one entry here. The type of a setting is the type of its default (``None``
means a string that may be unset).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Setting:
    key: str
    default: object
    help: str
    # Values the Config pane cycles through with Enter or +/-. Empty means the
    # value is typed (Enter opens the prompt) or, with editable=False, shown only.
    choices: tuple = ()
    editable: bool = True


SETTINGS: tuple[Setting, ...] = (
    Setting("ui", "panes", "Interface at start: panes, or the classic Textual views",
            ("panes", "classic")),
    Setting("transcode", True, "Transcode codecs the device can not play (uses CPU)",
            (True, False)),
    Setting("transcode_scale", 0, "Height of the transcoded stream, 0 keeps the source",
            (0, 1080, 720, 480)),
    Setting("seek_step", 10, "Seconds per seek key", (5, 10, 15, 30, 60)),
    Setting("volume_step", 0.1, "Volume change per key, 0.1 is 10%", (0.05, 0.1, 0.2)),
    Setting("icons", "auto", "Labels: ascii, unicode, or auto (ascii on a bare console)",
            ("auto", "ascii", "unicode")),
    Setting("colors", "auto", "Colour depth: auto, mono, 16 or 256",
            ("auto", "mono", "16", "256")),
    Setting("start_dir", "", "Folder the Source pane opens in, empty is the current folder"),
    Setting("last_device", None, "Device reconnected at start (set on connect)",
            editable=False),
    Setting("devices", [], "Saved device addresses (a in Devices adds, d forgets)",
            editable=False),
    Setting("keys", {}, "Key overrides, action = key, see the help overlay (?)",
            editable=False),
)

BY_KEY = {s.key: s for s in SETTINGS}


def kind(s: Setting) -> type:
    return str if s.default is None else type(s.default)


def valid(s: Setting, value: object) -> bool:
    """Is ``value`` (as read from TOML) acceptable for ``s``?"""
    k = kind(s)
    if k is bool:
        return isinstance(value, bool)
    if k is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if k is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if k is list:
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    if k is dict:
        return isinstance(value, dict) and all(
            isinstance(a, str) and isinstance(b, str) for a, b in value.items())
    return isinstance(value, str)


def parse(s: Setting, text: str) -> object:
    """Turn typed text into a value for ``s``; raises ValueError."""
    k = kind(s)
    text = text.strip()
    if k is bool:
        if text.lower() in ("on", "true", "yes", "1"):
            return True
        if text.lower() in ("off", "false", "no", "0"):
            return False
        raise ValueError(f"{s.key} takes on or off")
    if k in (int, float):
        try:
            v = k(text)
        except ValueError:
            raise ValueError(f"{s.key} takes a number") from None
        if v < 0:
            raise ValueError(f"{s.key} can not be negative")
        return v
    if k is str:
        if s.choices and text not in s.choices:
            raise ValueError(f"{s.key} takes one of: {', '.join(s.choices)}")
        return text
    raise ValueError(f"{s.key} is not set by typing")


def show(value: object) -> str:
    """A setting value as the Config pane and help show it."""
    if isinstance(value, bool):
        return "on" if value else "off"
    if value is None or value == "":
        return "-"
    if isinstance(value, list):
        return ", ".join(value) or "-"
    if isinstance(value, dict):
        return f"{len(value)} set" if value else "-"
    return str(value)


def help_text() -> str:
    """The settings section of ``--help``."""
    lines = ["settings (~/.config/casttui/config.toml, also changed live in the Config pane):"]
    for s in SETTINGS:
        lines.append(f"  {s.key:<16}{show(s.default):<8}{s.help}")
    return "\n".join(lines)
