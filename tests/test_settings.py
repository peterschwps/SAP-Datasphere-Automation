from pathlib import Path

import pytest
from pydantic import ValidationError

from datasphere_cli.utils import settings as settings_module
from datasphere_cli.utils.settings import Settings, build_config

VALID_TOML = """\
[setup]
datasphere_url = "https://example.eu10.hcs.cloud.sap"
authorization_url = "https://auth.example/oauth/authorize"
token_url = "https://auth.example/oauth/token"
browser_to_use = "edge"

[credentials]
client_id = "client-id"
secret = "top-secret"
"""


@pytest.fixture
def settings_file(tmp_path: Path, monkeypatch) -> Path:
    """
    Redirects the settings file into tmp_path.
    """
    path = tmp_path / "settings.toml"
    monkeypatch.setattr(settings_module, "SETTINGS_FILE", path)
    monkeypatch.setitem(Settings.model_config, "toml_file", path)
    monkeypatch.setattr(settings_module, "settings", None)
    return path


def test_settings_load_and_uppercase_browser(settings_file: Path) -> None:
    settings_file.write_text(VALID_TOML, encoding="utf-8")
    loaded = Settings()  # pyright: ignore[reportCallIssue]
    assert loaded.setup.datasphere_url == "https://example.eu10.hcs.cloud.sap"
    assert loaded.setup.browser_to_use == "EDGE"
    assert loaded.credentials.secret == "top-secret"


def test_settings_reject_missing_keys(settings_file: Path) -> None:
    settings_file.write_text("[setup]\n[credentials]\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        Settings()  # pyright: ignore[reportCallIssue]


def test_build_config_uses_settings(settings_file: Path) -> None:
    settings_file.write_text(VALID_TOML, encoding="utf-8")
    config = build_config()
    assert config.base_url == "https://example.eu10.hcs.cloud.sap"
    assert config.browser == "EDGE"
    assert config.client_secret == "top-secret"


def test_build_config_secret_from_environment(
    settings_file: Path,
    monkeypatch,
) -> None:
    settings_file.write_text(
        VALID_TOML.replace('secret = "top-secret"', 'secret = ""'),
        encoding="utf-8",
    )
    monkeypatch.setenv("SECRET", "env-secret")
    config = build_config()
    assert config.client_secret == "env-secret"
