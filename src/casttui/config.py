"""Tiny persistence for last-used device and a few preferences.

Stored as ``$XDG_CONFIG_HOME/casttui/config.toml`` (default
``~/.config/casttui/config.toml``), per SCOPE_CastTUI.md §4. The file is flat
and small, so we read with stdlib ``tomllib`` and write a minimal serializer
rather than take a TOML-writer dependency (SCOPE §9: minimal footprint).

Loading never raises: a missing or malformed file yields defaults, so a
corrupt config can never stop the app from starting.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "casttui" / "config.toml"


@dataclass
class Config:
    last_device: str | None = None
    seek_step: int = 10
    volume_step: float = 0.1
    # When true, files with a codec the Chromecast cannot decode are transcoded
    # to H.264/AAC on the fly via ffmpeg (uses CPU). False → warn and skip.
    transcode: bool = True

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or config_path()
        try:
            data = tomllib.loads(path.read_text())
        except (OSError, tomllib.TOMLDecodeError):
            return cls()
        cfg = cls()
        if isinstance(data.get("last_device"), str):
            cfg.last_device = data["last_device"]
        if isinstance(data.get("seek_step"), int):
            cfg.seek_step = data["seek_step"]
        if isinstance(data.get("volume_step"), (int, float)):
            cfg.volume_step = float(data["volume_step"])
        if isinstance(data.get("transcode"), bool):
            cfg.transcode = data["transcode"]
        return cfg

    def save(self, path: Path | None = None) -> None:
        path = path or config_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self._to_toml())
        except OSError:
            pass  # persistence is best-effort; never block the UI

    def _to_toml(self) -> str:
        lines = []
        for key, value in asdict(self).items():
            if value is None:
                continue
            if isinstance(value, str):
                lines.append(f'{key} = "{value}"')
            elif isinstance(value, bool):
                lines.append(f"{key} = {str(value).lower()}")
            else:
                lines.append(f"{key} = {value}")
        return "\n".join(lines) + "\n"
