import logging
from typing import TYPE_CHECKING

import httpx

from datasphere_api.auth import (
    TokenDict,
    authenticate_interactively,
    refresh_tokens,
)
from datasphere_api.config import BROWSER_MAPPING, DatasphereConfig
from datasphere_api.exceptions import (
    InvalidConfiguration,
    MissingCredentials,
)

if TYPE_CHECKING:
    from datasphere_api.resources.analytical_models import AnalyticalModels
    from datasphere_api.resources.remote_tables import RemoteTables
    from datasphere_api.resources.task_chains import TaskChains
    from datasphere_api.resources.views import Views

logger = logging.getLogger(__name__)


class DatasphereClient:

    def __init__(self, config: DatasphereConfig):
        """
        Initializes the client and its httpx session. Doesn't perform any
        file or network I/O.

        Args:
            config (DatasphereConfig): Configuration with the URLs and
                                       credentials of the tenant.

        Raises:
            MissingCredentials: If no client secret is configured.
            InvalidConfiguration: If an unsupported browser is configured.
        """
        # Validate configuration
        if not config.client_secret:
            raise MissingCredentials()
        if config.browser not in BROWSER_MAPPING:
            raise InvalidConfiguration(
                f"Unsupported browser '{config.browser}'. Supported "
                f"browsers are: {', '.join(BROWSER_MAPPING)}."
            )

        # Initialize session
        self.config = config
        self.session: httpx.AsyncClient = httpx.AsyncClient(
            timeout=config.timeout,
            follow_redirects=True,
        )

        # Lazily created resource instances
        self._analytical_models: AnalyticalModels | None = None
        self._remote_tables: RemoteTables | None = None
        self._task_chains: TaskChains | None = None
        self._views: Views | None = None

    async def login(self, tokens: TokenDict | None = None) -> TokenDict:
        """
        Authenticates the session against the Datasphere tenant. Tries
        to refresh the given tokens if they contain a refresh token.
        Falls back to the interactive browser login if no tokens are
        given or the refresh fails. Doesn't persist anything — the
        caller is responsible for caching the returned tokens.

        Args:
            tokens (TokenDict | None, optional): Tokens of a previous
                                                 login to refresh.
                                                 Defaults to None.

        Raises:
            AuthenticationFailed: If the interactive login fails.

        Returns:
            TokenDict: Tokens returned by the token endpoint.
        """
        # Set default headers
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/"
                    "537.36 (KHTML, like Gecko) Chrome/138.0.0.0 "
                    "Safari/537.36 Edg/138.0.0.0"
                ),
                "Accept": "text/plain, */*; q=0.01",
                "Accept-Encoding": "gzip, deflate, zstd",
                "Accept-Language": "en",
            }
        )

        # Try to refresh the given tokens
        if tokens is not None and "refresh_token" in tokens:
            logger.info("Refreshing session tokens...")
            new_tokens = await refresh_tokens(
                config=self.config,
                session=self.session,
                refresh_token=tokens["refresh_token"],
            )
            if new_tokens is not None:
                self._apply_tokens(new_tokens)
                return new_tokens
            logger.warning("Starting a new login...")
        else:
            logger.debug("No session tokens given.")

        # Start interactive login
        logger.debug("Opening browser window to log in...")
        new_tokens = await authenticate_interactively(
            config=self.config,
            session=self.session,
        )
        self._apply_tokens(new_tokens)
        return new_tokens

    def _apply_tokens(self, tokens: TokenDict) -> None:
        """
        Adds the access token to the session headers.

        Args:
            tokens (TokenDict): Tokens returned by the token endpoint.
        """
        self.session.headers.update(
            {"Authorization": f"Bearer {tokens['access_token']}"}
        )

    async def aclose(self) -> None:
        """
        Closes the underlying httpx session.
        """
        await self.session.aclose()

    @property
    def analytical_models(self) -> "AnalyticalModels":
        """
        Returns:
            AnalyticalModels: Resource for the analytical model APIs.
        """
        if self._analytical_models is None:
            from datasphere_api.resources.analytical_models import (
                AnalyticalModels,
            )
            self._analytical_models = AnalyticalModels(self)
        return self._analytical_models

    @property
    def remote_tables(self) -> "RemoteTables":
        """
        Returns:
            RemoteTables: Resource for the remote table APIs.
        """
        if self._remote_tables is None:
            from datasphere_api.resources.remote_tables import RemoteTables
            self._remote_tables = RemoteTables(self)
        return self._remote_tables

    @property
    def task_chains(self) -> "TaskChains":
        """
        Returns:
            TaskChains: Resource for the task chain APIs.
        """
        if self._task_chains is None:
            from datasphere_api.resources.task_chains import TaskChains
            self._task_chains = TaskChains(self)
        return self._task_chains

    @property
    def views(self) -> "Views":
        """
        Returns:
            Views: Resource for the view APIs.
        """
        if self._views is None:
            from datasphere_api.resources.views import Views
            self._views = Views(self)
        return self._views
