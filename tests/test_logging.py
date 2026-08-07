from pathlib import Path

from datasphere_core.logging import SUCCESS

from datasphere_cli import logging


def test_result_file_log_uses_clickable_absolute_uri(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """
    Checks that result messages link their file label to an absolute URI.
    """
    calls: list[tuple[int, str, tuple[object, ...]]] = []

    def record(level: int, message: str, *args: object) -> None:
        calls.append((level, message, args))

    monkeypatch.setattr(logging.logger, "log", record)
    path = tmp_path / "result with spaces.csv"

    logging.log_result_file(path)

    assert calls == [
        (
            SUCCESS,
            "Result saved to %s.",
            (
                f"[link={path.resolve().as_uri()}]"
                "[u]file[/u][/link]",
            ),
        )
    ]
