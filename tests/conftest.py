"""Every test gets its own config and state folders, so none can touch USER's real
~/.config/casttui/config.toml or ~/.local/state/casttui/history.jsonl."""
import pytest


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
