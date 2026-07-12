from dataclasses import dataclass
from typing import Literal

# Browsers supported for the interactive OAuth login
type Browser = Literal["CHROME", "EDGE"]

# Mapping of browser names to Playwright channel identifiers
BROWSER_MAPPING: dict[str, str] = {
    "CHROME": "chrome",
    "EDGE": "msedge",
}


@dataclass(frozen=True, slots=True)
class DatasphereConfig:
    """
    Configuration for the Datasphere client. All URLs and credentials can
    be found in the SAP Datasphere tenant under:  System > Administration >
    App Integration.

    Args:
        base_url (str): URL of the SAP Datasphere tenant.
        authorization_url (str): OAuth authorization URL of the tenant.
        token_url (str): OAuth token URL of the tenant.
        client_id (str): OAuth client ID of an "Interactive Usage" client.
        client_secret (str): OAuth client secret of the client.
        browser (Browser, optional): Browser to use for the interactive login.
                                     Has to be installed on the system.
                                     Defaults to "CHROME".
        redirect_uri (str, optional): Redirect URI configured for the OAuth
                                      client.
                                      Defaults to "http://localhost:8080".
        timeout (float, optional): Timeout for HTTP requests in seconds.
                                   Defaults to 60 seconds.
    """
    base_url: str
    authorization_url: str
    token_url: str
    client_id: str
    client_secret: str
    browser: Browser = "CHROME"
    redirect_uri: str = "http://localhost:8080"
    timeout: float = 60.0
