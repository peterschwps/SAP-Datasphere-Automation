import httpx
import respx

from datasphere_api import DatasphereConfig
from datasphere_api.auth import refresh_tokens
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
