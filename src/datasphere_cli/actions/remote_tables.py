from datasphere_core import CommandContext
from datasphere_core.models.remote_tables import (
    ConfigureRemoteTableStatisticsBatchRequest,
    ConfigureRemoteTableStatisticsBatchResult,
    RefreshRemoteTableStatisticsBatchRequest,
    RefreshRemoteTableStatisticsBatchResult,
)
from datasphere_core.models.remote_tables import (
    StatisticsType as CoreStatisticsType,
)

from datasphere_cli.actions.dispatch import dispatch_command
from datasphere_cli.files.records import StatisticsType
from datasphere_cli.logging import logger

_CONFIGURE_COMMAND = "remote_tables.configure_statistics_batch"
_REFRESH_COMMAND = "remote_tables.refresh_statistics_batch"


def _log_results(
    command: str,
    result: ConfigureRemoteTableStatisticsBatchResult
    | RefreshRemoteTableStatisticsBatchResult,
) -> None:
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
    """Configures remote-table statistics through the Core batch command.

    Args:
        context (CommandContext): Core context with the authenticated client.
        space (str): Datasphere space containing the remote tables.
        statistics_type (StatisticsType): Statistics type to configure.
        max_concurrency (int, optional): Maximum concurrent SAP operations.

    Returns:
        ConfigureRemoteTableStatisticsBatchResult: Configuration results.
    """
    request = ConfigureRemoteTableStatisticsBatchRequest(
        tables=None,
        space=space,
        statistics_type=CoreStatisticsType(statistics_type),
        max_concurrency=max_concurrency,
    )
    result = await dispatch_command(
        _CONFIGURE_COMMAND,
        context,
        request,
        ConfigureRemoteTableStatisticsBatchRequest,
        ConfigureRemoteTableStatisticsBatchResult,
    )
    _log_results(_CONFIGURE_COMMAND, result)
    return result


async def refresh_remote_table_statistics(
    context: CommandContext,
    space: str,
    max_concurrency: int = 4,
) -> RefreshRemoteTableStatisticsBatchResult:
    """Refresh remote-table statistics through the Core batch command.

    Args:
        context (CommandContext): Core context with the authenticated client.
        space (str): Datasphere space containing the remote tables.
        max_concurrency (int, optional): Maximum concurrent SAP operations.

    Returns:
        RefreshRemoteTableStatisticsBatchResult: Statistics operation results.
    """
    request = RefreshRemoteTableStatisticsBatchRequest(
        tables=None,
        space=space,
        max_concurrency=max_concurrency,
    )
    result = await dispatch_command(
        _REFRESH_COMMAND,
        context,
        request,
        RefreshRemoteTableStatisticsBatchRequest,
        RefreshRemoteTableStatisticsBatchResult,
    )
    _log_results(_REFRESH_COMMAND, result)
    return result
