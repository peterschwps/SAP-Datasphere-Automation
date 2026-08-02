from datasphere_core import CommandContext
from datasphere_core.commands.remote_tables import (
    configure_remote_table_statistics_batch,
    refresh_remote_table_statistics_batch,
)
from datasphere_core.models.remote_tables import (
    ConfigureRemoteTableStatisticsBatchRequest,
    ConfigureRemoteTableStatisticsBatchResult,
    RefreshRemoteTableStatisticsBatchRequest,
    RefreshRemoteTableStatisticsBatchResult,
    StatisticsType,
)

from datasphere_cli.logging import logger

_CONFIGURE_COMMAND = "remote_tables.configure_statistics_batch"
_REFRESH_COMMAND = "remote_tables.refresh_statistics_batch"


def _log_results(
    command: str,
    result: ConfigureRemoteTableStatisticsBatchResult
    | RefreshRemoteTableStatisticsBatchResult,
) -> None:
    """
    Logs the status of every remote table and the batch summary.

    Args:
        command (str): Command the results belong to.
        result (ConfigureRemoteTableStatisticsBatchResult |
                RefreshRemoteTableStatisticsBatchResult):
            Completed batch result to log.
    """
    # Log the status of every table
    # These two actions are the only ones without a result file
    for item in result.results:
        logger.info(
            "%s for table '%s' in '%s': %s.",
            command,
            item.table,
            item.space,
            item.status,
        )
    logger.info(
        "%s: %s succeeded, %s failed, %s skipped.",
        command,
        result.summary.succeeded,
        result.summary.failed,
        result.summary.skipped,
    )


async def configure_remote_table_statistics(
    context: CommandContext,
    space: str,
    statistics_type: StatisticsType,
    max_concurrency: int = 4,
) -> ConfigureRemoteTableStatisticsBatchResult:
    """
    Configures statistics for all remote tables in a given space.

    Args:
        context (CommandContext): Context with the authenticated client.
        space (str): Datasphere space containing the remote tables.
        statistics_type (StatisticsType): Statistics type to configure.
        max_concurrency (int, optional): Maximum amount of concurrent
                                         operations. Defaults to 4.

    Returns:
        ConfigureRemoteTableStatisticsBatchResult: Configuration results.
    """
    # Convert the statistics type into a real enum member
    # Callers outside the TUI pass a string, which is compared by identity
    request = ConfigureRemoteTableStatisticsBatchRequest(
        tables=None,
        space=space,
        statistics_type=StatisticsType(statistics_type),
        max_concurrency=max_concurrency,
    )
    result = await configure_remote_table_statistics_batch(context, request)
    _log_results(_CONFIGURE_COMMAND, result)
    return result


async def refresh_remote_table_statistics(
    context: CommandContext,
    space: str,
    max_concurrency: int = 4,
) -> RefreshRemoteTableStatisticsBatchResult:
    """
    Refreshes all remote table statistics.

    Args:
        context (CommandContext): Context with the authenticated client.
        space (str): Datasphere space containing the remote tables.
        max_concurrency (int, optional): Maximum amount of concurrent
                                         operations. Defaults to 4.

    Returns:
        RefreshRemoteTableStatisticsBatchResult: Statistics operation results.
    """
    request = RefreshRemoteTableStatisticsBatchRequest(
        tables=None,
        space=space,
        max_concurrency=max_concurrency,
    )
    result = await refresh_remote_table_statistics_batch(context, request)
    _log_results(_REFRESH_COMMAND, result)
    return result
