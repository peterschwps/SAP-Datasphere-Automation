from typing import Any, cast

from datasphere_api.models import (
    StatisticsInformationDict,
    StatisticsWriteOutcome,
)
from datasphere_api.models import StatisticsType as ApiStatisticsType

from datasphere_core.context import CommandContext
from datasphere_core.definitions import CommandDefinition
from datasphere_core.execution import batch_command, command, run_batch
from datasphere_core.models.remote_tables import (
    ConfigureRemoteTableStatisticsBatchRequest,
    ConfigureRemoteTableStatisticsBatchResult,
    ConfigureRemoteTableStatisticsRequest,
    ConfigureRemoteTableStatisticsResult,
    ConfigureRemoteTableStatisticsStatus,
    RefreshRemoteTableStatisticsBatchRequest,
    RefreshRemoteTableStatisticsBatchResult,
    RefreshRemoteTableStatisticsRequest,
    RefreshRemoteTableStatisticsResult,
    RefreshRemoteTableStatisticsStatus,
    StatisticsType,
)

CONFIGURE_REMOTE_TABLE_STATISTICS_COMMAND_NAME = (
    "remote_tables.configure_statistics"
)
CONFIGURE_REMOTE_TABLE_STATISTICS_BATCH_COMMAND_NAME = (
    "remote_tables.configure_statistics_batch"
)
REFRESH_REMOTE_TABLE_STATISTICS_COMMAND_NAME = (
    "remote_tables.refresh_statistics"
)
REFRESH_REMOTE_TABLE_STATISTICS_BATCH_COMMAND_NAME = (
    "remote_tables.refresh_statistics_batch"
)

_DEFAULT_TIMEOUT_SECONDS = 60.0
_MAXIMUM_TIMEOUT_SECONDS = 600.0

# Every table is processed together with its metadata, so a batch fetches the
# metadata of all tables once instead of once per item.
type ConfigureStatisticsItem = tuple[
    ConfigureRemoteTableStatisticsRequest,
    StatisticsInformationDict | None,
]
type RefreshStatisticsItem = tuple[
    RefreshRemoteTableStatisticsRequest,
    StatisticsInformationDict | None,
]


def _write_status(
    outcome: StatisticsWriteOutcome,
    *,
    creating: bool,
) -> ConfigureRemoteTableStatisticsStatus:
    """
    Turns the outcome of a statistics write into its status.

    Args:
        outcome (StatisticsWriteOutcome): What the request achieved.
        creating (bool): Whether statistics were created or replaced.

    Returns:
        ConfigureRemoteTableStatisticsStatus: Status of the written table.
    """
    if outcome == "already_exists":
        return ConfigureRemoteTableStatisticsStatus.ALREADY_EXISTS
    if outcome == "failed":
        return ConfigureRemoteTableStatisticsStatus.FAILED

    # The same accepted answer means different things per endpoint
    return (
        ConfigureRemoteTableStatisticsStatus.CREATED
        if creating
        else ConfigureRemoteTableStatisticsStatus.UPDATED
    )


async def _configure_statistics_item(
    context: CommandContext,
    item: ConfigureStatisticsItem,
) -> ConfigureRemoteTableStatisticsResult:
    """
    Configures the requested statistics for one already discovered remote
    table.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        item (ConfigureStatisticsItem): Configuration request and the metadata
                                        of its remote table.

    Returns:
        ConfigureRemoteTableStatisticsResult: Result of the configuration.
    """
    request, metadata = item
    status: ConfigureRemoteTableStatisticsStatus

    # Check metadata of the remote table
    if metadata is None:
        status = ConfigureRemoteTableStatisticsStatus.TABLE_NOT_FOUND

    # If statistics not supported
    elif not metadata["statisticsSupported"]:
        status = ConfigureRemoteTableStatisticsStatus.UNSUPPORTED

    # If only record count supported but different statistics type requested
    elif (
        metadata["statisticsLimitedToRecordCount"]
        and request.statistics_type is not StatisticsType.RECORD_COUNT
    ):
        status = ConfigureRemoteTableStatisticsStatus.UNSUPPORTED_TYPE

    # Skip if statistics present and same type (should use refresh instead)
    elif metadata["statisticsType"] == request.statistics_type.value:
        status = ConfigureRemoteTableStatisticsStatus.ALREADY_CONFIGURED

    # Create new statistics if supported but not present yet, otherwise
    # replace the type that is already there
    else:
        creating = metadata["statisticsType"] is None
        write = (
            context.client.remote_tables.create_statistics
            if creating
            else context.client.remote_tables.update_statistics
        )
        outcome = await write(
            table=request.table,
            statistics_type=cast(
                ApiStatisticsType, request.statistics_type.value
            ),
            space=request.space,
        )
        status = _write_status(outcome, creating=creating)

    return ConfigureRemoteTableStatisticsResult(
        table=request.table,
        space=request.space,
        statistics_type=request.statistics_type,
        status=status,
    )


