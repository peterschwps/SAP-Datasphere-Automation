import dataclasses

import pytest

from datasphere_api import (
    DatasphereClient,
    DatasphereConfig,
    InvalidConfiguration,
    MissingCredentials,
)


def test_config_defaults(config: DatasphereConfig) -> None:
    assert config.browser == "CHROME"
    assert config.redirect_uri == "http://localhost:8080"
    assert config.timeout == 60.0


def test_config_is_frozen(config: DatasphereConfig) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.base_url = "https://other.example"  # type: ignore[misc]


def test_client_requires_secret(config: DatasphereConfig) -> None:
    config = dataclasses.replace(config, client_secret="")
    with pytest.raises(MissingCredentials):
        DatasphereClient(config)


def test_client_rejects_unknown_browser(config: DatasphereConfig) -> None:
    config = dataclasses.replace(config, browser="FIREFOX")  # type: ignore
    with pytest.raises(InvalidConfiguration):
        DatasphereClient(config)
