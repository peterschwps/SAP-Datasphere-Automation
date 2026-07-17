import contextlib
import os
import sys
import webbrowser
from pathlib import Path
from typing import Literal

from datasphere_core import SessionConfig
from platformdirs import user_config_dir
from pydantic import BaseModel, ValidationError, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from datasphere_cli.utils.logging import logger

# Paths
_CONFIG_DIR = Path(user_config_dir("Datasphere"))
SETTINGS_FILE = _CONFIG_DIR / "settings.toml"

# Template for new settings files (with explanatory comments)
SETTINGS_TEMPLATE = """\
[setup]
# Your SAP Datasphere URL
# (System > Administration > Tenant Links: SAP Datasphere URL)
datasphere_url = "https://example.eu10.hcs.cloud.sap"

# The Authorization URL for OAuth Clients
# (System > Administration > App Integration: Authorization URL)
authorization_url = "https://example.authentication.eu10.hana.ondemand.com/oauth/authorize"

# The Token URL for OAuth Clients
# (System > Administration > App Integration: Token URL)
token_url = "https://example.authentication.eu10.hana.ondemand.com/oauth/token"

# Browser to use for the initial authentication: 'CHROME' or 'EDGE'
browser_to_use = "CHROME"

[credentials]
# OAuth Client ID of your Configured Client
# (System > Administration > App Integration: Configured Clients)
client_id = ""

# Secret of your Configured Client
# NOTE: Can be left empty and set with the environment variable
# 'SECRET' instead.
secret = ""
"""


class SetupSettings(BaseModel):
    """
    Tenant URLs and the browser used for the interactive login.
    """
    datasphere_url: str
    authorization_url: str
    token_url: str
    browser_to_use: Literal["CHROME", "EDGE"] = "CHROME"

    @field_validator("browser_to_use", mode="before")
    def to_upper(cls, value: str) -> str:
        """
        Converts the browser name to uppercase so it matches the
        supported values.

        Args:
            value (str): Configured browser name.

        Returns:
            str: Browser name in uppercase.
        """
        if isinstance(value, str):
            return value.upper()
        return value


class CredentialsSettings(BaseModel):
    """
    OAuth client credentials of the "Interactive Usage" client.
    """
    client_id: str
    secret: str = ""


class Settings(BaseSettings):
    """
    Application settings loaded from the settings.toml file in the user
    configuration directory.
    """
    model_config = SettingsConfigDict(toml_file=SETTINGS_FILE)
    setup: SetupSettings
    credentials: CredentialsSettings

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """
        Loads the settings exclusively from the TOML file.

        Returns:
            tuple[PydanticBaseSettingsSource, ...]: Settings sources.
        """
        return (TomlConfigSettingsSource(settings_cls),)


# Loaded settings instance (populated by load_settings())
settings: Settings | None = None


def create_settings_file() -> None:
    """
    Creates a new settings file filled with example values. Provides
    additional information to the user and exits the program afterwards.
    """
    SETTINGS_FILE.write_text(SETTINGS_TEMPLATE, encoding="utf-8")
    logger.info("Created new settings file at '%s'.", SETTINGS_FILE)
    logger.debug("Opening file...")
    logger.debug("Please fill it and restart the program.")
    with contextlib.suppress(Exception):
        webbrowser.open(f"file://{SETTINGS_FILE}")
    sys.exit()


def reload_settings() -> None:
    """
    (Re-)loads and validates the settings file into the global settings
    object.

    Raises:
        ValidationError: If the settings file is invalid.
    """
    global settings
    settings = Settings()  # pyright: ignore[reportCallIssue]


def load_settings() -> None:
    """
    Loads the settings file. Creates a new settings file (and exits) if
    it doesn't exist. Exits with a readable error message if the file
    is invalid.
    """
    # Create config directory if it doesn't exist
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Create settings if file doesn't exist
    if not SETTINGS_FILE.is_file():
        create_settings_file()

    # Load and validate settings
    try:
        reload_settings()
    except ValidationError as error:
        logger.error("Invalid settings file:\n%s", error)
        logger.error(
            "Please fix '%s' and restart the program.", SETTINGS_FILE
        )
        sys.exit(1)


def get_settings() -> Settings:
    """
    Returns the loaded settings. Loads them first if needed.

    Returns:
        Settings: Loaded settings instance.
    """
    if settings is None:
        load_settings()
    assert settings is not None
    return settings


def build_session_config() -> SessionConfig:
    """
    Builds the session configuration from the settings file. The client
    secret can also be provided via the 'SECRET' environment variable.

    Returns:
        SessionConfig: Configuration for the Datasphere session.
    """
    current = get_settings()
    client_secret = current.credentials.secret or os.environ.get("SECRET")
    if not client_secret:
        raise ValueError(
            "Client secret not found. Add it to the settings file or set "
            "the 'SECRET' environment variable."
        )
    return SessionConfig(
        base_url=current.setup.datasphere_url,
        authorization_url=current.setup.authorization_url,
        token_url=current.setup.token_url,
        client_id=current.credentials.client_id,
        client_secret=client_secret,
        browser=current.setup.browser_to_use,
    )
