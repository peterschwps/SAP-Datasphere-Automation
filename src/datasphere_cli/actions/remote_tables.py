import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from pathlib import Path

from datasphere_core import CommandContext
from datasphere_core.commands.remote_tables import (
    configure_remote_table_statistics_batch,
    refresh_remote_table_statistics_batch,
)
from datasphere_core.models.common import BatchItemResult, CommandStatus
from datasphere_core.models.remote_tables import (
    ConfigureRemoteTableStatisticsBatchRequest,
    ConfigureRemoteTableStatisticsBatchResult,
    ConfigureRemoteTableStatisticsResult,
    ConfigureRemoteTableStatisticsStatus,
    RefreshRemoteTableStatisticsBatchRequest,
    RefreshRemoteTableStatisticsBatchResult,
    RefreshRemoteTableStatisticsResult,
    RefreshRemoteTableStatisticsStatus,
    StatisticsType,
)

from datasphere_cli.files.records import (
    RemoteTableRefreshResultRecord,
    RemoteTableStatisticsResultRecord,
)
from datasphere_cli.files.storage import initialize_result, write_result_csv
from datasphere_cli.logging import LEVEL_BY_OUTCOME, SUCCESS, logger

_CONFIGURE_COMMAND = "remote_tables.configure_statistics_batch"
_REFRESH_COMMAND = "remote_tables.refresh_statistics_batch"

type RemoteTableBatchResult = (
    ConfigureRemoteTableStatisticsBatchResult
    | RefreshRemoteTableStatisticsBatchResult
)

# Log level and message per status. Both enums need their own mapping: their
# members compare equal by value, so one shared table would drop entries.
_CONFIGURE_MESSAGES: Mapping[CommandStatus, tuple[int, str]] = {
    ConfigureRemoteTableStatisticsStatus.CREATED: (
        SUCCESS,
        "Successfully created statistics for table '%s'.",
    ),
    ConfigureRemoteTableStatisticsStatus.UPDATED: (
        SUCCESS,
        "Successfully updated statistics for table '%s'.",
    ),
    ConfigureRemoteTableStatisticsStatus.ALREADY_CONFIGURED: (
        logging.INFO,
        "Table '%s' already has statistics of this type. Skipping...",
    ),
    ConfigureRemoteTableStatisticsStatus.ALREADY_EXISTS: (
        logging.INFO,
        "Statistics for table '%s' already exist. Skipping...",
    ),
    ConfigureRemoteTableStatisticsStatus.UNSUPPORTED: (
        logging.INFO,
        "Table '%s' does not support statistics. Skipping...",
    ),
    ConfigureRemoteTableStatisticsStatus.UNSUPPORTED_TYPE: (
        logging.INFO,
        "Table '%s' only supports record counts. Skipping...",
    ),
    ConfigureRemoteTableStatisticsStatus.TABLE_NOT_FOUND: (
        logging.ERROR,
        "Table '%s' not found. Skipping...",
    ),
    ConfigureRemoteTableStatisticsStatus.FAILED: (
        logging.ERROR,
        "Failed to configure statistics for table '%s'.",
    ),
}

_REFRESH_MESSAGES: Mapping[CommandStatus, tuple[int, str]] = {
    RefreshRemoteTableStatisticsStatus.REFRESHED: (
        SUCCESS,
        "Successfully refreshed statistics for table '%s'.",
    ),
    RefreshRemoteTableStatisticsStatus.NO_STATISTICS: (
        logging.INFO,
        "Table '%s' has no statistics to refresh. Skipping...",
    ),
    RefreshRemoteTableStatisticsStatus.UNSUPPORTED: (
        logging.INFO,
        "Table '%s' does not support statistics. Skipping...",
    ),
    RefreshRemoteTableStatisticsStatus.TABLE_NOT_FOUND: (
        logging.ERROR,
        "Table '%s' not found. Skipping...",
    ),
    RefreshRemoteTableStatisticsStatus.FAILED: (
        logging.ERROR,
        "Failed to refresh statistics for table '%s'.",
    ),
}


