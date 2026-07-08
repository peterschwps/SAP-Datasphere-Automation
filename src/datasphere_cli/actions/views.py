from typing import cast

from datasphere_api import DatasphereClient

from datasphere_cli.actions.files import (
    append_result_row,
    log_results_saved,
    prefill_result_rows,
    read_task_csv,
    update_result_row,
)
from datasphere_cli.models import PartitionTask, ViewRef
from datasphere_cli.utils.concurrency import run_async_tasks
from datasphere_cli.utils.logging import logger


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
    all_views = await client.views.get_all_views()

    # Function to analyze a view and save the best candidate
    async def analyze_view(view: dict) -> None:
        entity_stats = await client.views.analyze_view(
            view["name"], view["space_name"]
        )

        # Filter out the view with the best persistence score
        # (only one view can have score 10)
        best_view = [
            entity
            for entity in entity_stats
            if entity.get("persistencyCandidateScore", 0) == 10
        ]
        if not best_view:
            logger.debug("No view with a persistence score of 10 found.")
            return
        logger.info(
            "View '%s' in '%s' has a persistence score of 10.",
            best_view[0]["entity"],
            best_view[0]["space"],
        )
        append_result_row("VIEW_ANALYSE", best_view[0])

    await run_async_tasks(all_views, analyze_view, thread_count)
    log_results_saved("VIEW_ANALYSE")


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
    all_views = await client.views.get_all_views()
    logger.debug(
        "Searching for views that have an attribute "
        "containing the substring '%s'...",
        word,
    )

    # Function to check a view for matching attributes
    async def check_view(view: dict) -> None:
        logger.debug(
            "Checking view '%s' in '%s'...",
            view["name"],
            view["space_name"],
        )
        attributes = await client.views.get_view_attributes(
            view_id=view["id"],
            view_name=view["name"],
            space=view["space_name"],
        )
        for attribute in attributes:
            if word.lower() in attribute.lower():
                logger.info(
                    "View '%s' in '%s' has attribute '%s'.",
                    view["name"],
                    view["space_name"],
                    attribute,
                )
                append_result_row(
                    "VIEW_ATTRIBUTE",
                    {
                        "entity": view["name"],
                        "space": view["space_name"],
                        "businessName": view["business_name"],
                        "attribute": attribute,
                    },
                )

    await run_async_tasks(all_views, check_view, thread_count)
    log_results_saved("VIEW_ATTRIBUTE")


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
        list[PartitionTask], read_task_csv("VIEW_PARTITIONING_CREATE")
    )

    # Function to create the partitioning for a view
    async def create_partitioning(view: PartitionTask) -> None:
        outcome = await client.views.create_partitioning(
            view=view["entity"],
            space=view["space"],
            attribute=view["attribute"],
            partitions=partitions,
            overwrite_existing=overwrite_existing_partitions,
        )
        append_result_row(
            "VIEW_PARTITIONING_CREATE_RESULT",
            {
                "entity": view["entity"],
                "space": view["space"],
                "attribute": view["attribute"],
                # Existing partitions count as created (skip case)
                "createdPartition": outcome in ("created", "exists"),
            },
        )

    await run_async_tasks(views, create_partitioning, thread_count)
    log_results_saved("VIEW_PARTITIONING_CREATE_RESULT")


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
    views = cast(list[ViewRef], read_task_csv("VIEW_PARTITIONING_DELETE"))

    # Function to remove the partitioning of a view
    async def remove_partitioning(view: ViewRef) -> None:
        logger.debug(
            "Removing partitions for view '%s' in '%s'...",
            view["entity"],
            view["space"],
        )
        removed = await client.views.delete_partitioning(
            view["entity"], view["space"]
        )
        if removed:
            logger.info(
                "Removed partitions for view '%s' in '%s'.",
                view["entity"],
                view["space"],
            )
        else:
            logger.error(
                "Error removing partitions for view '%s' in '%s'.",
                view["entity"],
                view["space"],
            )
        append_result_row(
            "VIEW_PARTITIONING_DELETE_RESULT",
            {
                "entity": view["entity"],
                "space": view["space"],
                "removedPartition": removed,
            },
        )

    await run_async_tasks(views, remove_partitioning, thread_count)
    log_results_saved("VIEW_PARTITIONING_DELETE_RESULT")


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
    views = cast(list[ViewRef], read_task_csv("VIEW_PERSIST"))
    prefill_result_rows(
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

    # Function to persist a view and update its result row
    async def persist_view(view: ViewRef) -> None:
        success, log_details = await client.views.persist_view(
            view["entity"], view["space"]
        )
        runtime = round(log_details.get("runTime", 0) / 1000)
        update_result_row(
            "VIEW_PERSIST_RESULT",
            {
                "entity": view["entity"],
                "space": view["space"],
                "isPersisted": success,
                "runtime": (
                    runtime if timer and success and runtime > 0 else None
                ),
            },
        )

    await run_async_tasks(views, persist_view, thread_count)
    log_results_saved("VIEW_PERSIST_RESULT")


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
    views = cast(list[ViewRef], read_task_csv("VIEW_UNPERSIST"))
    prefill_result_rows(
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

    # Function to unpersist a view and update its result row
    async def unpersist_view(view: ViewRef) -> None:
        success, _ = await client.views.unpersist_view(
            view["entity"], view["space"]
        )
        update_result_row(
            "VIEW_UNPERSIST_RESULT",
            {
                "entity": view["entity"],
                "space": view["space"],
                "isRemoved": success,
            },
        )

    await run_async_tasks(views, unpersist_view, thread_count)
    log_results_saved("VIEW_UNPERSIST_RESULT")


async def lock_partitions_until_year(
    client: DatasphereClient,
    year: int,
    thread_count: int,
) -> None:
    """
    Locks partitions for all views from the task file up to (and
    including) the given year and saves the results. Views without
    partitions are skipped.

    Args:
        client (DatasphereClient): Authenticated client.
        year (int): Year up to which partitions should be locked.
        thread_count (int): Amount of concurrent asynchronous requests.
    """
    views = cast(list[ViewRef], read_task_csv("VIEW_PARTITION_LOCK"))

    # Function to lock the partitions of a view
    async def lock_partitions(view: ViewRef) -> None:
        outcome = await client.views.lock_partitions(
            view=view["entity"],
            space=view["space"],
            until_year=year,
        )
        if outcome == "no_partitions":
            return
        append_result_row(
            "VIEW_PARTITION_LOCK_RESULT",
            {
                "entity": view["entity"],
                "space": view["space"],
                "lockedPartitions": outcome == "locked",
            },
        )

    await run_async_tasks(views, lock_partitions, thread_count)
    log_results_saved("VIEW_PARTITION_LOCK_RESULT")


async def unlock_all_partitions(
    client: DatasphereClient,
    thread_count: int,
) -> None:
    """
    Unlocks all partitions for all views from the task file and saves
    the results. Views without partitions are skipped.

    Args:
        client (DatasphereClient): Authenticated client.
        thread_count (int): Amount of concurrent asynchronous requests.
    """
    views = cast(list[ViewRef], read_task_csv("VIEW_PARTITION_UNLOCK"))

    # Function to unlock the partitions of a view
    async def unlock_partitions(view: ViewRef) -> None:
        outcome = await client.views.unlock_partitions(
            view["entity"], view["space"]
        )
        if outcome == "no_partitions":
            return
        append_result_row(
            "VIEW_PARTITION_UNLOCK_RESULT",
            {
                "entity": view["entity"],
                "space": view["space"],
                "unlockedPartitions": outcome == "unlocked",
            },
        )

    await run_async_tasks(views, unlock_partitions, thread_count)
    log_results_saved("VIEW_PARTITION_UNLOCK_RESULT")
