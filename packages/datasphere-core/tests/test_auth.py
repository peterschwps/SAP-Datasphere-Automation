import dataclasses
from pathlib import Path

import httpx
import pytest
import respx
from datasphere_core import (
    AuthenticationError,
    DatasphereSession,
    InvalidConfigurationError,
    SessionConfig,
    SessionNotAuthenticatedError,
    TokenDict,
)
from datasphere_core import auth as auth_module

TOKEN_URL = "https://auth.example/token"


class MemoryTokenStore:
    def __init__(self) -> None:
        self.tokens: dict[str, TokenDict] = {}

    async def load_tokens(self, key: str) -> TokenDict | None:
        return self.tokens.get(key)

    async def save_tokens(self, key: str, tokens: TokenDict) -> None:
        self.tokens[key] = tokens

    async def delete_tokens(self, key: str) -> None:
        self.tokens.pop(key, None)


def _config(client_secret: str = "secret") -> SessionConfig:
    """
    Builds a session configuration for the test tenant.
    """
    return SessionConfig(
        base_url="https://tenant.example",
        authorization_url="https://auth.example/authorize",
        token_url=TOKEN_URL,
        client_id="client-id",
        client_secret=client_secret,
    )


def _store(**tokens: str) -> tuple[SessionConfig, MemoryTokenStore]:
    """
    Builds a configuration and a token store already holding the tokens.
    """
    config = _config()
    store = MemoryTokenStore()
    if tokens:
        store.tokens[config.credential_key] = dict(tokens)
    return config, store


@respx.mock
async def test_session_loads_and_replaces_tokens(tmp_path: Path) -> None:
    """
    Checks that a session refreshes stored tokens and writes back the new one.
    """
    config, store = _store(
        access_token="old-access",
        refresh_token="old-refresh",
    )
    token = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
            },
        )
    )

    async with DatasphereSession(
        config,
        token_store=store,
        lock_directory=tmp_path,
    ) as session:
        await session.authenticate(interactive=False)

        # Only the refresh token is persisted, the access token is short-lived
        assert store.tokens[config.credential_key] == {
            "refresh_token": "new-refresh",
        }
        assert session.client.headers["Authorization"] == "Bearer new-access"

    # The stored refresh token is what the session refreshed with
    body = token.calls.last.request.content.decode()
    assert "grant_type=refresh_token" in body
    assert "refresh_token=old-refresh" in body


@respx.mock
async def test_session_keeps_tokens_without_a_new_refresh_token(
    tmp_path: Path,
) -> None:
    """
    Checks that a login without a refresh token leaves the stored one alone.
    """
    config, store = _store(refresh_token="old-refresh")
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "new-access"})
    )

    async with DatasphereSession(
        config,
        token_store=store,
        lock_directory=tmp_path,
    ) as session:
        await session.authenticate(interactive=False)

    # Overwriting with nothing would force an interactive login next time
    assert store.tokens[config.credential_key] == {
        "refresh_token": "old-refresh",
    }


@respx.mock
async def test_session_preserves_tokens_after_failed_login(
    tmp_path: Path,
) -> None:
    """
    Checks that stored tokens survive a failed login.
    """
    config, store = _store(
        access_token="old-access",
        refresh_token="old-refresh",
    )
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(401, json={"error": "invalid_token"})
    )

    async with DatasphereSession(
        config,
        token_store=store,
        lock_directory=tmp_path,
    ) as session:
        with pytest.raises(AuthenticationError):
            await session.authenticate(interactive=False)

    # A rejected refresh must not cost the token that may still work later
    assert store.tokens[config.credential_key] == {
        "access_token": "old-access",
        "refresh_token": "old-refresh",
    }


@respx.mock
async def test_session_falls_back_to_the_browser_login(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """
    Checks that an expired refresh token opens the browser login.
    """
    config, store = _store(refresh_token="expired")
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(401, json={"error": "invalid_token"})
    )

    async def browser_login(
        config: SessionConfig,
        session: httpx.AsyncClient,
    ) -> TokenDict:
        return {
            "access_token": "browser-access",
            "refresh_token": "browser-refresh",
        }

    monkeypatch.setattr(
        auth_module,
        "authenticate_interactively",
        browser_login,
    )

    async with DatasphereSession(
        config,
        token_store=store,
        lock_directory=tmp_path,
    ) as session:
        await session.authenticate(interactive=True)

        assert session.client.headers["Authorization"] == (
            "Bearer browser-access"
        )

    assert store.tokens[config.credential_key] == {
        "refresh_token": "browser-refresh",
    }


@respx.mock
async def test_session_without_tokens_skips_the_refresh(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """
    Checks that a session without stored tokens logs in interactively.
    """
    config, store = _store()
    token = respx.post(TOKEN_URL)

    async def browser_login(
        config: SessionConfig,
        session: httpx.AsyncClient,
    ) -> TokenDict:
        return {"access_token": "browser-access"}

    monkeypatch.setattr(
        auth_module,
        "authenticate_interactively",
        browser_login,
    )

    async with DatasphereSession(
        config,
        token_store=store,
        lock_directory=tmp_path,
    ) as session:
        await session.authenticate(interactive=True)

    # Without a refresh token there is nothing the token endpoint could do
    assert not token.called


async def test_session_requires_an_interactive_login_to_be_allowed(
    tmp_path: Path,
) -> None:
    """
    Checks that a session refuses to open a browser when told not to.
    """
    config, store = _store()

    async with DatasphereSession(
        config,
        token_store=store,
        lock_directory=tmp_path,
    ) as session:
        with pytest.raises(AuthenticationError, match="Interactive login"):
            await session.authenticate(interactive=False)


def test_session_requires_authentication_before_client_access(
    tmp_path: Path,
) -> None:
    """
    Checks that the client is unavailable before authentication.
    """
    session = DatasphereSession(
        _config(),
        token_store=MemoryTokenStore(),
        lock_directory=tmp_path,
    )

    with pytest.raises(SessionNotAuthenticatedError):
        _ = session.client


async def test_session_logout_deletes_tokens(tmp_path: Path) -> None:
    """
    Checks that a logout removes the stored tokens.
    """
    config, store = _store(access_token="access")
    session = DatasphereSession(
        config,
        token_store=store,
        lock_directory=tmp_path,
    )

    await session.logout()

    assert store.tokens == {}


def test_session_config_defaults() -> None:
    """
    Checks the defaults a configuration does not have to spell out.
    """
    config = _config()

    assert config.browser == "EDGE"
    assert config.redirect_uri == "http://localhost:8080"
    assert config.timeout == 60.0


def test_session_config_requires_client_secret() -> None:
    """
    Checks that a configuration without a client secret is rejected.
    """
    with pytest.raises(ValueError, match="Client secret"):
        _config(client_secret=" ")


def test_session_config_rejects_an_unsupported_browser() -> None:
    """
    Checks that only a browser the login can drive is accepted.
    """
    with pytest.raises(InvalidConfigurationError, match="FIREFOX"):
        dataclasses.replace(_config(), browser="FIREFOX")  # type: ignore
