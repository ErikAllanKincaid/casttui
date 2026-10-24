"""Every test gets its own config folder, so none can touch USER's real
~/.config/casttui/config.toml (a connect saves last_device)."""
import pytest


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
