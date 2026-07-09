import httpx
import respx

from datasphere_api import DatasphereClient
from tests.conftest import TOKEN_URL


@respx.mock
async def test_login_refreshes_given_tokens(
    client: DatasphereClient,
) -> None:
    # Prepare a successful refresh response
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "new-access", "refresh_token": "new-ref"},
        )
    )
    tokens = await client.login(
        {"access_token": "old-access", "refresh_token": "old-refresh"}
    )

    # Check session header and returned tokens
    assert client.session.headers["Authorization"] == "Bearer new-access"
    assert tokens == {
        "access_token": "new-access",
        "refresh_token": "new-ref",
    }


@respx.mock
async def test_login_falls_back_to_interactive(
    client: DatasphereClient,
    monkeypatch,
) -> None:
    # Prepare a failing refresh response
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
    tokens = await client.login(
        {"access_token": "old-access", "refresh_token": "expired"}
    )

    # Check fallback result
    assert (
        client.session.headers["Authorization"] == "Bearer browser-access"
    )
    assert tokens == {
        "access_token": "browser-access",
        "refresh_token": "ref",
    }


async def test_login_without_tokens_starts_interactive(
    client: DatasphereClient,
    monkeypatch,
) -> None:
    # Stub the interactive login
    async def fake_authenticate(config, session):
        return {"access_token": "browser-access", "refresh_token": "ref"}

    monkeypatch.setattr(
        "datasphere_api.client.authenticate_interactively",
        fake_authenticate,
    )
    tokens = await client.login()

    # Check that no refresh was attempted and tokens are returned
    assert (
        client.session.headers["Authorization"] == "Bearer browser-access"
    )
    assert tokens["refresh_token"] == "ref"


def test_resources_are_cached(client: DatasphereClient) -> None:
    assert client.views is client.views
    assert client.task_chains is client.task_chains
    assert client.remote_tables is client.remote_tables
    assert client.analytical_models is client.analytical_models
