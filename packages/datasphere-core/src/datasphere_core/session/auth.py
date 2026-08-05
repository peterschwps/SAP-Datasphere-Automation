import asyncio
import logging
from pathlib import Path

import httpx
from filelock import AsyncFileLock
from platformdirs import user_cache_path

from datasphere_core.errors import (
    AuthenticationError,
    SessionNotAuthenticatedError,
)
from datasphere_core.http_logging import http_logging_hooks
from datasphere_core.logging import SUCCESS
from datasphere_core.session.config import DEFAULT_HEADERS, SessionConfig
from datasphere_core.session.credentials import (
    KeyringTokenStore,
    TokenDict,
    TokenStore,
)
from datasphere_core.session.oauth import (
    authenticate_interactively,
    refresh_tokens,
)

logger = logging.getLogger(__name__)


class DatasphereSession:
    """
    Owns one authenticated HTTP client and its persisted OAuth tokens.
    """

    def __init__(
        self,
        config: SessionConfig,
        *,
        token_store: TokenStore | None = None,
        lock_directory: Path | None = None,
    ) -> None:
        """
        Initializes an instance of the DatasphereSession class.

        Args:
            config (SessionConfig): Configuration to create an SAP Datasphere
                                    session.
            token_store (TokenStore | None, optional): Token store used to
                                                       persist OAuth tokens.
                                                       Uses the OS credential
                                                       store when None. Mainly
                                                       used to swap the store
                                                       in tests.
                                                       Defaults to None.
            lock_directory (Path | None, optional): Directory for the lock
                                                    file that keeps parallel
                                                    processes from writing
                                                    tokens at once. Uses the
                                                    default cache directory
                                                    when None. Mainly used to
                                                    point at a temporary
                                                    directory in tests.
                                                    Defaults to None.
        """
        self._config = config
        self._token_store = token_store or KeyringTokenStore()
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

        # Create a lock file
        directory = lock_directory or (
            user_cache_path("Datasphere-Core") / "locks"
        )
        directory.mkdir(parents=True, exist_ok=True)
        self._file_lock = AsyncFileLock(
            directory / f"{config.credential_key}.lock"
        )

    @property
    def client(self) -> httpx.AsyncClient:
        """
        Returns the authenticated HTTP client of the session.

        Raises:
            SessionNotAuthenticatedError: If the session was not
                                          authenticated yet.
        """
        if self._client is None:
            raise SessionNotAuthenticatedError(
                "The Datasphere session is not authenticated."
            )
        return self._client

    async def authenticate(self, *, interactive: bool) -> None:
        """
        Authenticates using cached tokens or an explicit browser login. This
        method needs to be called first if the session is not already
        authenticated (self._client=None).

        Args:
            interactive (bool): Whether to allow interactive login if no valid
                                refresh token is available.
        Raises:
            TokenStoreError: If local tokens could not be read or written.
            AuthenticationError: If interactive login is required but disabled,
                                 or if the interactive login fails.
        """
        # Start authentication with lock to prevent parallel processes from
        # writing tokens
        async with self._lock, self._file_lock:

            # Load identifier to load and store tokens in the credential store
            key = self._config.credential_key

            # Create the HTTP client if it doesn't exist yet
            if self._client is None:
                self._client = httpx.AsyncClient(
                    base_url=self._config.base_url,
                    timeout=self._config.timeout,
                    follow_redirects=True,
                    headers=DEFAULT_HEADERS,
                    # Add the hooks only while the requests are logged
                    event_hooks=http_logging_hooks(),
                )

            # Load tokens from the credential store and login
            tokens = await self._token_store.load_tokens(key)
            new_tokens = await self._login(
                tokens,
                allow_interactive_fallback=interactive,
            )

            # Store the refresh token to the credential store
            # All other tokens are not needed, since the token is always
            # refreshed on startup
            refresh_token = new_tokens.get("refresh_token")
            if refresh_token is not None:
                await self._token_store.save_tokens(
                    key,
                    {"refresh_token": refresh_token},
                )

    async def _login(
        self,
        tokens: TokenDict | None,
        *,
        allow_interactive_fallback: bool,
    ) -> TokenDict:
        """
        Authenticates the HTTP client against the tenant. Tries to refresh the
        given tokens if they contain a refresh token. Falls back to the
        interactive browser login if no tokens are given or the refresh fails,
        unless interactive fallback is disabled.

        Args:
            tokens (TokenDict | None): Tokens of a previous login to refresh.
            allow_interactive_fallback (bool): Whether to open a browser when
                                               no valid refresh token is
                                               available.

        Raises:
            AuthenticationError: If interactive login is required but disabled,
                                 or if the interactive login fails.

        Returns:
            TokenDict: Tokens returned by the token endpoint.
        """
        # Try to refresh the given tokens
        if tokens is not None and "refresh_token" in tokens:
            logger.info("Refreshing session tokens...")
            new_tokens = await refresh_tokens(
                config=self._config,
                session=self.client,
                refresh_token=tokens["refresh_token"],
            )
            if new_tokens is not None:
                # Only add saved refresh token to the new tokens if the token
                # endpoint didn't return a new one
                new_tokens.setdefault("refresh_token", tokens["refresh_token"])
                self._apply_tokens(new_tokens)
                logger.log(
                    SUCCESS,
                    "Successfully refreshed the session tokens.",
                )
                return new_tokens
            logger.warning(
                "Unable to refresh session tokens. Starting a new login..."
            )
        else:
            logger.debug("No session tokens provided.")

        if not allow_interactive_fallback:
            raise AuthenticationError(
                "Interactive login is required to authenticate."
            )

        # Start interactive login
        # Reported at info level, because the user has to act on the window
        logger.info("Opening browser window to log in...")
        new_tokens = await authenticate_interactively(
            config=self._config,
            session=self.client,
        )
        self._apply_tokens(new_tokens)
        logger.log(SUCCESS, "Successfully logged in.")
        return new_tokens

    def _apply_tokens(self, tokens: TokenDict) -> None:
        """
        Adds the access token to the client headers.

        Args:
            tokens (TokenDict): Tokens returned by the token endpoint.
        """
        self.client.headers.update(
            {"Authorization": f"Bearer {tokens['access_token']}"}
        )

    async def logout(self) -> None:
        """
        Deletes persisted credentials for the configured tenant.
        """
        async with self._lock, self._file_lock:
            key = self._config.credential_key
            await self._token_store.delete_tokens(key)
            if self._client is not None:
                self._client.headers.pop("Authorization", None)

    async def aclose(self) -> None:
        """
        Closes the HTTP client when one was created.
        """
        if self._client is not None:
            await self._client.aclose()

    async def __aenter__(self) -> "DatasphereSession":
        """
        Enters the session context.

        Returns:
            DatasphereSession: The session itself.
        """
        return self

    async def __aexit__(self, *args: object) -> None:
        """
        Closes the HTTP client when leaving the session context.
        """
        _ = args
        await self.aclose()
