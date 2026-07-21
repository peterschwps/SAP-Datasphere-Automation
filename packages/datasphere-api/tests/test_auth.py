import httpx
import pytest
import respx

from datasphere_api import DatasphereConfig, InvalidConfiguration
from datasphere_api.auth import authenticate_interactively, refresh_tokens
from tests.conftest import TOKEN_URL


@respx.mock
async def test_refresh_tokens_success(config: DatasphereConfig) -> None:
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "new-access", "refresh_token": "new-ref"},
        )
    )
    async with httpx.AsyncClient() as session:
        tokens = await refresh_tokens(config, session, "old-refresh")

    # Check returned tokens and sent request
    assert tokens == {
        "access_token": "new-access",
        "refresh_token": "new-ref",
    }
    request = route.calls.last.request
    body = request.content.decode()
    assert "grant_type=refresh_token" in body
    assert "refresh_token=old-refresh" in body
    assert request.headers["Authorization"].startswith("Basic ")


@respx.mock
async def test_refresh_tokens_failure(config: DatasphereConfig) -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            401, json={"error": "invalid_token"}
        )
    )
    async with httpx.AsyncClient() as session:
        tokens = await refresh_tokens(config, session, "expired-refresh")
    assert tokens is None


@respx.mock
async def test_refresh_tokens_invalid_json(
    config: DatasphereConfig,
) -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, text="not json")
    )
    async with httpx.AsyncClient() as session:
        tokens = await refresh_tokens(config, session, "old-refresh")
    assert tokens is None


async def test_interactive_login_rejects_remote_redirect(
    config: DatasphereConfig,
) -> None:
    invalid = DatasphereConfig(
        base_url=config.base_url,
        authorization_url=config.authorization_url,
        token_url=config.token_url,
        client_id=config.client_id,
        client_secret=config.client_secret,
        redirect_uri="https://attacker.example/callback",
    )
    async with httpx.AsyncClient() as session:
        with pytest.raises(InvalidConfiguration):
            await authenticate_interactively(invalid, session)
