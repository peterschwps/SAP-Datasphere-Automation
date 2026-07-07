from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from datasphere_api import DatasphereClient, DatasphereConfig

BASE_URL = "https://datasphere.example"
TOKEN_URL = "https://auth.example/oauth/token"


@pytest.fixture
def config(tmp_path: Path) -> DatasphereConfig:
    return DatasphereConfig(
        base_url=BASE_URL,
        authorization_url="https://auth.example/oauth/authorize",
        token_url=TOKEN_URL,
        client_id="client-id",
        client_secret="client-secret",
        session_file=tmp_path / "session.json",
    )


@pytest.fixture
async def client(
    config: DatasphereConfig,
) -> AsyncIterator[DatasphereClient]:
    client = DatasphereClient(config)
    yield client
    await client.aclose()
