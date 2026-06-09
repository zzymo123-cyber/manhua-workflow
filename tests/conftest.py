import pytest


@pytest.fixture(autouse=True)
def isolated_settings_file(tmp_path, monkeypatch):
    from api.routes import settings

    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
