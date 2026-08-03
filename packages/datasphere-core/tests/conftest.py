from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from datasphere_api import DatasphereClient
from datasphere_core import CommandContext

# Tenant the mocked requests are matched against
BASE_URL = "https://datasphere.example"


@pytest.fixture
async def session() -> AsyncIterator[httpx.AsyncClient]:
    """
    Yields a session that resolves the relative paths of the commands.
    """
    async with httpx.AsyncClient(base_url=BASE_URL) as session:
        yield session


@pytest.fixture
def context(
    session: httpx.AsyncClient,
) -> Callable[..., CommandContext]:
    """
    Yields a factory for command contexts around the mocked session.
    """
    def build(**callbacks: Any) -> CommandContext:
        """
        Builds one command context.

        Args:
            **callbacks (Any): Progress and batch item callbacks to report to.

        Returns:
            CommandContext: Context for one command execution.
        """
        return CommandContext(
            client=cast(DatasphereClient, SimpleNamespace(session=session)),
            **callbacks,
        )

    return build
