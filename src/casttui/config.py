"""Persistence for the settings in :mod:`casttui.settings`.

Stored as ``$XDG_CONFIG_HOME/casttui/config.toml`` (default
``~/.config/casttui/config.toml``). Reads with stdlib ``tomllib``; saves with
``tomlkit`` into the existing file, so USER's comments, order and unknown keys
survive a save from the Config pane.

Loading never raises: a missing or malformed file yields defaults, and a bad
value for one key falls back to that key's default, so a corrupt config can
never stop the app from starting.
"""
from __future__ import annotations

import copy
import os
import tomllib
from pathlib import Path

import tomlkit

from .settings import BY_KEY, SETTINGS, valid


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "casttui" / "config.toml"


class Config:
    """One attribute per setting, defaulted from the table."""

    def __init__(self, path: Path | None = None, **values) -> None:
        self.path = path
        for s in SETTINGS:
            setattr(self, s.key, copy.deepcopy(s.default))
        for key, value in values.items():
            if key not in BY_KEY:
                raise TypeError(f"unknown setting {key!r}")
            setattr(self, key, value)

    def __repr__(self) -> str:
        vals = ", ".join(f"{s.key}={getattr(self, s.key)!r}" for s in SETTINGS)
        return f"Config({vals})"

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or config_path()
        cfg = cls(path=path)
        try:
            data = tomllib.loads(path.read_text())
        except (OSError, tomllib.TOMLDecodeError):
            return cfg
        for s in SETTINGS:
            if s.key in data and valid(s, data[s.key]):
                value = data[s.key]
                setattr(cfg, s.key, float(value) if isinstance(s.default, float) else value)
        return cfg

    def save(self, path: Path | None = None) -> None:
        """Write the settings that differ from the default, or are already in
        the file, keeping everything else in the file as it was."""
        path = path or self.path or config_path()
        try:
            text = path.read_text()
        except OSError:
            text = ""
        try:
            doc = tomlkit.parse(text)
        except Exception:  # noqa: BLE001  a malformed file: keep a copy, start fresh
            try:
                path.with_suffix(".toml.bad").write_text(text)
            except OSError:
                pass
            doc = tomlkit.document()
        for s in SETTINGS:
            value = getattr(self, s.key)
            if value is None:
                doc.pop(s.key, None)
            elif s.key in doc or value != s.default:
                doc[s.key] = value
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(tomlkit.dumps(doc))
        except OSError:
            pass  # persistence is best-effort; never block the UI