def _table_reporter(
    messages: Mapping[CommandStatus, tuple[int, str]],
) -> Callable[[BatchItemResult], Awaitable[None]]:
    """
    Builds a callback that logs every remote table as soon as it is done.

    Args:
        messages (Mapping[CommandStatus, tuple[int, str]]): Log level and
                                                            message per
                                                            status.

    Returns:
        Callable[[BatchItemResult], Awaitable[None]]: Callback for the batch.
    """

    async def report(update: BatchItemResult) -> None:
        """
        Logs the outcome of one remote table.

        Args:
            update (BatchItemResult): Result of one completed table.

        Raises:
            TypeError: If the item carries an unexpected result type.
        """
        if not isinstance(
            update.result,
            ConfigureRemoteTableStatisticsResult
            | RefreshRemoteTableStatisticsResult,
        ):
            raise TypeError("Remote table item has an unexpected result.")

        # A status added to the Core later would otherwise abort the batch
        item = update.result
        level, message = messages.get(
            item.status,
            (
                LEVEL_BY_OUTCOME[item.status.outcome],
                "Table '%s' finished with an unexpected status. See the "
                "result file.",
            ),
        )
        logger.log(level, message, item.table)

    return report


def _log_summary(result: RemoteTableBatchResult, path: Path) -> None:
    """
    Logs the outcome counts of a batch and where its result was written.

    Args:
        result (RemoteTableBatchResult): Completed batch result to summarize.
        path (Path): Path the result file was written to.
    """
    logger.info(
        "Results: %s succeeded, %s failed, %s skipped.",
        result.summary.succeeded,
        result.summary.failed,
        result.summary.skipped,
    )
    logger.log(SUCCESS, "Results saved to '%s'.", path)


async def configure_remote_table_statistics(
    context: CommandContext,
    space: str,
    statistics_type: StatisticsType,
    max_concurrency: int = 5,
    workspace_root: str | Path | None = None,
) -> ConfigureRemoteTableStatisticsBatchResult:
    """
    Configures statistics for all remote tables in a given space.

    Args:
        context (CommandContext): Context with the authenticated client.
        space (str): Datasphere space containing the remote tables.
        statistics_type (StatisticsType): Statistics type to configure.
        max_concurrency (int, optional): Maximum amount of concurrent
                                         operations. Defaults to 5.
        workspace_root (str | Path | None, optional): Root for the result
                                                      file. Uses the default
                                                      workspace when None.
                                                      Defaults to None.

    Returns:
        ConfigureRemoteTableStatisticsBatchResult: Configuration results.
    """
    # Write empty result file
    initialize_result(_CONFIGURE_COMMAND, workspace_root)

    # Convert the statistics type into a real enum member
    # Callers outside the TUI pass a string, which is compared by identity
    request = ConfigureRemoteTableStatisticsBatchRequest(
        tables=None,
        space=space,
        statistics_type=StatisticsType(statistics_type),
        max_concurrency=max_concurrency,
    )

    # Report every table as soon as it is done
    result = await configure_remote_table_statistics_batch(
        replace(
            context,
            batch_item_result_callback=_table_reporter(_CONFIGURE_MESSAGES),
        ),
        request,
    )

    # Write result CSV
    rows: list[RemoteTableStatisticsResultRecord] = [
        {
            "table": item.table,
            "space": item.space,
            "statistics_type": item.statistics_type,
            "status": item.status,
        }
        for item in result.results
    ]
    path = write_result_csv(_CONFIGURE_COMMAND, rows, workspace_root)

    # Log outcome counts
    _log_summary(result, path)
    return result


async def refresh_remote_table_statistics(
    context: CommandContext,
    space: str,
    max_concurrency: int = 5,
    workspace_root: str | Path | None = None,
) -> RefreshRemoteTableStatisticsBatchResult:
    """
    Refreshes all remote table statistics.

    Args:
        context (CommandContext): Context with the authenticated client.
        space (str): Datasphere space containing the remote tables.
        max_concurrency (int, optional): Maximum amount of concurrent
                                         operations. Defaults to 5.
        workspace_root (str | Path | None, optional): Root for the result
                                                      file. Uses the default
                                                      workspace when None.
                                                      Defaults to None.

    Returns:
        RefreshRemoteTableStatisticsBatchResult: Statistics operation results.
    """
    # Write empty result file
    initialize_result(_REFRESH_COMMAND, workspace_root)
    request = RefreshRemoteTableStatisticsBatchRequest(
        tables=None,
        space=space,
        max_concurrency=max_concurrency,
    )

    # Report every table as soon as it is done
    result = await refresh_remote_table_statistics_batch(
        replace(
            context,
            batch_item_result_callback=_table_reporter(_REFRESH_MESSAGES),
        ),
        request,
    )

    # Write result CSV
    rows: list[RemoteTableRefreshResultRecord] = [
        {
            "table": item.table,
            "space": item.space,
            "status": item.status,
        }
        for item in result.results
    ]
    path = write_result_csv(_REFRESH_COMMAND, rows, workspace_root)

    # Log outcome counts
    _log_summary(result, path)
    return result
