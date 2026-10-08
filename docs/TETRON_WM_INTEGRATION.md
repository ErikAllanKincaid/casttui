# casttui in tetron-wm (store + launcher entry)

casttui is designed to ship as a tetron-wm store app: it is a keyboard-and-mouse
TUI that drives the living-room Chromecast, and it needs nothing from tetron-wm
beyond a normal terminal (SCOPE_CastTUI.md §10). This document holds the exact
entries to register it, and the two prerequisites that gate a clean
registration.

## Prerequisites (not yet met)

1. **Publish casttui** so there is a real install command. The intended name is
   `casttui` on PyPI; until then the only install is from source
   (`uv tool install git+<repo>` or `pipx install git+<repo>`), which cannot be
   marked `verified` in a recipe.
2. **A generator hook for non-awesome-tuis apps.** tetron-wm's
   `assets/catalog.json` is fully regenerated from the awesome-tuis README by
   `scripts/gen_catalog.py`, which has no "extras" mechanism — so a hand-added
   entry in `catalog.json` is clobbered on the next regeneration. Registering
   casttui durably means adding an `EXTRA_APPS` list to that generator (casttui
   is not in awesome-tuis). Until that exists, treat the entry below as a patch
   to re-apply, not a committed line.

## Catalog entry (`assets/catalog.json`)

Add under the "Multimedia" (or nearest) category, keeping the file's
alpha-within-category ordering:

```json
{
 "name": "casttui",
 "bin": "casttui",
 "category": "Multimedia",
 "description": "Terminal remote for Chromecast: cast local files, URLs, YouTube and web pages, with a live progress bar and playback controls.",
 "homepage": "https://github.com/erikallankincaid/CastTUI"
}
```

## Install recipe (`assets/recipes.json`)

Keyed by display name, alpha-sorted. Mark `verified: false` until casttui is on
PyPI, then switch the command to `pipx install casttui` (or
`uv tool install casttui`) and set `verified: true`:

```json
"casttui": {
 "install": "pipx install casttui",
 "method": "pipx",
 "os": ["macos", "linux"],
 "verified": false,
 "tip": "Discovers Chromecasts on first launch (needs the same LAN). Pulls in pychromecast and yt-dlp, so the first install is sizeable. Casting a local file serves it over HTTP, so the host and the Chromecast must share a subnet."
}
```

`requires_cwd` is intentionally omitted (false): casttui does not operate on a
project tree.

## Launcher

`packaging/casttui.desktop` is a standard freedesktop launcher entry. Once
`casttui` is on `$PATH`, tetron-wm's catalog detection picks it up by its `bin`
automatically; the `.desktop` file covers plain desktop environments.
