import json
from pathlib import Path

import httpx
import respx
from platformdirs import user_data_dir

from datasphere_api import DatasphereConfig, TokenStore
from datasphere_api.auth import refresh_tokens
from tests.conftest import TOKEN_URL


def test_token_store_roundtrip(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "session.json")
    tokens = {"access_token": "abc", "refresh_token": "def"}
    store.save(tokens)
    assert store.load() == tokens

    # Deleting removes the file
    store.delete()
    assert store.load() is None
    assert not store.path.is_file()


def test_token_store_deletes_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    path.write_text("{not json", encoding="utf-8")
    store = TokenStore(path)
    assert store.load() is None
    assert not path.is_file()


def test_token_store_default_path() -> None:
    store = TokenStore()
    expected = Path(user_data_dir("Datasphere")) / "session.json"
    assert store.path == expected


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


def test_token_store_save_creates_directories(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dirs" / "session.json"
    store = TokenStore(path)
    store.save({"access_token": "abc"})
    with open(path, encoding="utf-8") as token_file:
        assert json.load(token_file) == {"access_token": "abc"}
