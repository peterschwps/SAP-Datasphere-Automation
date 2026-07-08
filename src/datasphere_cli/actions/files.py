import csv
import json
from collections.abc import Mapping
from typing import Any, cast

from datasphere_cli.utils.filehandler import ALL_FILES
from datasphere_cli.utils.logging import logger


def read_task_csv(file_key: str) -> list[dict[str, str]]:
    """
    Reads a task file and returns its rows (without the header).

    Args:
        file_key (str): Key of the task file in ALL_FILES.

    Returns:
        list[dict[str, str]]: All rows of the task file.
    """
    file = ALL_FILES[file_key]
    with open(
        file["absolute_path"], newline="", encoding="utf-8"
    ) as task_file:
        reader = csv.DictReader(
            task_file,
            fieldnames=file["columns"],
        )
        return list(reader)[1:]


def append_result_row(
    file_key: str,
    row: Mapping[str, Any],
) -> None:
    """
    Appends a single row to a result/export file. Only the configured
    columns of the file are written.

    Args:
        file_key (str): Key of the result file in ALL_FILES.
        row (Mapping[str, Any]): Row to append.
    """
    file = ALL_FILES[file_key]
    with open(
        file["absolute_path"], "a", newline="", encoding="utf-8"
    ) as result_file:
        writer = csv.DictWriter(
            result_file,
            fieldnames=file["columns"],
            extrasaction="ignore",
        )
        writer.writerow(row)


def prefill_result_rows(
    file_key: str,
    rows: list[dict[str, Any]],
) -> None:
    """
    Pre-fills a result file with one row per task so results can be
    updated incrementally during long runs.

    Args:
        file_key (str): Key of the result file in ALL_FILES.
        rows (list[dict[str, Any]]): Rows to append.
    """
    file = ALL_FILES[file_key]
    with open(
        file["absolute_path"], "a", newline="", encoding="utf-8"
    ) as result_file:
        writer = csv.DictWriter(
            result_file,
            fieldnames=file["columns"],
            extrasaction="ignore",
        )
        writer.writerows(rows)


def update_result_row(
    file_key: str,
    row: Mapping[str, Any],
) -> None:
    """
    Updates the row matching 'entity' and 'space' in a result file.
    Reads the whole file and writes it back with the updated values.

    Args:
        file_key (str): Key of the result file in ALL_FILES.
        row (Mapping[str, Any]): Row with the new values.
    """
    file = ALL_FILES[file_key]

    # Read all rows (header is consumed by the DictReader)
    with open(
        file["absolute_path"], newline="", encoding="utf-8"
    ) as result_file:
        rows = list(csv.DictReader(result_file))

    # Update matching row
    for existing in rows:
        if (
            existing["entity"] == row["entity"]
            and existing["space"] == row["space"]
        ):
            for key, value in row.items():
                if key in file["columns"]:
                    existing[key] = value

    # Write back the whole file
    with open(
        file["absolute_path"], "w", newline="", encoding="utf-8"
    ) as result_file:
        writer = csv.DictWriter(result_file, fieldnames=file["columns"])
        writer.writeheader()
        writer.writerows(rows)


def write_json_export(
    file_key: str,
    data: dict,
    file_name: str | None = None,
) -> None:
    """
    Writes data to a JSON export file.

    Args:
        file_key (str): Key of the export file in ALL_FILES.
        data (dict): Data to write.
        file_name (str | None, optional): Path to use instead of the
                                          configured one. Defaults to
                                          None.
    """
    if file_name is None:
        file_name = cast(str, ALL_FILES[file_key]["absolute_path"])
    with open(file_name, "w", encoding="utf-8") as export_file:
        json.dump(data, export_file, indent=4)


def log_results_saved(file_key: str) -> None:
    """
    Logs the path of the result/export file.

    Args:
        file_key (str): Key of the file in ALL_FILES.
    """
    logger.info(
        "Results saved to '%s'.", ALL_FILES[file_key]["absolute_path"]
    )
