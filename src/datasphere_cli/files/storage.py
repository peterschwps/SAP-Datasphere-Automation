import csv
import json
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO, cast

from datasphere_cli.files.workspace import (
    RESULT_FILES,
    TASK_FILES,
    result_path,
    task_path,
)


class CsvRowValidationError(ValueError):
    """Raised when a task CSV row does not match its declared schema."""

    def __init__(self, path: Path, row_number: int, reason: str) -> None:
        self.path = path
        self.row_number = row_number
        self.reason = reason
        super().__init__(
            f"Invalid CSV row {row_number} in '{path}': {reason}."
        )


def _atomic_write(path: Path, writer: Callable[[TextIO], object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            writer(cast(TextIO, temporary_file))
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def read_task_csv(
    command: str,
    root: str | Path | None = None,
) -> list[dict[str, str]]:
    """Read and validate one command's task records."""
    definition = TASK_FILES[command]
    path = task_path(command, root)
    with path.open(newline="", encoding="utf-8") as task_file:
        reader = csv.reader(task_file)
        expected = list(definition.columns or ())
        try:
            actual_columns = next(reader)
        except StopIteration:
            actual_columns = []
        if actual_columns != expected:
            raise CsvRowValidationError(
                path,
                1,
                f"expected columns {expected}, got {actual_columns}",
            )
        records: list[dict[str, str]] = []
        for row in reader:
            row_number = reader.line_num
            if len(row) < len(expected):
                missing = expected[len(row) :]
                raise CsvRowValidationError(
                    path,
                    row_number,
                    f"missing cells for {missing}",
                )
            if len(row) > len(expected):
                raise CsvRowValidationError(
                    path,
                    row_number,
                    f"expected {len(expected)} cells, got "
                    f"{len(row)}",
                )
            blank = [
                column
                for column, value in zip(expected, row, strict=True)
                if not value.strip()
            ]
            if blank:
                raise CsvRowValidationError(
                    path,
                    row_number,
                    f"blank required values for {blank}",
                )
            records.append(dict(zip(expected, row, strict=True)))
        return records


def initialize_result(
    command: str,
    root: str | Path | None = None,
    *,
    space: str | None = None,
) -> Path:
    """Create a missing result schema without replacing an existing result."""
    definition = RESULT_FILES[command]
    path = result_path(command, root, space=space)
    if path.exists():
        return path

    if definition.columns is None:

        def write_empty(result_file: TextIO) -> None:
            json.dump(
                {
                    "results": [],
                    "summary": {
                        "total": 0,
                        "succeeded": 0,
                        "failed": 0,
                        "skipped": 0,
                        "timed_out": 0,
                    },
                },
                result_file,
                indent=2,
            )
            result_file.write("\n")

        _atomic_write(path, write_empty)
    else:
        columns = definition.columns

        def write_header(result_file: TextIO) -> None:
            csv.DictWriter(
                result_file,
                fieldnames=columns,
            ).writeheader()

        _atomic_write(path, write_header)
    return path


def write_result_csv(
    command: str,
    rows: Sequence[Mapping[str, Any]],
    root: str | Path | None = None,
) -> Path:
    """Atomically replace one command's complete ordered CSV result."""
    definition = RESULT_FILES[command]
    if definition.columns is None:
        raise ValueError(f"Result for '{command}' is not CSV.")
    columns = definition.columns
    path = result_path(command, root)

    def write_rows(result_file: TextIO) -> None:
        writer = csv.DictWriter(
            result_file,
            fieldnames=columns,
            extrasaction="raise",
        )
        writer.writeheader()
        writer.writerows(rows)
    _atomic_write(path, write_rows)
    return path


def write_result_json(
    command: str,
    data: object,
    root: str | Path | None = None,
    *,
    space: str | None = None,
) -> Path:
    """Atomically replace one structured JSON command result."""
    definition = RESULT_FILES[command]
    if definition.columns is not None:
        raise ValueError(f"Result for '{command}' is not JSON.")
    path = result_path(command, root, space=space)

    def write_data(result_file: TextIO) -> None:
        json.dump(data, result_file, indent=2)
        result_file.write("\n")
    _atomic_write(path, write_data)
    return path
