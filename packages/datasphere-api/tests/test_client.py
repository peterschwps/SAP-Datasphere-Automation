import httpx
import pytest
import respx

from datasphere_api import AuthenticationFailed, DatasphereClient
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
async def test_login_preserves_unrotated_refresh_token(
    client: DatasphereClient,
) -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "new-access"})
    )

    tokens = await client.login(
        {"access_token": "old-access", "refresh_token": "old-refresh"}
    )

    assert tokens == {
        "access_token": "new-access",
        "refresh_token": "old-refresh",
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


@respx.mock
async def test_login_can_disable_interactive_fallback(
    client: DatasphereClient,
    monkeypatch,
) -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(401, json={"error": "invalid_token"})
    )

    async def fail_if_called(config, session):
        raise AssertionError("Interactive authentication must not be called")

    monkeypatch.setattr(
        "datasphere_api.client.authenticate_interactively",
        fail_if_called,
    )

    with pytest.raises(AuthenticationFailed):
        await client.login(
            {"access_token": "old-access", "refresh_token": "expired"},
            allow_interactive_fallback=False,
        )


async def test_login_without_tokens_can_disable_interactive_fallback(
    client: DatasphereClient,
    monkeypatch,
) -> None:
    async def fail_if_called(config, session):
        raise AssertionError("Interactive authentication must not be called")

    monkeypatch.setattr(
        "datasphere_api.client.authenticate_interactively",
        fail_if_called,
    )

    with pytest.raises(AuthenticationFailed):
        await client.login(allow_interactive_fallback=False)


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
