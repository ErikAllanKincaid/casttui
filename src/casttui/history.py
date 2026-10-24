"""What was cast, kept across runs.

``$XDG_STATE_HOME/casttui/history.jsonl`` (default
``~/.local/state/casttui/history.jsonl``): one JSON object per line, oldest
first, so adding an entry is one append. The file is trimmed to the newest
:data:`KEEP` entries once it passes twice that. Like the config, a missing or
broken file never stops casttui: unreadable lines are skipped.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

KEEP = 200


@dataclass
class Entry:
    when: str          # ISO local time, minutes: 2026-10-23T21:04
    text: str
    kind: str = ""     # file, url, page: recastable; "" is information only
    target: str = ""


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M")


def history_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or "~/.local/state"
    return Path(base).expanduser() / "casttui" / "history.jsonl"


def shown_when(when: str, today: str | None = None) -> str:
    """``21:04`` for today, ``10-22 21:04`` before that."""
    today = today or now()[:10]
    date, _, clock = when.partition("T")
    return clock if date == today else f"{date[5:]} {clock}"


def load(path: Path | None = None) -> list[Entry]:
    """The newest :data:`KEEP` entries, newest first."""
    path = path or history_path()
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            d = json.loads(line)
            out.append(Entry(str(d["when"]), str(d["text"]), str(d.get("kind", "")),
                             str(d.get("target", ""))))
        except (ValueError, KeyError, TypeError):
            continue
    return out[::-1][:KEEP]


def append(entry: Entry, path: Path | None = None) -> None:
    path = path or history_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(asdict(entry)) + "\n")
        with path.open() as f:
            count = sum(1 for _ in f)
        if count > 2 * KEEP:
            rewrite(load(path), path)
    except OSError:
        pass  # best-effort, like the config


def rewrite(entries: list[Entry], path: Path | None = None) -> None:
    """Replace the file with ``entries`` (newest first, as the UI holds them)."""
    path = path or history_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".jsonl.tmp")
        tmp.write_text("".join(json.dumps(asdict(e)) + "\n" for e in entries[::-1]))
        tmp.replace(path)
    except OSError:
        pass
