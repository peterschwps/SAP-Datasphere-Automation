"""File-backed wrappers around the datasphere-api client.

Each function in this module backs one menu entry of the TUI: it reads
the task files, calls the datasphere-api library and writes the results
to the export/result files. All file handling lives here — the library
itself only returns data.
"""

import csv
import json
from collections.abc import Mapping
from typing import Any, cast

from datasphere_api import DatasphereClient
from datasphere_api.models import (
    ModelRef,
    PartitionTask,
    StatisticsType,
    ViewRef,
)

from sap_datasphere_automation.utils.filehandler import ALL_FILES
from sap_datasphere_automation.utils.logging import logger

# ------------------------------ Helpers ---------------------------------

def _read_task_csv(file_key: str) -> list[dict[str, str]]:
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


def _append_result_row(
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


def _prefill_result_rows(
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


def _update_result_row(
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


def _write_json_export(
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


def _log_results_saved(file_key: str) -> None:
    """
    Logs the path of the result/export file.

    Args:
        file_key (str): Key of the file in ALL_FILES.
    """
    logger.info(
        "Results saved to '%s'.", ALL_FILES[file_key]["absolute_path"]
    )


# -------------------------- Analytical Models ---------------------------

async def get_all_views_for_analytical_models(
    client: DatasphereClient,
    skip_duplicates: bool,
    thread_count: int,
) -> None:
    """
    Exports all analytical models and their associated views to a file.

    Args:
        client (DatasphereClient): Authenticated client.
        skip_duplicates (bool): If True, views that already occur in
                                other analytical models are filtered out.
        thread_count (int): Amount of concurrent asynchronous requests.
    """
    models = await (
        client.analytical_models.get_all_views_for_analytical_models(
            skip_duplicates=skip_duplicates,
            thread_count=thread_count,
        )
    )
    _write_json_export("ANALYTICAL_MODELS_ALL_VIEWS", models)
    _log_results_saved("ANALYTICAL_MODELS_ALL_VIEWS")


async def get_all_views_for_analytical_models_in_space(
    client: DatasphereClient,
    space_name: str,
    skip_duplicates: bool,
    thread_count: int,
) -> None:
    """
    Exports all analytical models of a space with their associated views
    to a file. The space name becomes part of the file name.

    Args:
        client (DatasphereClient): Authenticated client.
        space_name (str): Name of the space.
        skip_duplicates (bool): If True, views that already occur in
                                other analytical models are filtered out.
        thread_count (int): Amount of concurrent asynchronous requests.
    """
    models = await (
        client.analytical_models.get_all_views_for_analytical_models_in_space(
            space_name=space_name,
            skip_duplicates=skip_duplicates,
            thread_count=thread_count,
        )
    )
    file_name = ALL_FILES["ANALYTICAL_MODELS_ALL_VIEWS_IN_SPACE"][
        "absolute_path"
    ].replace("space", space_name)
    _write_json_export(
        "ANALYTICAL_MODELS_ALL_VIEWS_IN_SPACE", models, file_name=file_name
    )
    logger.info("Results saved to '%s'.", file_name)


async def check_runtime_for_all_views_of_analytical_models(
    client: DatasphereClient,
    thread_count: int,
) -> None:
    """
    Checks the persistence times of all views for the analytical models
    in the task file. Saves the results incrementally to a JSON file.

    Args:
        client (DatasphereClient): Authenticated client.
        thread_count (int): Amount of concurrent asynchronous requests.
    """
    models = cast(
        list[ModelRef],
        _read_task_csv("ANALYTICAL_MODELS_ALL_VIEWS_PERSISTENCE_TIME"),
    )
    result_key = "ANALYTICAL_MODELS_ALL_VIEWS_PERSISTENCE_TIME_RESULT"

    # Save the report at every state change (crash resilience during
    # hours-long runs)
    report = await (
        client.analytical_models
        .check_runtime_for_all_views_of_analytical_models(
            models=models,
            thread_count=thread_count,
            on_update=lambda report: _write_json_export(result_key, report),
        )
    )
    _write_json_export(result_key, report)
    _log_results_saved(result_key)


# ----------------------------- Remote Tables ----------------------------

async def create_statistics(
    client: DatasphereClient,
    statistics_type: StatisticsType,
    thread_count: int,
) -> None:
    """
    Creates statistics for all remote tables.

    Args:
        client (DatasphereClient): Authenticated client.
        statistics_type (StatisticsType): Type of the statistic.
        thread_count (int): Amount of concurrent asynchronous requests.
    """
    await client.remote_tables.create_statistics(
        statistics_type=statistics_type,
        thread_count=thread_count,
    )


async def refresh_statistics(
    client: DatasphereClient,
    thread_count: int,
) -> None:
    """
    Refreshes statistics for all remote tables.

    Args:
        client (DatasphereClient): Authenticated client.
        thread_count (int): Amount of concurrent asynchronous requests.
    """
    await client.remote_tables.refresh_statistics(
        thread_count=thread_count,
    )


# ------------------------------ Task Chains -----------------------------

async def run_task_chains(
    client: DatasphereClient,
    thread_count: int,
) -> None:
    """
    Runs all task chains from the task file and saves the results.

    Args:
        client (DatasphereClient): Authenticated client.
        thread_count (int): Amount of concurrent asynchronous requests.
    """
    chains = cast(list[ViewRef], _read_task_csv("TASK_CHAIN_RUN"))
    _prefill_result_rows(
        "TASK_CHAIN_RUN_RESULT",
        [
            {
                "entity": chain["entity"],
                "space": chain["space"],
                "isCompleted": False,
                "runtime": None,
            }
            for chain in chains
        ],
    )
    await client.task_chains.run(
        chains=chains,
        thread_count=thread_count,
        on_result=lambda result: _update_result_row(
            "TASK_CHAIN_RUN_RESULT", result
        ),
    )
    _log_results_saved("TASK_CHAIN_RUN_RESULT")


# -------------------------------- Views ---------------------------------

async def create_view_analytics(
    client: DatasphereClient,
    thread_count: int,
) -> None:
    """
    Runs the view analyzer for all views and exports the views with a
    persistence score of 10.

    Args:
        client (DatasphereClient): Authenticated client.
        thread_count (int): Amount of concurrent asynchronous requests.
    """
    await client.views.create_view_analytics(
        thread_count=thread_count,
        on_result=lambda result: _append_result_row("VIEW_ANALYSE", result),
    )
    _log_results_saved("VIEW_ANALYSE")


async def get_all_views_where_attribute_contains(
    client: DatasphereClient,
    word: str,
    thread_count: int,
) -> None:
    """
    Exports all views with an attribute that contains the search word.

    Args:
        client (DatasphereClient): Authenticated client.
        word (str): Search word (case-insensitive).
        thread_count (int): Amount of concurrent asynchronous requests.
    """
    await client.views.get_all_views_where_attribute_contains(
        word=word,
        thread_count=thread_count,
        on_result=lambda result: _append_result_row(
            "VIEW_ATTRIBUTE", result
        ),
    )
    _log_results_saved("VIEW_ATTRIBUTE")


async def create_partitioning_for_views(
    client: DatasphereClient,
    partitions: list[str],
    overwrite_existing_partitions: bool,
    thread_count: int,
) -> None:
    """
    Creates partitions for all views from the task file and saves the
    results.

    Args:
        client (DatasphereClient): Authenticated client.
        partitions (list[str]): List of all partitions to be created in
                                the correct order.
        overwrite_existing_partitions (bool): If True, existing
                                              partitions will get
                                              overwritten.
        thread_count (int): Amount of concurrent asynchronous requests.
    """
    views = cast(
        list[PartitionTask], _read_task_csv("VIEW_PARTITIONING_CREATE")
    )
    await client.views.create_partitioning_for_views(
        views=views,
        partitions=partitions,
        overwrite_existing_partitions=overwrite_existing_partitions,
        thread_count=thread_count,
        on_result=lambda result: _append_result_row(
            "VIEW_PARTITIONING_CREATE_RESULT", result
        ),
    )
    _log_results_saved("VIEW_PARTITIONING_CREATE_RESULT")


async def remove_partitioning_for_views(
    client: DatasphereClient,
    thread_count: int,
) -> None:
    """
    Removes partitions for all views from the task file and saves the
    results.

    Args:
        client (DatasphereClient): Authenticated client.
        thread_count (int): Amount of concurrent asynchronous requests.
    """
    views = cast(list[ViewRef], _read_task_csv("VIEW_PARTITIONING_DELETE"))
    await client.views.remove_partitioning_for_views(
        views=views,
        thread_count=thread_count,
        on_result=lambda result: _append_result_row(
            "VIEW_PARTITIONING_DELETE_RESULT", result
        ),
    )
    _log_results_saved("VIEW_PARTITIONING_DELETE_RESULT")


async def lock_partitions_until_year(
    client: DatasphereClient,
    year: int,
    thread_count: int,
) -> None:
    """
    Locks partitions for all views from the task file up to (and
    including) the given year and saves the results.

    Args:
        client (DatasphereClient): Authenticated client.
        year (int): Year up to which partitions should be locked.
        thread_count (int): Amount of concurrent asynchronous requests.
    """
    views = cast(list[ViewRef], _read_task_csv("VIEW_PARTITION_LOCK"))
    await client.views.lock_partitions_until_year(
        views=views,
        year=year,
        thread_count=thread_count,
        on_result=lambda result: _append_result_row(
            "VIEW_PARTITION_LOCK_RESULT", result
        ),
    )
    _log_results_saved("VIEW_PARTITION_LOCK_RESULT")


async def unlock_all_partitions(
    client: DatasphereClient,
    thread_count: int,
) -> None:
    """
    Unlocks all partitions for all views from the task file and saves
    the results.

    Args:
        client (DatasphereClient): Authenticated client.
        thread_count (int): Amount of concurrent asynchronous requests.
    """
    views = cast(list[ViewRef], _read_task_csv("VIEW_PARTITION_UNLOCK"))
    await client.views.unlock_all_partitions(
        views=views,
        thread_count=thread_count,
        on_result=lambda result: _append_result_row(
            "VIEW_PARTITION_UNLOCK_RESULT", result
        ),
    )
    _log_results_saved("VIEW_PARTITION_UNLOCK_RESULT")


async def persist_views(
    client: DatasphereClient,
    timer: bool,
    thread_count: int,
) -> None:
    """
    Persists all views from the task file and saves the results
    incrementally.

    Args:
        client (DatasphereClient): Authenticated client.
        timer (bool): If True, the duration of the persistence run is
                      saved.
        thread_count (int): Amount of concurrent asynchronous requests.
    """
    views = cast(list[ViewRef], _read_task_csv("VIEW_PERSIST"))
    _prefill_result_rows(
        "VIEW_PERSIST_RESULT",
        [
            {
                "entity": view["entity"],
                "space": view["space"],
                "isPersisted": False,
                "runtime": None,
            }
            for view in views
        ],
    )
    await client.views.persist_views(
        views=views,
        thread_count=thread_count,
        timer=timer,
        on_result=lambda result: _update_result_row(
            "VIEW_PERSIST_RESULT", result
        ),
    )
    _log_results_saved("VIEW_PERSIST_RESULT")


async def unpersist_views(
    client: DatasphereClient,
    thread_count: int,
) -> None:
    """
    Removes the persistence for all views from the task file and saves
    the results incrementally.

    Args:
        client (DatasphereClient): Authenticated client.
        thread_count (int): Amount of concurrent asynchronous requests.
    """
    views = cast(list[ViewRef], _read_task_csv("VIEW_UNPERSIST"))
    _prefill_result_rows(
        "VIEW_UNPERSIST_RESULT",
        [
            {
                "entity": view["entity"],
                "space": view["space"],
                "isRemoved": False,
            }
            for view in views
        ],
    )
    await client.views.unpersist_views(
        views=views,
        thread_count=thread_count,
        on_result=lambda result: _update_result_row(
            "VIEW_UNPERSIST_RESULT", result
        ),
    )
    _log_results_saved("VIEW_UNPERSIST_RESULT")
