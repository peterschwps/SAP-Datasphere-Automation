import asyncio
import json

import httpx
import respx

from datasphere_api import DatasphereClient, DatasphereConfig
from tests.conftest import TOKEN_URL


@respx.mock
async def test_login_refreshes_cached_tokens(
    client: DatasphereClient,
    config: DatasphereConfig,
) -> None:
    # Prepare cached tokens and a successful refresh response
    client.token_store.save(
        {"access_token": "old-access", "refresh_token": "old-refresh"}
    )
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "new-access", "refresh_token": "new-ref"},
        )
    )
    await client.login()

    # Check session header and persisted tokens
    assert client.session.headers["Authorization"] == "Bearer new-access"
    assert config.session_file is not None
    with open(config.session_file, encoding="utf-8") as session_file:
        assert json.load(session_file)["access_token"] == "new-access"


@respx.mock
async def test_login_falls_back_to_interactive(
    client: DatasphereClient,
    monkeypatch,
) -> None:
    # Prepare cached tokens and a failing refresh response
    client.token_store.save(
        {"access_token": "old-access", "refresh_token": "expired"}
    )
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(401, json={"error": "invalid_token"})
    )

    # Stub the interactive login
    async def fake_authenticate(config, session):
        return {"access_token": "browser-access", "refresh_token": "ref"}

    monkeypatch.setattr(
        "datasphere_api.client.authenticate_interactively",
        fake_authenticate,
    )
    await client.login()

    # Check fallback result
    assert (
        client.session.headers["Authorization"] == "Bearer browser-access"
    )
    assert client.token_store.load() == {
        "access_token": "browser-access",
        "refresh_token": "ref",
    }


async def test_run_async_tasks_respects_semaphore(
    client: DatasphereClient,
) -> None:
    running = 0
    max_running = 0

    async def task(item: int) -> None:
        nonlocal running, max_running
        running += 1
        max_running = max(max_running, running)
        await asyncio.sleep(0.01)
        running -= 1

    await client.run_async_tasks(range(10), task, thread_count=3)
    assert max_running <= 3


async def test_run_async_tasks_unpacks_tuples(
    client: DatasphereClient,
) -> None:
    received = []

    async def task(first: str, second: int) -> None:
        received.append((first, second))

    await client.run_async_tasks([("a", 1), ("b", 2)], task)
    assert received == [("a", 1), ("b", 2)]


def test_resources_are_cached(client: DatasphereClient) -> None:
    assert client.views is client.views
    assert client.task_chains is client.task_chains
    assert client.remote_tables is client.remote_tables
    assert client.analytical_models is client.analytical_models
