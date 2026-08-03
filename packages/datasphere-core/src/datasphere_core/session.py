from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from datasphere_core.credentials import build_credential_key
from datasphere_core.errors import InvalidConfigurationError

# Browsers supported for the interactive OAuth login
type Browser = Literal["CHROME", "EDGE"]

# Mapping of browser names to Playwright channel identifiers
BROWSER_MAPPING: dict[str, str] = {
    "CHROME": "chrome",
    "EDGE": "msedge",
}

# Headers every request of a session carries. The tenant only serves the
# endpoints its web UI uses, so the session presents itself as a browser.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0"
    ),
    "Accept": "text/plain, */*; q=0.01",
    "Accept-Encoding": "gzip, deflate, zstd",
    "Accept-Language": "en",
}


@dataclass(frozen=True, slots=True)
class SessionConfig:
    """
    Configuration of one Datasphere session. All URLs and credentials can be
    found in the tenant under: System > Administration > App Integration.
    """
    base_url: str
    authorization_url: str
    token_url: str
    client_id: str
    client_secret: str
    browser: Browser = "EDGE"
    redirect_uri: str = "http://localhost:8080"
    timeout: float = 60.0

    def __post_init__(self) -> None:
        """
        Validates the credentials and the browser of the configuration.

        Raises:
            ValueError: If no client secret was provided.
            InvalidConfigurationError: If the browser is not supported.
        """
        if not self.client_secret.strip():
            raise ValueError("Client secret must not be empty.")
        if self.browser not in BROWSER_MAPPING:
            raise InvalidConfigurationError(
                f"Unsupported browser '{self.browser}'. Supported browsers "
                f"are: {', '.join(BROWSER_MAPPING)}."
            )

    @property
    def credential_key(self) -> str:
        """
        Returns a stable, non-secret key for the tenant and client.
        """
        return build_credential_key(self.base_url, self.client_id)


def request_headers(**extra: str) -> dict[str, str]:
    """
    Builds the headers a Datasphere request carries. Every request gets its
    own identifier, which the tenant echoes in its logs.

    Args:
        **extra (str): Additional headers, merged over the defaults.

    Returns:
        dict[str, str]: Headers for one request.
    """
    return {"Accept": "*/*", "x-request-id": uuid4().hex, **extra}
