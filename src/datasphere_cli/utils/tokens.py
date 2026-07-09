import json
from pathlib import Path

from datasphere_api import TokenDict
from platformdirs import user_data_dir

from datasphere_cli.utils.logging import logger


class TokenStore:

    def __init__(self, path: Path | None = None):
        """
        Initializes the token store. The store persists the raw token
        response of the OAuth token endpoint as a JSON file so sessions
        can be shared between consumers of the Datasphere API library.

        Args:
            path (Path | None, optional): Path of the token file.
                                          Defaults to None, which
                                          resolves to 'session.json' in
                                          the user data directory of
                                          'Datasphere'.
        """
        if path is None:
            path = Path(user_data_dir("Datasphere")) / "session.json"
        self.path = path

    def load(self) -> TokenDict | None:
        """
        Loads the cached tokens from the token file. Deletes the file if
        it cannot be parsed.

        Returns:
            TokenDict | None: Cached tokens if the file exists and is
                              valid, else None.
        """
        if not self.path.is_file():
            return None
        try:
            with open(self.path, encoding="utf-8") as token_file:
                return json.load(token_file)
        except json.JSONDecodeError:
            logger.warning("Token file is corrupt. Deleting file...")
            self.delete()
            return None

    def save(self, tokens: TokenDict) -> None:
        """
        Saves tokens to the token file. Creates the parent directory if
        it doesn't exist yet.

        Args:
            tokens (TokenDict): Tokens to save.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as token_file:
            json.dump(tokens, token_file)

    def delete(self) -> None:
        """
        Deletes the token file if it exists.
        """
        self.path.unlink(missing_ok=True)
