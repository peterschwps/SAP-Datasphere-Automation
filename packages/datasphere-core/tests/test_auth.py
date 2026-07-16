from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from datasphere_api import (
    AuthenticationFailed,
    DatasphereClient,
    DatasphereConfig,
    TokenDict,
)
from datasphere_core import (
    DatasphereSession,
    SessionConfig,
    SessionNotAuthenticatedError,
)


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
    return SessionConfig(
        base_url="https://tenant.example",
        authorization_url="https://auth.example/authorize",
        token_url="https://auth.example/token",
        client_id="client-id",
        client_secret=client_secret,
    )


def _client_factory(
    calls: list[tuple[TokenDict | None, bool]],
    configs: list[DatasphereConfig],
) -> Any:
    def create(config: DatasphereConfig) -> DatasphereClient:
        configs.append(config)

        async def login(
            tokens: TokenDict | None = None,
            *,
            allow_interactive_fallback: bool = True,
        ) -> TokenDict:
            calls.append((tokens, allow_interactive_fallback))
            return {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
            }

        async def aclose() -> None:
            return None

        return cast(
            DatasphereClient,
            SimpleNamespace(
                login=login,
                aclose=aclose,
                session=SimpleNamespace(headers={}),
                task_chains=SimpleNamespace(),
            ),
        )

    return create


async def test_session_loads_and_replaces_tokens(tmp_path: Path) -> None:
    config = _config()
    store = MemoryTokenStore()
    store.tokens[config.credential_key] = {
        "access_token": "old-access",
        "refresh_token": "old-refresh",
    }
    calls: list[tuple[TokenDict | None, bool]] = []
    configs: list[DatasphereConfig] = []
    session = DatasphereSession(
        config,
        token_store=store,
        client_factory=_client_factory(calls, configs),
        lock_directory=tmp_path,
    )

    await session.authenticate(interactive=False)

    assert calls == [
        (
            {
                "access_token": "old-access",
                "refresh_token": "old-refresh",
            },
            False,
        )
    ]
    assert store.tokens[config.credential_key] == {
        "access_token": "new-access",
        "refresh_token": "new-refresh",
    }
    assert configs[0].client_secret == "secret"
    assert session.client is not None


def test_session_config_requires_client_secret() -> None:
    with pytest.raises(ValueError, match="Client secret"):
        _config(client_secret=" ")


async def test_session_preserves_tokens_after_failed_login(
    tmp_path: Path,
) -> None:
    config = _config()
    store = MemoryTokenStore()
    store.tokens[config.credential_key] = {
        "access_token": "old-access",
        "refresh_token": "old-refresh",
    }

    def create(api_config: DatasphereConfig) -> DatasphereClient:
        async def login(
            tokens: TokenDict | None = None,
            *,
            allow_interactive_fallback: bool = True,
        ) -> TokenDict:
            raise AuthenticationFailed("Invalid client secret")

        async def aclose() -> None:
            return None

        return cast(
            DatasphereClient,
            SimpleNamespace(login=login, aclose=aclose),
        )

    session = DatasphereSession(
        config,
        token_store=store,
        client_factory=create,
        lock_directory=tmp_path,
    )

    with pytest.raises(AuthenticationFailed):
        await session.authenticate(interactive=True)

    assert store.tokens[config.credential_key] == {
        "access_token": "old-access",
        "refresh_token": "old-refresh",
    }


def test_session_requires_authentication_before_client_access(
    tmp_path: Path,
) -> None:
    session = DatasphereSession(
        _config(),
        token_store=MemoryTokenStore(),
        lock_directory=tmp_path,
    )

    with pytest.raises(SessionNotAuthenticatedError):
        _ = session.client


async def test_session_logout_deletes_tokens(
    tmp_path: Path,
) -> None:
    config = _config()
    store = MemoryTokenStore()
    store.tokens[config.credential_key] = {"access_token": "access"}
    session = DatasphereSession(
        config,
        token_store=store,
        lock_directory=tmp_path,
    )

    await session.logout()

    assert store.tokens == {}
