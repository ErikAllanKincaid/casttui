"""Command line: parse the arguments, then start the panes or the classic UI.

UI choice, first match wins: ``--panes``/``--classic``, ``CASTTUI_UI``, the
``ui`` setting. ``casttui-classic`` always starts the classic UI.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .settings import help_text

UIS = ("panes", "classic")


def is_url(text: str) -> bool:
    return text.lower().startswith(("http://", "https://"))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="casttui",
        description="A terminal remote for casting to a Chromecast.",
        epilog=help_text() + "\n\nenvironment: CASTTUI_UI=panes|classic, "
        "CASTTUI_ICONS=ascii|unicode, CASTTUI_COLORS=mono|16|256, NO_COLOR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("source", nargs="?",
                   help="a media file or URL to cast as soon as a device is connected")
    p.add_argument("-d", "--device", metavar="NAME_OR_IP",
                   help="connect to this device (a name or an address) without scanning first")
    ui = p.add_mutually_exclusive_group()
    ui.add_argument("--panes", dest="ui", action="store_const", const="panes",
                    help="the paned, keyboard-first interface")
    ui.add_argument("--classic", dest="ui", action="store_const", const="classic",
                    help="the classic Textual interface")
    return p


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Exits with a usage error before any UI starts on a missing file, so a
    bad right-click never opens an empty UI. File paths are made absolute."""
    p = parser()
    args = p.parse_args(argv)
    if args.source is not None and not is_url(args.source):
        path = Path(args.source).expanduser()
        if not path.is_file():
            p.error(f"not a file: {args.source}")
        args.source = str(path.resolve())
    return args


def parse_source(argv: list[str]) -> str | None:
    return parse_args(argv).source


def pick_ui(flag: str | None, env: dict, setting: str) -> str:
    for choice in (flag, env.get("CASTTUI_UI"), setting):
        if choice in UIS:
            return choice
    return "panes"


def main() -> None:
    from .config import Config

    args = parse_args(sys.argv[1:])
    cfg = Config.load()
    if pick_ui(args.ui, os.environ, cfg.ui) == "classic":
        from .classic import CastTUI

        CastTUI(config=cfg, source=args.source, device=args.device).run()
    else:
        from .panes import run

        run(config=cfg, source=args.source, device=args.device)
