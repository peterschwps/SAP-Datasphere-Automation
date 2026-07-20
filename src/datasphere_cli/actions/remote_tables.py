from datasphere_api import DatasphereClient
from datasphere_api.models import StatisticsType

from datasphere_cli.concurrency import run_async_tasks
from datasphere_cli.logging import logger


async def create_statistics(
    client: DatasphereClient,
    statistics_type: StatisticsType,
    thread_count: int,
) -> None:
    """
    Creates statistics for all remote tables. Tables that don't support
    statistics or already have statistics of the given type are
    skipped.

    Args:
        client (DatasphereClient): Authenticated client.
        statistics_type (StatisticsType): Type of the statistic.
        thread_count (int): Amount of concurrent asynchronous requests.
    """
    all_tables = await client.remote_tables.get_all_tables()

    # Function to create or update the statistics of a table
    async def create_statistics_for_table(table: str) -> None:
        # Only create statistics for tables that support them
        # and don't have statistics of the given type yet
        if not (
            all_tables[table]["statisticsSupported"]
            and all_tables[table]["statisticsType"] != statistics_type
        ):
            return

        # Create new statistics or update the existing type
        if all_tables[table]["statisticsType"] is None:
            outcome = await client.remote_tables.create_statistics(
                table, statistics_type
            )
        else:
            outcome = await client.remote_tables.update_statistics(
                table, statistics_type
            )

        # Log the outcome (errors are logged by the client)
        if outcome == "already_exists":
            logger.debug(
                "Statistics for table '%s' already exists. Skipping...",
                table,
            )
        elif outcome in ("created", "updated"):
            logger.info("Created statistics for table '%s'.", table)

    await run_async_tasks(
        all_tables, create_statistics_for_table, thread_count
    )


async def refresh_statistics(
    client: DatasphereClient,
    thread_count: int,
) -> None:
    """
    Refreshes statistics for all remote tables. Tables that don't
    support statistics or don't have statistics are skipped.

    Args:
        client (DatasphereClient): Authenticated client.
        thread_count (int): Amount of concurrent asynchronous requests.
    """
    all_tables = await client.remote_tables.get_all_tables()

    # Function to refresh the statistics of a table
    async def refresh_statistics_for_table(table: str) -> None:
        # Only refresh statistics for tables that support them
        # and have statistics
        if not (
            all_tables[table]["statisticsSupported"]
            and all_tables[table]["statisticsType"] is not None
        ):
            return

        # Refresh the statistics (errors are logged by the client)
        if await client.remote_tables.refresh_statistics(table):
            logger.info("Refreshed statistics for table '%s'.", table)

    await run_async_tasks(
        all_tables, refresh_statistics_for_table, thread_count
    )
