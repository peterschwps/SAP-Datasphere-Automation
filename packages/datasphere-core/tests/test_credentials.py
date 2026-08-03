from datasphere_core import KeyringTokenStore
from datasphere_core.session.credentials import build_credential_key


def test_credential_key_normalizes_trailing_slash() -> None:
    """
    Checks that a trailing slash yields the same credential key.
    """
    assert build_credential_key(
        "https://tenant.example",
        "client-id",
    ) == build_credential_key(
        "https://tenant.example/",
        "client-id",
    )


async def test_keyring_store_serializes_tokens(monkeypatch) -> None:
    """
    Checks that tokens survive a round trip through the token store.
    """
    passwords: dict[tuple[str, str], str] = {}

    def get_password(service: str, key: str) -> str | None:
        return passwords.get((service, key))

    def set_password(service: str, key: str, value: str) -> None:
        passwords[(service, key)] = value

    monkeypatch.setattr(
        "datasphere_core.session.credentials.keyring.get_password",
        get_password,
    )
    monkeypatch.setattr(
        "datasphere_core.session.credentials.keyring.set_password",
        set_password,
    )
    store = KeyringTokenStore()

    await store.save_tokens(
        "key",
        {"access_token": "access", "refresh_token": "refresh"},
    )

    assert await store.load_tokens("key") == {
        "access_token": "access",
        "refresh_token": "refresh",
    }
