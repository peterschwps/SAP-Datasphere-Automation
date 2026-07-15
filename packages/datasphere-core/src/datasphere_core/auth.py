import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from datasphere_api import (
    Browser,
    DatasphereClient,
    DatasphereConfig,
)
from filelock import AsyncFileLock
from platformdirs import user_cache_path

from datasphere_core.credentials import (
    CredentialStore,
    KeyringCredentialStore,
    build_credential_key,
)
from datasphere_core.errors import SessionNotAuthenticatedError


@dataclass(frozen=True, slots=True)
class SessionConfig:
    """
    Configuration required to create an authenticated API session.
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
        Validates if a client cecret was provided.

        Raises:
            ValueError: If no slient secret was provided.
        """
        if not self.client_secret.strip():
            raise ValueError("Client secret must not be empty.")

    def to_api_config(self) -> DatasphereConfig:
        """
        Creates the API configuration.
        """
        return DatasphereConfig(
            base_url=self.base_url,
            authorization_url=self.authorization_url,
            token_url=self.token_url,
            client_id=self.client_id,
            client_secret=self.client_secret,
            browser=self.browser,
            redirect_uri=self.redirect_uri,
            timeout=self.timeout,
        )

    @property
    def credential_key(self) -> str:
        """
        Returns a stable, non-secret key for the tenant and client.
        """
        return build_credential_key(self.base_url, self.client_id)


# Type alias for a factory function that creates a DatasphereClient
# (can be overridden for testing purposes)
type ClientFactory = Callable[[DatasphereConfig], DatasphereClient]


class DatasphereSession:
    """
    Owns one authenticated API client and its persisted OAuth tokens.
    """

    def __init__(
        self,
        config: SessionConfig,
        *,
        credential_store: CredentialStore | None = None,
        client_factory: ClientFactory = DatasphereClient,
        lock_directory: Path | None = None,
    ) -> None:
        """
        Initializes an instance of the DatasphereSession class.

        Args:
            config (SessionConfig): Configuration to create an SAP Datasphere
                                    session.
            credential_store (CredentialStore | None, optional):
                Credential store used to store OAuth tokens. If None, the OS
                credential store will be used. This argument is mainly used
                to provide a different credential store when running tests.
                Defaults to None.
            client_factory (ClientFactory, optional):
                A callable that receives a DatasphereConfig and returns a
                DatasphereClient. This argument is mainly used to provide a
                mock client when running tests.
                Defaults to DatasphereClient.
            lock_directory (Path | None, optional):
                Path where a lock file should be created. This is done to
                prevent parallel processes from writing tokens. If None, the
                default cache directory will be used. This argument is mainly
                used to provide a temporary directory when running tests.
                Defaults to None.
        """
        self._config = config
        self._credential_store = credential_store or KeyringCredentialStore()
        self._client_factory = client_factory
        self._client: DatasphereClient | None = None
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
    def client(self) -> DatasphereClient:
        """
        Returns the authenticated API client.
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
            CredentialStoreError: If local tokens could not be read or written.
        """
        # Start authentication with lock to prevent parallel processes from
        # writing tokens
        async with self._lock, self._file_lock:

            # Load identifier to load and store tokens in the credential store
            key = self._config.credential_key

            # Create the API client if it doesn't exist yet
            if self._client is None:
                api_config = self._config.to_api_config()
                self._client = self._client_factory(api_config)

            # Load tokens from the credential store and login
            tokens = await self._credential_store.load_tokens(key)
            new_tokens = await self._client.login(
                tokens=tokens,
                allow_interactive_fallback=interactive,
            )

            # Save tokens to the credential store (only saves if they changed)
            await self._credential_store.save_tokens(key, new_tokens)

    async def logout(self) -> None:
        """
        Deletes persisted credentials for the configured tenant.
        """
        async with self._lock, self._file_lock:
            key = self._config.credential_key
            await self._credential_store.delete_tokens(key)
            if self._client is not None:
                self._client.session.headers.pop("Authorization", None)

    async def aclose(self) -> None:
        """
        Closes the API client when one was created.
        """
        if self._client is not None:
            await self._client.aclose()

    async def __aenter__(self) -> "DatasphereSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()
