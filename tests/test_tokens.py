import json
from pathlib import Path

from platformdirs import user_data_dir

from datasphere_cli.utils.tokens import TokenStore


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


def test_token_store_save_creates_directories(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dirs" / "session.json"
    store = TokenStore(path)
    store.save({"access_token": "abc"})
    with open(path, encoding="utf-8") as token_file:
        assert json.load(token_file) == {"access_token": "abc"}
