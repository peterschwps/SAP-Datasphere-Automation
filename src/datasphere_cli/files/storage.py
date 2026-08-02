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
    """
    Raised when a task CSV row does not match its declared schema.
    """
    def __init__(self, path: Path, row_number: int, reason: str) -> None:
        """
        Initializes the error with the row that failed validation.

        Args:
            path (Path): Path of the task file.
            row_number (int): Number of the invalid row.
            reason (str): Reason the row was rejected.
        """
        self.path = path
        self.row_number = row_number
        self.reason = reason
        super().__init__(
            f"Invalid CSV row {row_number} in '{path}': {reason}."
        )


def _atomic_write(
    path: Path,
    writer: Callable[[TextIO], object],
) -> None:
    """
    Writes a file by replacing it atomically. The content is written to a
    temporary file first so an interrupted run never leaves a partial
    result behind.

    Args:
        path (Path): Path of the file to replace.
        writer (Callable[[TextIO], object]): Callable writing the content
                                             to the opened file.
    """
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
        # Clean up after a failed write
        # A successful replace already moved the temporary file away
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def read_task_csv(
    command: str,
    root: str | Path | None = None,
) -> list[dict[str, str]]:
    """
    Reads and validates one command's task records. A task file is edited by
    hand, so every deviation from the declared schema is reported with its
    row number instead of being silently skipped.

    Args:
        command (str): Command the task file belongs to.
        root (str | Path | None, optional): Explicit workspace root.
                                            Uses the default workspace when
                                            None. Defaults to None.

    Raises:
        CsvRowValidationError: If the header or any row does not match the
                               declared schema.

    Returns:
        list[dict[str, str]]: One dictionary per task row, keyed by column.
    """
    definition = TASK_FILES[command]
    path = task_path(command, root)
    with path.open(newline="", encoding="utf-8") as task_file:
        reader = csv.reader(task_file)
        expected = list(definition.columns or ())

        # Read the header row, which an empty file does not have
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
        # Validate every row
        # Separate checks so the message names the actual problem
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
    """
    Creates a missing result schema without replacing an existing result.
    An empty schema lets the user open the result file before the command
    finishes.

    Args:
        command (str): Command the result file belongs to.
        root (str | Path | None, optional): Explicit workspace root.
                                            Uses the default workspace when
                                            None. Defaults to None.
        space (str | None, optional): Space to scope the result file to.
                                      Defaults to None.

    Returns:
        Path: Path of the existing or newly created result file.
    """
    definition = RESULT_FILES[command]
    path = result_path(command, root, space=space)
    if path.exists():
        return path

    # Write an empty JSON result, marked by missing columns
    if definition.columns is None:

        def write_empty(result_file: TextIO) -> None:
            """
            Writes an empty JSON result with a zeroed summary.

            Args:
                result_file (TextIO): Opened result file to write to.
            """
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
            """
            Writes the CSV header of the result schema.

            Args:
                result_file (TextIO): Opened result file to write to.
            """
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
    """
    Atomically replaces one command's complete ordered CSV result.

    Args:
        command (str): Command the result file belongs to.
        rows (Sequence[Mapping[str, Any]]): Result rows in their final order.
        root (str | Path | None, optional): Explicit workspace root.
                                            Uses the default workspace when
                                            None. Defaults to None.

    Raises:
        ValueError: If the command writes a JSON result instead of a CSV one.

    Returns:
        Path: Path of the written result file.
    """
    definition = RESULT_FILES[command]
    if definition.columns is None:
        raise ValueError(f"Result for '{command}' is not CSV.")
    columns = definition.columns
    path = result_path(command, root)

    def write_rows(result_file: TextIO) -> None:
        """
        Writes the header and every result row.

        Args:
            result_file (TextIO): Opened result file to write to.
        """
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
    """
    Atomically replaces one structured JSON command result. Checkpointing
    commands call this repeatedly while they are still running.

    Args:
        command (str): Command the result file belongs to.
        data (object): Structured result to serialize.
        root (str | Path | None, optional): Explicit workspace root.
                                            Uses the default workspace when
                                            None. Defaults to None.
        space (str | None, optional): Space to scope the result file to.
                                      Defaults to None.

    Raises:
        ValueError: If the command writes a CSV result instead of a JSON one.

    Returns:
        Path: Path of the written result file.
    """
    definition = RESULT_FILES[command]
    if definition.columns is not None:
        raise ValueError(f"Result for '{command}' is not JSON.")
    path = result_path(command, root, space=space)

    def write_data(result_file: TextIO) -> None:
        """
        Writes the structured result as indented JSON.

        Args:
            result_file (TextIO): Opened result file to write to.
        """
        json.dump(data, result_file, indent=2)
        result_file.write("\n")
    _atomic_write(path, write_data)
    return path
