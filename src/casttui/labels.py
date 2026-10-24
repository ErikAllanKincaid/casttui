"""Label sets and colour depth, chosen once at start (and again on a live
setting change).

``ascii`` is safe on a bare Linux console (tty1), where the font has no emoji
and few symbols; ``unicode`` uses box drawing and block characters.
"""
from __future__ import annotations

ASCII = {
    "bar_fill": "#", "bar_empty": "-", "bar_stream": "=",
    "box": dict(tlcorner="+", tline="-", lline="|", trcorner="+",
                blcorner="+", rline="|", bline="-", brcorner="+"),
    "more": "...",
}
UNICODE = {
    "bar_fill": "█", "bar_empty": "░", "bar_stream": "─",
    "box": {},  # urwid's default line drawing
    "more": "…",
}

LOW_TERMS = ("linux", "vt100", "vt220", "dumb", "ansi")
MONO_TERMS = ("vt100", "vt220", "dumb")


def pick_icons(setting: str, env: dict) -> dict:
    choice = env.get("CASTTUI_ICONS") or setting
    if choice == "ascii":
        return ASCII
    if choice == "unicode":
        return UNICODE
    term = env.get("TERM", "")
    locale = env.get("LC_ALL") or env.get("LC_CTYPE") or env.get("LANG") or ""
    utf8 = "utf-8" in locale.lower() or "utf8" in locale.lower()
    return ASCII if term in LOW_TERMS or not utf8 else UNICODE


def pick_depth(setting: str, env: dict) -> int:
    """1 (mono), 16 or 256 colours."""
    if env.get("NO_COLOR"):
        return 1
    for choice in (env.get("CASTTUI_COLORS"), setting, env.get("TETRON_WM_COLORS")):
        if choice == "mono":
            return 1
        if choice == "16":
            return 16
        if choice in ("256", "truecolor"):
            return 256
    term = env.get("TERM", "")
    if term in MONO_TERMS:
        return 1
    if term == "linux":
        return 16
    if "256" in term or env.get("COLORTERM") in ("truecolor", "24bit"):
        return 256
    return 16


def bar(labels: dict, position: float, duration: float | None, width: int) -> str:
    if not duration or duration <= 0:
        return labels["bar_stream"] * width
    filled = max(0, min(width, round(width * position / duration)))
    return labels["bar_fill"] * filled + labels["bar_empty"] * (width - filled)
