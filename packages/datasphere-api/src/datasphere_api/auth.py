import asyncio
import http.server
import json
import logging
import secrets
import socketserver
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from playwright.async_api import async_playwright

from datasphere_api.config import BROWSER_MAPPING, DatasphereConfig
from datasphere_api.exceptions import (
    AuthenticationFailed,
    InvalidConfiguration,
)

logger = logging.getLogger(__name__)

# Raw token response of the OAuth token endpoint
type TokenDict = dict[str, Any]


async def refresh_tokens(
    config: DatasphereConfig,
    session: httpx.AsyncClient,
    refresh_token: str,
) -> TokenDict | None:
    """
    Requests new tokens from the token endpoint using a refresh token.

    Args:
        config (DatasphereConfig): Configuration with the token URL and
                                   the client credentials.
        session (httpx.AsyncClient): Session to send the request with.
        refresh_token (str): Refresh token of a previous login.

    Returns:
        TokenDict | None: New tokens if the refresh was successful, else
                          None (e.g. if the refresh token has expired).
    """
    # Send refresh request
    auth = httpx.BasicAuth(
        username=config.client_id,
        password=config.client_secret,
    )
    try:
        response = await session.post(
            url=config.token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            auth=auth,
        )
    except httpx.HTTPError:
        logger.warning("Refreshing tokens failed due to a network error.")
        return None

    # Parse and validate response
    try:
        tokens = response.json()
    except json.JSONDecodeError:
        tokens = {}
    if response.status_code != 200 or "access_token" not in tokens:
        logger.warning(
            "Refreshing tokens failed with status code %s.",
            response.status_code,
        )
        return None
    return tokens


async def authenticate_interactively(
    config: DatasphereConfig,
    session: httpx.AsyncClient,
) -> TokenDict:
    """
    Runs the interactive OAuth authorization code flow. Starts a local
    callback server to receive the authorization code and opens a
    Playwright browser window for the user to log in. Exchanges the
    received code for tokens at the token endpoint.

    Args:
        config (DatasphereConfig): Configuration with the URLs, the
                                   client credentials and the browser to
                                   use for the login.
        session (httpx.AsyncClient): Session to send the token request
                                     with.

    Raises:
        AuthenticationFailed: If the login is not completed in time or
                              the token endpoint doesn't return tokens.

    Returns:
        TokenDict: Tokens returned by the token endpoint.
    """
    redirect = urlparse(config.redirect_uri)
    if (
        redirect.scheme != "http"
        or redirect.hostname not in ("localhost", "127.0.0.1")
        or redirect.username is not None
        or redirect.password is not None
        or redirect.query
        or redirect.fragment
    ):
        raise InvalidConfiguration(
            "The OAuth redirect URI must be an HTTP loopback URI without "
            "credentials, query parameters or fragments."
        )
    callback_path = redirect.path or "/"
    expected_state = secrets.token_urlsafe(32)

    class ReusableServer(socketserver.TCPServer):
        allow_reuse_address = True  # to allow immediate reuse of the port

    # Mutable container to store the callback code and access it from
    # different threads
    callback: dict[str, str | None] = {"code": None, "error": None}

    # Async handling of the callback server using an event to signal when
    # the code is received
    loop = asyncio.get_running_loop()
    received = asyncio.Event()

    @contextmanager
    def callback_server(port: int) -> Iterator[dict[str, str | None]]:
        """
        Context manager for the callback server. Everything before the
        yield is treated as __enter__. Everything after the yield is
        treated as __exit__.

        Args:
            port (int): Port to listen on.

        Yields:
            dict[str, str | None]: Mapping of the callback code received
                                   in a GET-request. The key is 'code'.
                                   The initial value is None.
        """
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                """
                Checks the query params of an incoming GET-request for a 'code'
                parameter. Assigns the value to the 'code' key in the callback
                dict and displays a short confirmation in the browser.
                """
                # Check if callback path matched
                request = urlparse(self.path)
                if request.path != callback_path:
                    self.send_error(404)
                    return

                # Fetch query params and compare expected state to prevent
                # handling other callbacks
                params = parse_qs(request.query)
                state = params.get("state", [None])[0]
                if not secrets.compare_digest(state or "", expected_state):
                    self.send_error(400)
                    return

                # Check if OAuth server returned an error
                oauth_error = params.get("error", [None])[0]
                if oauth_error:
                    callback["error"] = oauth_error
                    self.send_error(400)
                    loop.call_soon_threadsafe(received.set)
                    return

                # Fetch callback code
                callback_code = params.get("code", [None])[0]
                if callback_code:
                    callback["code"] = callback_code
                    self.send_response(200)
                    self.send_header(
                        "Content-Type",
                        "text/html; charset=utf-8",
                    )
                    self.end_headers()
                    self.wfile.write(
                        b"<h1>Code received</h1>"
                        b"<p>This window will be closed automatically.</p>"
                    )
                else:
                    callback["error"] = "missing_code"
                    self.send_error(400)

                # Set asyncio event to signal that the wait_for can be stopped
                loop.call_soon_threadsafe(received.set)

            def log_message(self, *args, **kwargs):
                """
                Overrides the default logs to hide output to the console.
                """
                return

        # Starts server in separate thread to not block the main thread
        with ReusableServer(("127.0.0.1", port), Handler) as server:
            thread = threading.Thread(
                target=server.serve_forever,
                daemon=True,
            )
            thread.start()
            try:
                yield callback
            finally:
                server.shutdown()
                thread.join(timeout=3)

    # Start callback server and open Playwright browser for authentication
    port = redirect.port or 80
    with callback_server(port):
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                channel=BROWSER_MAPPING[config.browser],
                headless=False,
            )
            page = await browser.new_page()

            # Add required query params to the authorization URL and open it
            parameters = urlencode(
                {
                    "response_type": "code",
                    "client_id": config.client_id,
                    "redirect_uri": config.redirect_uri,
                    "state": expected_state,
                }
            )
            authorization_url = (f"{config.authorization_url}?{parameters}")
            await page.goto(authorization_url)

            # Wait about 2 minutes for the user to complete the login
            try:
                await asyncio.wait_for(received.wait(), timeout=120)
            except TimeoutError:
                raise AuthenticationFailed(
                    "Timed out waiting for the login to complete."
                ) from None

            # check if OAuth server returned an error in the callback URL
            if callback["error"] is not None:
                raise AuthenticationFailed(
                    "The authorization server rejected the login."
                )

    # Send callback code to token endpoint to receive access tokens
    auth = httpx.BasicAuth(
        username=config.client_id,
        password=config.client_secret,
    )
    try:
        response = await session.post(
            url=config.token_url,
            data={
                "grant_type": "authorization_code",
                "code": callback["code"],
                "redirect_uri": config.redirect_uri,
            },
            auth=auth,
        )
    except httpx.HTTPError:
        raise AuthenticationFailed(
            "Unable to contact the token endpoint."
        ) from None

    # Parse and validate response
    try:
        tokens = response.json()
    except json.JSONDecodeError:
        tokens = {}
    if "access_token" not in tokens:
        raise AuthenticationFailed(
            "Token endpoint returned an unexpected response "
            f"[{response.status_code}]: {response.text}."
        )
    return tokens
