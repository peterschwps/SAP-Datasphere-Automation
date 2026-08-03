import dataclasses

import httpx
import pytest
import respx
from datasphere_core import InvalidConfigurationError, SessionConfig
from datasphere_core.session.oauth import (
    authenticate_interactively,
    refresh_tokens,
)

TOKEN_URL = "https://auth.example/token"


def _config() -> SessionConfig:
    """
    Builds a session configuration for the test tenant.
    """
    return SessionConfig(
        base_url="https://tenant.example",
        authorization_url="https://auth.example/authorize",
        token_url=TOKEN_URL,
        client_id="client-id",
        client_secret="client-secret",
    )


@respx.mock
async def test_refresh_returns_the_new_tokens() -> None:
    """
    Checks that a refresh sends its credentials and returns the new tokens.
    """
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "new-access", "refresh_token": "new-ref"},
        )
    )

    async with httpx.AsyncClient() as session:
        tokens = await refresh_tokens(_config(), session, "old-refresh")

    assert tokens == {
        "access_token": "new-access",
        "refresh_token": "new-ref",
    }

    # The client credentials go into the header, never into the body
    request = route.calls.last.request
    body = request.content.decode()
    assert "grant_type=refresh_token" in body
    assert "refresh_token=old-refresh" in body
    assert "client-secret" not in body
    assert request.headers["Authorization"].startswith("Basic ")


@respx.mock
async def test_refresh_reports_a_rejected_token() -> None:
    """
    Checks that a rejected refresh token yields no tokens.
    """
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(401, json={"error": "invalid_token"})
    )

    async with httpx.AsyncClient() as session:
        tokens = await refresh_tokens(_config(), session, "expired-refresh")

    # The caller falls back to the browser login, so this is not an error
    assert tokens is None


@respx.mock
async def test_refresh_reports_an_unreadable_answer() -> None:
    """
    Checks that an answer that is not JSON yields no tokens.
    """
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, text="not json")
    )

    async with httpx.AsyncClient() as session:
        tokens = await refresh_tokens(_config(), session, "old-refresh")

    assert tokens is None


@respx.mock
async def test_refresh_reports_an_unreachable_endpoint() -> None:
    """
    Checks that a network error yields no tokens instead of raising.
    """
    respx.post(TOKEN_URL).mock(side_effect=httpx.ConnectError)

    async with httpx.AsyncClient() as session:
        tokens = await refresh_tokens(_config(), session, "old-refresh")

    assert tokens is None


async def test_interactive_login_rejects_a_remote_redirect() -> None:
    """
    Checks that the callback is only ever awaited on the local machine.
    """
    # A remote redirect would hand the authorization code to someone else
    config = dataclasses.replace(
        _config(),
        redirect_uri="https://attacker.example/callback",
    )

    async with httpx.AsyncClient() as session:
        with pytest.raises(InvalidConfigurationError):
            await authenticate_interactively(config, session)