async def _refresh_statistics_item(
    context: CommandContext,
    item: RefreshStatisticsItem,
) -> RefreshRemoteTableStatisticsResult:
    """
    Refreshes the statistics of one already discovered remote table.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        item (RefreshStatisticsItem): Refresh request and the metadata of its
                                      remote table.

    Returns:
        RefreshRemoteTableStatisticsResult: Result of the refresh.
    """
    request, metadata = item
    status: RefreshRemoteTableStatisticsStatus

    # Check metadata of the remote table
    if metadata is None:
        status = RefreshRemoteTableStatisticsStatus.TABLE_NOT_FOUND

    # If statistics not supported
    elif not metadata["statisticsSupported"]:
        status = RefreshRemoteTableStatisticsStatus.UNSUPPORTED

    # If no statistics present to be refreshed
    elif metadata["statisticsType"] is None:
        status = RefreshRemoteTableStatisticsStatus.NO_STATISTICS

    # Start refresh
    elif await context.client.remote_tables.refresh_statistics(
        table=request.table,
        space=request.space,
    ):
        status = RefreshRemoteTableStatisticsStatus.REFRESHED

    else:
        status = RefreshRemoteTableStatisticsStatus.FAILED

    return RefreshRemoteTableStatisticsResult(
        table=request.table,
        space=request.space,
        status=status,
    )


@command(CONFIGURE_REMOTE_TABLE_STATISTICS_COMMAND_NAME)
async def configure_remote_table_statistics(
    context: CommandContext,
    request: ConfigureRemoteTableStatisticsRequest,
) -> ConfigureRemoteTableStatisticsResult:
    """
    Discovers one remote table and configures the requested statistics for it.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (ConfigureRemoteTableStatisticsRequest): Input for the
                                                         configuration.

    Returns:
        ConfigureRemoteTableStatisticsResult: Result of the configuration.
    """
    all_tables = await context.client.remote_tables.get_all_tables(
        space=request.space
    )
    return await _configure_statistics_item(
        context=context,
        item=(request, all_tables.get(request.table)),
    )


@command(REFRESH_REMOTE_TABLE_STATISTICS_COMMAND_NAME)
async def refresh_remote_table_statistics(
    context: CommandContext,
    request: RefreshRemoteTableStatisticsRequest,
) -> RefreshRemoteTableStatisticsResult:
    """
    Discovers one remote table and refreshes its configured statistics.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (RefreshRemoteTableStatisticsRequest): Input for the refresh.

    Returns:
        RefreshRemoteTableStatisticsResult: Result of the refresh.
    """
    all_tables = await context.client.remote_tables.get_all_tables(
        space=request.space
    )
    return await _refresh_statistics_item(
        context=context,
        item=(request, all_tables.get(request.table)),
    )


@batch_command(CONFIGURE_REMOTE_TABLE_STATISTICS_BATCH_COMMAND_NAME)
async def configure_remote_table_statistics_batch(
    context: CommandContext,
    request: ConfigureRemoteTableStatisticsBatchRequest,
) -> ConfigureRemoteTableStatisticsBatchResult:
    """
    Configures statistics for selected remote tables with concurrency.
    Discovers every remote table of the space if the request carries no
    explicit tables.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (ConfigureRemoteTableStatisticsBatchRequest): Input for the
                                                              configurations.

    Returns:
        ConfigureRemoteTableStatisticsBatchResult: Ordered results of the
                                                   configurations.
    """
    # Fetch the metadata of all tables once and select the requested ones
    all_tables = await context.client.remote_tables.get_all_tables(
        space=request.space
    )
    tables = (
        request.tables
        if request.tables is not None
        else tuple(sorted(all_tables))
    )

    # Discovery cannot miss a table because the names come from
    # all_tables, but an explicit selection can name an unknown one
    items = tuple(
        (
            ConfigureRemoteTableStatisticsRequest(
                table=table,
                space=request.space,
                statistics_type=request.statistics_type,
            ),
            all_tables.get(table),
        )
        for table in tables
    )

    results, summary = await run_batch(
        context=context,
        command=CONFIGURE_REMOTE_TABLE_STATISTICS_BATCH_COMMAND_NAME,
        items=items,
        operation=_configure_statistics_item,
        max_concurrency=request.max_concurrency,
    )
    return ConfigureRemoteTableStatisticsBatchResult(
        results=results,
        summary=summary,
    )


