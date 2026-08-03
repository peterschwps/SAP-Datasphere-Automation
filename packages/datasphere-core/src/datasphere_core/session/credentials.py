import asyncio
import json
from hashlib import sha256
from typing import Any, Protocol, cast

import keyring

from datasphere_core.errors import TokenStoreError

# Service name used in the credential store
TOKEN_SERVICE = "Datasphere-Core OAuth Tokens"

# Raw token response of the OAuth token endpoint. It lives here because the
# token store is the only part that outlives one session.
type TokenDict = dict[str, Any]


def build_credential_key(base_url: str, client_id: str) -> str:
    """
    Returns a stable, non-secret key for the tenant and client. Can be used as
    an identifier for storing multiple OAuth tokens for different tenants or
    clients in the credential store.

    Args:
        base_url (str): Base URL of the Datasphere tenant.
        client_id (str): OAuth client ID used against that tenant.

    Returns:
        str: Value identifying the tenant and client pair.
    """
    value = f"{base_url.rstrip('/')}\0{client_id}"
    return sha256(value.encode()).hexdigest()


class TokenStore(Protocol):
    """
    Simple protocol for credential stores that handle OAuth tokens
    (e.g. KeyringTokenStore or MemoryTokenStore).
    """
    async def load_tokens(self, key: str) -> TokenDict | None:
        """
        Loads the stored tokens of one tenant and client.

        Args:
            key (str): Credential key of the tenant and client.

        Returns:
            TokenDict | None: Stored tokens, or None if none exist.
        """
        ...

    async def save_tokens(self, key: str, tokens: TokenDict) -> None:
        """
        Stores the tokens of one tenant and client.

        Args:
            key (str): Credential key of the tenant and client.
            tokens (TokenDict): Tokens to store.
        """
        ...

    async def delete_tokens(self, key: str) -> None:
        """
        Deletes the stored tokens of one tenant and client.

        Args:
            key (str): Credential key of the tenant and client.
        """
        ...


class KeyringTokenStore:
    """
    Stores OAuth tokens in the OS credential store.
    """

    # INFO: Uses broad excepts to catch all errors. Not all backends report a
    #       KeyringError, e.g. the Windows backend raises pywintypes.error.

    async def load_tokens(self, key: str) -> TokenDict | None:
        """
        Loads a token (stored as a 'password') from the credential store.

        Args:
            key (str): Unique identifier for the tenant and client (e.g. the
                       value returned by build_credential_key()).

        Raises:
            TokenStoreError: If the stored tokens are not valid JSON.
            TokenStoreError: If the stored tokens have an invalid structure
                             (JSON but not a dict).

        Returns:
            TokenDict | None: Retrieved tokens or None if no tokens are stored
                              for the given key.
        """
        value = await self._get_password(key)
        if value is None:
            return None
        try:
            tokens = json.loads(value)
        except json.JSONDecodeError as error:
            raise TokenStoreError(
                "Stored session tokens are not valid JSON."
            ) from error
        if not isinstance(tokens, dict):
            raise TokenStoreError(
                "Stored session tokens have an invalid structure."
            )
        return cast(TokenDict, tokens)

    async def save_tokens(self, key: str, tokens: TokenDict) -> None:
        """
        Stores the TokenDict in the credential store.

        Args:
            key (str): Unique identifier for the tenant and client (e.g. the
                       value returned by build_credential_key()).
            tokens (TokenDict): Tokens to store.
        """
        value = json.dumps(tokens, separators=(",", ":"))
        await self._set_password(key, value)

    async def delete_tokens(self, key: str) -> None:
        """
        Deletes the stored tokens in the credential store.

        Args:
            key (str): Unique identifier for the tenant and client (e.g. the
                       value returned by build_credential_key()).
        """
        await self._delete_password(key)

    async def _get_password(self, key: str) -> str | None:
        """
        Loads the password from the credential store for the TOKEN_SERVICE name
        and a given username (key).

        Args:
            key (str): Unique identifier for the tenant and client (e.g. the
                       value returned by build_credential_key()).

        Raises:
            TokenStoreError: If the password could not be read from the
                             credential store.

        Returns:
            str | None: Password or None if no password is stored for the
                        given key.
        """
        try:
            return await asyncio.to_thread(
                keyring.get_password,
                TOKEN_SERVICE,
                key,
            )
        except Exception as error:
            raise TokenStoreError(
                "Unable to read from the operating system credential store."
            ) from error

    async def _set_password(self, key: str, value: str) -> None:
        """
        Sets a password in the credential store for the TOKEN_SERVICE name and
        a given username (key).

        Args:
            key (str): Unique identifier for the tenant and client (e.g. the
                       value returned by build_credential_key()).
            value (str): Password to store.

        Raises:
            TokenStoreError: If the password could not be written to the
                             credential store.
        """
        try:
            await asyncio.to_thread(
                keyring.set_password,
                TOKEN_SERVICE,
                key,
                value,
            )
        except Exception as error:
            raise TokenStoreError(
                "Unable to write to the operating system credential store."
            ) from error

    async def _delete_password(self, key: str) -> None:
        """
        Deletes a password in the credential store for the TOKEN_SERVICE name
        and a given username (key). Returns silently if no password is stored
        for the given key.

        Args:
            key (str): Unique identifier for the tenant and client (e.g. the
                       value returned by build_credential_key()).

        Raises:
            TokenStoreError: If the password could not be deleted from the
                             credential store.
        """
        # Skip if no password is stored for the given key
        if await self._get_password(key) is None:
            return
        try:
            await asyncio.to_thread(
                keyring.delete_password,
                TOKEN_SERVICE,
                key,
            )
        except Exception as error:
            raise TokenStoreError(
                "Unable to delete from the operating system credential store."
            ) from error
