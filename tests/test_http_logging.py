import json
from pathlib import Path

import pytest
from datasphere_core import is_http_logging, stop_http_logging

from datasphere_cli.http_logging import (
    HTTP_LOGGING_FILE_VARIABLE,
    HTTP_LOGGING_VARIABLE,
    configure_http_logging,
)


def test_logging_stays_off_without_the_variable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """
    Checks that an ordinary run neither logs nor creates a workspace.
    """
    monkeypatch.delenv(HTTP_LOGGING_VARIABLE, raising=False)
    monkeypatch.chdir(tmp_path)

    assert configure_http_logging() is None
    assert not is_http_logging()

    # Creating the workspace here would scatter folders through every run
    # that only wanted to print a result
    assert not (tmp_path / "datasphere").exists()


@pytest.mark.parametrize("setting", ["", "0", "true", "yes", "on"])
def test_only_the_documented_value_switches_logging_on(
    tmp_path: Path,
    monkeypatch,
    setting: str,
) -> None:
    """
    Checks that exactly one value starts the logging and nothing else does.
    """
    monkeypatch.setenv(HTTP_LOGGING_VARIABLE, setting)
    monkeypatch.chdir(tmp_path)

    assert configure_http_logging() is None
    assert not (tmp_path / "datasphere").exists()


def test_logging_writes_into_the_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """
    Checks that the log lands next to the task and result directories.
    """
    monkeypatch.setenv(HTTP_LOGGING_VARIABLE, "1")
    monkeypatch.chdir(tmp_path)

    path = configure_http_logging()
    stop_http_logging()

    assert path is not None
    assert path == tmp_path / "datasphere" / "http.jsonl"
    first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert first["event"] == "run_started"
    assert first["cwd"] == str(tmp_path)


def test_the_log_file_can_be_moved_elsewhere(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """
    Checks that the second variable overrides the file of the workspace.
    """
    target = tmp_path / "elsewhere" / "calls.jsonl"
    monkeypatch.setenv(HTTP_LOGGING_VARIABLE, "1")
    monkeypatch.setenv(HTTP_LOGGING_FILE_VARIABLE, str(target))
    monkeypatch.chdir(tmp_path)

    path = configure_http_logging()
    stop_http_logging()

    assert path == target
    assert target.exists()
    assert not (tmp_path / "datasphere").exists()