@batch_command(REFRESH_REMOTE_TABLE_STATISTICS_BATCH_COMMAND_NAME)
async def refresh_remote_table_statistics_batch(
    context: CommandContext,
    request: RefreshRemoteTableStatisticsBatchRequest,
) -> RefreshRemoteTableStatisticsBatchResult:
    """
    Refreshes statistics for selected remote tables with concurrency. Discovers
    every remote table of the space if the request carries no explicit tables.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (RefreshRemoteTableStatisticsBatchRequest): Input for the
                                                            refreshes.

    Returns:
        RefreshRemoteTableStatisticsBatchResult: Ordered results of the
                                                 refreshes.
    """
    # Fetch the metadata of all tables once and select the requested ones
    all_tables = await context.client.remote_tables.get_all_tables(
        request.space
    )
    tables = (
        request.tables
        if request.tables is not None
        else tuple(sorted(all_tables))
    )

    # Discovery cannot miss a table because the names come from
    # all_tables, but an explicit selection can name an unknown one
    items = tuple(
        (
            RefreshRemoteTableStatisticsRequest(
                table=table,
                space=request.space,
            ),
            all_tables.get(table),
        )
        for table in tables
    )

    results, summary = await run_batch(
        context=context,
        command=REFRESH_REMOTE_TABLE_STATISTICS_BATCH_COMMAND_NAME,
        items=items,
        operation=_refresh_statistics_item,
        max_concurrency=request.max_concurrency,
    )
    return RefreshRemoteTableStatisticsBatchResult(
        results=results,
        summary=summary,
    )


# Define all commands
CONFIGURE_REMOTE_TABLE_STATISTICS_COMMAND = CommandDefinition(
    name=CONFIGURE_REMOTE_TABLE_STATISTICS_COMMAND_NAME,
    request_type=ConfigureRemoteTableStatisticsRequest,
    result_type=ConfigureRemoteTableStatisticsResult,
    handler=configure_remote_table_statistics,
    description="Configure statistics for one remote table.",
    default_timeout_seconds=_DEFAULT_TIMEOUT_SECONDS,
    maximum_timeout_seconds=_MAXIMUM_TIMEOUT_SECONDS,
    read_only=False,
    destructive=False,
    idempotent=True,
    expose_to_mcp=False,
)

CONFIGURE_REMOTE_TABLE_STATISTICS_BATCH_COMMAND = CommandDefinition(
    name=CONFIGURE_REMOTE_TABLE_STATISTICS_BATCH_COMMAND_NAME,
    request_type=ConfigureRemoteTableStatisticsBatchRequest,
    result_type=ConfigureRemoteTableStatisticsBatchResult,
    handler=configure_remote_table_statistics_batch,
    description=(
        "Configure statistics for multiple remote tables with bounded "
        "concurrency."
    ),
    default_timeout_seconds=_DEFAULT_TIMEOUT_SECONDS,
    maximum_timeout_seconds=_MAXIMUM_TIMEOUT_SECONDS,
    read_only=False,
    destructive=False,
    idempotent=True,
    expose_to_mcp=False,
)

REFRESH_REMOTE_TABLE_STATISTICS_COMMAND = CommandDefinition(
    name=REFRESH_REMOTE_TABLE_STATISTICS_COMMAND_NAME,
    request_type=RefreshRemoteTableStatisticsRequest,
    result_type=RefreshRemoteTableStatisticsResult,
    handler=refresh_remote_table_statistics,
    description="Refresh statistics for one remote table.",
    default_timeout_seconds=_DEFAULT_TIMEOUT_SECONDS,
    maximum_timeout_seconds=_MAXIMUM_TIMEOUT_SECONDS,
    read_only=False,
    destructive=False,
    idempotent=False,
    expose_to_mcp=False,
)

REFRESH_REMOTE_TABLE_STATISTICS_BATCH_COMMAND = CommandDefinition(
    name=REFRESH_REMOTE_TABLE_STATISTICS_BATCH_COMMAND_NAME,
    request_type=RefreshRemoteTableStatisticsBatchRequest,
    result_type=RefreshRemoteTableStatisticsBatchResult,
    handler=refresh_remote_table_statistics_batch,
    description=(
        "Refresh statistics for multiple remote tables with bounded "
        "concurrency."
    ),
    default_timeout_seconds=_DEFAULT_TIMEOUT_SECONDS,
    maximum_timeout_seconds=_MAXIMUM_TIMEOUT_SECONDS,
    read_only=False,
    destructive=False,
    idempotent=False,
    expose_to_mcp=False,
)

# Gather all commands (to import to registry)
REMOTE_TABLES_COMMAND_DEFINITIONS: tuple[CommandDefinition[Any, Any], ...] = (
    CONFIGURE_REMOTE_TABLE_STATISTICS_COMMAND,
    CONFIGURE_REMOTE_TABLE_STATISTICS_BATCH_COMMAND,
    REFRESH_REMOTE_TABLE_STATISTICS_COMMAND,
    REFRESH_REMOTE_TABLE_STATISTICS_BATCH_COMMAND,
)
