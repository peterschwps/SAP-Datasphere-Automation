import csv
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from datasphere_cli.models import TaskRow
from datasphere_cli.utils.logging import logger

# Working directory of the program (task file and run folders)
DATA_DIR = Path("datasphere")
TASKS_FILE = DATA_DIR / "tasks.csv"
RUNS_DIR = DATA_DIR / "runs"

# Columns of the shared task file and the uniform result files
TASK_COLUMNS = ["entity", "space", "attribute"]
RESULT_COLUMNS = ["entity", "space", "success", "detail", "runtime"]


def read_tasks() -> list[TaskRow]:
    """
    Reads the shared task file and returns its rows. Creates an empty
    task file with the column header if it doesn't exist yet and
    prompts the user to fill it.

    Returns:
        list[TaskRow]: All rows of the task file.
    """
    # Create an empty task file on the first run
    if not TASKS_FILE.is_file():
        TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TASKS_FILE, "w", newline="", encoding="utf-8") as task_file:
            writer = csv.DictWriter(task_file, fieldnames=TASK_COLUMNS)
            writer.writeheader()
        logger.info("Created new task file at '%s'.", TASKS_FILE)
        logger.info("Please fill it and run the action again.")
        return []

    # Read all rows (the header is consumed by the DictReader)
    with open(TASKS_FILE, newline="", encoding="utf-8") as task_file:
        rows = cast(list[TaskRow], list(csv.DictReader(task_file)))
    if not rows:
        logger.info("Task file '%s' is empty.", TASKS_FILE)
    return rows


class Run:

    def __init__(self, action: str):
        """
        Initializes a run folder for a single action execution. All
        result and export files of the action are written into the
        folder 'datasphere/runs/<timestamp>_<action>/'.

        Args:
            action (str): Slug of the action (e.g. 'persist-views').
        """
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.path = RUNS_DIR / f"{timestamp}_{action}"
        self.path.mkdir(parents=True, exist_ok=True)
        self._results_file = self.path / "results.csv"
        self._export_file = self.path / "export.csv"

    def _append_rows(
        self,
        path: Path,
        rows: list[Mapping[str, Any]],
        columns: list[str],
    ) -> None:
        """
        Appends rows to a CSV file. Writes the column header first if
        the file doesn't exist yet.

        Args:
            path (Path): Path of the CSV file.
            rows (list[Mapping[str, Any]]): Rows to append.
            columns (list[str]): Columns to write.
        """
        write_header = not path.is_file()
        with open(path, "a", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(
                file, fieldnames=columns, extrasaction="ignore"
            )
            if write_header:
                writer.writeheader()
            writer.writerows(rows)

    def append_result(self, row: Mapping[str, Any]) -> None:
        """
        Appends a single row to the result file of the run.

        Args:
            row (Mapping[str, Any]): Row to append.
        """
        self._append_rows(self._results_file, [row], RESULT_COLUMNS)

    def prefill_results(self, rows: list[Mapping[str, Any]]) -> None:
        """
        Pre-fills the result file with one row per task so results can
        be updated incrementally during long runs.

        Args:
            rows (list[Mapping[str, Any]]): Rows to append.
        """
        self._append_rows(self._results_file, rows, RESULT_COLUMNS)

    def update_result(self, row: Mapping[str, Any]) -> None:
        """
        Updates the row matching 'entity' and 'space' in the result
        file. Reads the whole file and writes it back with the updated
        values.

        Args:
            row (Mapping[str, Any]): Row with the new values.
        """
        # Read all rows (the header is consumed by the DictReader)
        with open(
            self._results_file, newline="", encoding="utf-8"
        ) as file:
            rows = list(csv.DictReader(file))

        # Update matching row
        for existing in rows:
            if (
                existing["entity"] == row["entity"]
                and existing["space"] == row["space"]
            ):
                for key, value in row.items():
                    if key in RESULT_COLUMNS:
                        existing[key] = value

        # Write back the whole file
        with open(
            self._results_file, "w", newline="", encoding="utf-8"
        ) as file:
            writer = csv.DictWriter(file, fieldnames=RESULT_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    def append_export_row(
        self,
        row: Mapping[str, Any],
        columns: list[str],
    ) -> None:
        """
        Appends a single row to the CSV export file of the run.

        Args:
            row (Mapping[str, Any]): Row to append.
            columns (list[str]): Columns of the export.
        """
        self._append_rows(self._export_file, [row], columns)

    def write_export_json(
        self,
        data: dict,
        file_name: str = "export.json",
    ) -> None:
        """
        Writes data to a JSON export file of the run.

        Args:
            data (dict): Data to write.
            file_name (str, optional): Name of the export file.
                                       Defaults to "export.json".
        """
        with open(
            self.path / file_name, "w", encoding="utf-8"
        ) as export_file:
            json.dump(data, export_file, indent=4)

    def log_saved(self) -> None:
        """
        Logs the path of the run folder.
        """
        logger.info("Results saved to '%s'.", self.path)
