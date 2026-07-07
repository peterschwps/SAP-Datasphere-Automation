import asyncio
import logging
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

import httpx

from datasphere_api.auth import (
    TokenStore,
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

        # Initialize session and token store
        self.config = config
        self.session: httpx.AsyncClient = httpx.AsyncClient(
            timeout=config.timeout,
            follow_redirects=True,
        )
        self.token_store = TokenStore(config.session_file)

        # Lazily created resource instances
        self._analytical_models: AnalyticalModels | None = None
        self._remote_tables: RemoteTables | None = None
        self._task_chains: TaskChains | None = None
        self._views: Views | None = None

    async def login(self) -> None:
        """
        Authenticates the session against the Datasphere tenant. Refreshes
        cached tokens from the token store if they exist. Falls back to
        the interactive browser login if no tokens are cached or the
        refresh fails.

        Raises:
            AuthenticationFailed: If the interactive login fails.
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

        # Try to refresh cached tokens
        tokens = self.token_store.load()
        if tokens is not None and "refresh_token" in tokens:
            logger.info("Loading session tokens...")
            new_tokens = await refresh_tokens(
                config=self.config,
                session=self.session,
                refresh_token=tokens["refresh_token"],
            )
            if new_tokens is not None:
                self._apply_tokens(new_tokens)
                return
            logger.warning("Starting a new login...")
            self.token_store.delete()
        else:
            logger.debug("No session tokens found.")

        # Start interactive login
        logger.debug("Opening browser window to log in...")
        tokens = await authenticate_interactively(
            config=self.config,
            session=self.session,
        )
        self._apply_tokens(tokens)

    def _apply_tokens(self, tokens: dict) -> None:
        """
        Adds the access token to the session headers and persists the
        tokens in the token store.

        Args:
            tokens (dict): Tokens returned by the token endpoint.
        """
        self.session.headers.update(
            {"Authorization": f"Bearer {tokens['access_token']}"}
        )
        self.token_store.save(tokens)

    async def aclose(self) -> None:
        """
        Closes the underlying httpx session.
        """
        await self.session.aclose()

    async def run_async_tasks(
        self,
        items: Iterable,
        function: Callable,
        thread_count: int = 1,
    ) -> None:
        """
        Executes the given function. 'Parallelizes' the tasks if the
        thread count is greater than 1.

        Args:
            items (Iterable): List of all arguments to be passed to the
                              function.
            function (Callable): Function to be executed.
            thread_count (int, optional): Amount of concurrent
                                          asynchronous tasks.
                                          Default is 1.
        """
        if thread_count > 1:
            semaphore = asyncio.Semaphore(thread_count)
            tasks = []
            for item in items:

                async def process_item(item):
                    async with semaphore:
                        if isinstance(item, list | tuple):
                            await function(*item)
                        else:
                            await function(item)

                task = asyncio.create_task(process_item(item))
                tasks.append(task)
            await asyncio.gather(*tasks)

        else:
            for item in items:
                if isinstance(item, list | tuple):
                    await function(*item)
                else:
                    await function(item)

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
