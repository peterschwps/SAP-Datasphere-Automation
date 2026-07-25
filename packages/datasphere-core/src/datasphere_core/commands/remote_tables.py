from typing import Any, cast

from datasphere_api.models import (
    StatisticsInformationDict,
)
from datasphere_api.models import (
    StatisticsType as ApiStatisticsType,
)

from datasphere_core.context import CommandContext
from datasphere_core.definitions import CommandDefinition
from datasphere_core.execution import (
    BatchExecution,
    batch_result_phase,
    execute_batch,
    execute_command,
)
from datasphere_core.models.common import (
    BatchItemFinalStatus,
    CommandProgressPhase,
)
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

type ConfigureStatisticsItem = tuple[
    ConfigureRemoteTableStatisticsRequest,
    StatisticsInformationDict | None,
]
type RefreshStatisticsItem = tuple[
    RefreshRemoteTableStatisticsRequest,
    StatisticsInformationDict | None,
]


def _map_configure_result_to_command_progress_phase(
    result: ConfigureRemoteTableStatisticsResult,
) -> CommandProgressPhase:
    """
    Maps a configuration result to its lifecycle progress phase.

    Args:
        result (ConfigureRemoteTableStatisticsResult): Result to classify.

    Returns:
        CommandProgressPhase: Corresponding command progress phase.
    """
    return (
        CommandProgressPhase.FAILED
        if result.status is ConfigureRemoteTableStatisticsStatus.FAILED
        else CommandProgressPhase.COMPLETED
    )


def _map_refresh_result_to_command_progress_phase(
    result: RefreshRemoteTableStatisticsResult,
) -> CommandProgressPhase:
    """
    Maps a refresh result to its lifecycle progress phase.

    Args:
        result (RefreshRemoteTableStatisticsResult): Result to classify.

    Returns:
        CommandProgressPhase: Corresponding command progress phase.
    """
    if result.status in (
        RefreshRemoteTableStatisticsStatus.TABLE_NOT_FOUND,
        RefreshRemoteTableStatisticsStatus.FAILED,
    ):
        return CommandProgressPhase.FAILED
    return CommandProgressPhase.COMPLETED


def _map_configure_result_to_batch_item_final_status(
    result: ConfigureRemoteTableStatisticsResult,
) -> BatchItemFinalStatus:
    """
    Maps a configuration result to its batch item status.

    Args:
        result (ConfigureRemoteTableStatisticsResult): Result to classify.

    Returns:
        BatchItemFinalStatus: Corresponding batch item status.
    """
    if result.status in (
        ConfigureRemoteTableStatisticsStatus.UNSUPPORTED,
        ConfigureRemoteTableStatisticsStatus.UNSUPPORTED_TYPE,
    ):
        return BatchItemFinalStatus.SKIPPED
    if result.status is ConfigureRemoteTableStatisticsStatus.FAILED:
        return BatchItemFinalStatus.FAILED
    return BatchItemFinalStatus.SUCCEEDED


def _map_refresh_result_to_batch_item_final_status(
    result: RefreshRemoteTableStatisticsResult,
) -> BatchItemFinalStatus:
    """
    Maps a refresh result to its batch item status.

    Args:
        result (RefreshRemoteTableStatisticsResult): Result to classify.

    Returns:
        BatchItemFinalStatus: Corresponding batch item status.
    """
    if result.status in (
        RefreshRemoteTableStatisticsStatus.NO_STATISTICS,
        RefreshRemoteTableStatisticsStatus.UNSUPPORTED,
    ):
        return BatchItemFinalStatus.SKIPPED
    if result.status in (
        RefreshRemoteTableStatisticsStatus.TABLE_NOT_FOUND,
        RefreshRemoteTableStatisticsStatus.FAILED,
    ):
        return BatchItemFinalStatus.FAILED
    return BatchItemFinalStatus.SUCCEEDED


async def _configure_remote_table_statistics_item(
    context: CommandContext,
    item: ConfigureStatisticsItem,
) -> ConfigureRemoteTableStatisticsResult:
    """
    Configures the requested statistics for one remote table.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        item (ConfigureStatisticsItem): Input for the configuration.

    Returns:
        ConfigureRemoteTableStatisticsResult: Result of the configuration.
    """
    request, metadata = item
    status: ConfigureRemoteTableStatisticsStatus

    # Check metadata of the remote table
    if metadata is None:
        status = ConfigureRemoteTableStatisticsStatus.FAILED

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

    # Create new statistics if supported but not present yet
    elif metadata["statisticsType"] is None:
        status = ConfigureRemoteTableStatisticsStatus(
            await context.client.remote_tables.create_statistics(
                request.table,
                cast(ApiStatisticsType, request.statistics_type.value),
                request.space,
            )
        )

    # Update statistics if supported, present but of different type
    else:
        status = ConfigureRemoteTableStatisticsStatus(
            await context.client.remote_tables.update_statistics(
                request.table,
                cast(ApiStatisticsType, request.statistics_type.value),
                request.space,
            )
        )

    return ConfigureRemoteTableStatisticsResult(
        table=request.table,
        space=request.space,
        statistics_type=request.statistics_type,
        status=status,
    )


async def _refresh_remote_table_statistics_item(
    context: CommandContext,
    item: RefreshStatisticsItem,
) -> RefreshRemoteTableStatisticsResult:
    """
    Refreshes the statistics for one remote table.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        item (RefreshStatisticsItem): Input for the refresh.

    Returns:
        RefreshRemoteTableStatisticsResult: Result of the refresh.
    """
    request, metadata = item

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
    else:
        started = await context.client.remote_tables.refresh_statistics(
            request.table,
            request.space,
        )
        if started:
            status = RefreshRemoteTableStatisticsStatus.REFRESHED
        else:
            status = RefreshRemoteTableStatisticsStatus.FAILED

    return RefreshRemoteTableStatisticsResult(
        table=request.table,
        space=request.space,
        status=status,
    )


async def _configure_remote_table_statistics(
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
    return await _configure_remote_table_statistics_item(
        context=context,
        item=(request, all_tables.get(request.table)),
    )


async def configure_remote_table_statistics(
    context: CommandContext,
    request: ConfigureRemoteTableStatisticsRequest,
) -> ConfigureRemoteTableStatisticsResult:
    """
    Configures the requested statistics for one remote table.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (ConfigureRemoteTableStatisticsRequest): Input for the
                                                         configuration.

    Returns:
        ConfigureRemoteTableStatisticsResult: Result of the configuration.
    """
    return await execute_command(
        context=context,
        command=CONFIGURE_REMOTE_TABLE_STATISTICS_COMMAND_NAME,
        request=request,
        operation=_configure_remote_table_statistics,
        result_phase=_map_configure_result_to_command_progress_phase,
    )


async def _refresh_remote_table_statistics(
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
    return await _refresh_remote_table_statistics_item(
        context=context,
        item=(request, all_tables.get(request.table)),
    )


async def refresh_remote_table_statistics(
    context: CommandContext,
    request: RefreshRemoteTableStatisticsRequest,
) -> RefreshRemoteTableStatisticsResult:
    """
    Refreshes the statistics for one remote table.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (RefreshRemoteTableStatisticsRequest): Input for the refresh.

    Returns:
        RefreshRemoteTableStatisticsResult: Result of the refresh.
    """
    return await execute_command(
        context=context,
        command=REFRESH_REMOTE_TABLE_STATISTICS_COMMAND_NAME,
        request=request,
        operation=_refresh_remote_table_statistics,
        result_phase=_map_refresh_result_to_command_progress_phase,
    )


async def _configure_remote_table_statistics_batch(
    execution: BatchExecution,
    request: ConfigureRemoteTableStatisticsBatchRequest,
) -> ConfigureRemoteTableStatisticsBatchResult:
    """
    Discovers selected remote tables and configures the requested statistics
    for them with concurrency.

    Args:
        execution (BatchExecution): Runtime state and shared operations for the
                                    batch execution.
        request (ConfigureRemoteTableStatisticsBatchRequest): Input for the
                                                              configurations.

    Returns:
        ConfigureRemoteTableStatisticsBatchResult: Ordered results of the
                                                   configurations.
    """
    # Fetch all tables and filter them
    all_tables = await execution.context.client.remote_tables.get_all_tables(
        space=request.space
    )
    tables = (
        request.tables
        if request.tables is not None
        else tuple(sorted(all_tables))
    )

    # Create all configurations requests
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

    # Call executor to handle execution
    results = await execution.execute_items(
        items=items,
        operation=_configure_remote_table_statistics_item,
        max_concurrency=request.max_concurrency,
        classify=_map_configure_result_to_batch_item_final_status,
    )
    return ConfigureRemoteTableStatisticsBatchResult(
        results=results,
        summary=execution.to_summary(),
    )


async def configure_remote_table_statistics_batch(
    context: CommandContext,
    request: ConfigureRemoteTableStatisticsBatchRequest,
) -> ConfigureRemoteTableStatisticsBatchResult:
    """
    Configures statistics for selected remote tables with concurrency.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (ConfigureRemoteTableStatisticsBatchRequest): Input for the
                                                              configurations.

    Returns:
        ConfigureRemoteTableStatisticsBatchResult: Ordered results of the
                                                   configurations.
    """
    total_items = len(request.tables) if request.tables is not None else None
    return await execute_batch(
        context=context,
        command=CONFIGURE_REMOTE_TABLE_STATISTICS_BATCH_COMMAND_NAME,
        request=request,
        operation=_configure_remote_table_statistics_batch,
        total_items=total_items,
        result_phase=lambda result: batch_result_phase(result.summary),
    )


async def _refresh_remote_table_statistics_batch(
    execution: BatchExecution,
    request: RefreshRemoteTableStatisticsBatchRequest,
) -> RefreshRemoteTableStatisticsBatchResult:
    """
    Discovers selected remote tables and refreshes their statistics with
    concurrency.

    Args:
        execution (BatchExecution): Runtime state and shared operations for the
                                    batch execution.
        request (RefreshRemoteTableStatisticsBatchRequest): Input for the
                                                            refreshes.

    Returns:
        RefreshRemoteTableStatisticsBatchResult: Ordered results of the
                                                 refreshes.
    """
    # Fetch all tables and filter them
    all_tables = await execution.context.client.remote_tables.get_all_tables(
        request.space
    )
    tables = (
        request.tables
        if request.tables is not None
        else tuple(sorted(all_tables))
    )

    # Create all refresh requests
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

    # Call executor to handle execution
    results = await execution.execute_items(
        items=items,
        operation=_refresh_remote_table_statistics_item,
        max_concurrency=request.max_concurrency,
        classify=_map_refresh_result_to_batch_item_final_status,
    )
    return RefreshRemoteTableStatisticsBatchResult(
        results=results,
        summary=execution.to_summary(),
    )


async def refresh_remote_table_statistics_batch(
    context: CommandContext,
    request: RefreshRemoteTableStatisticsBatchRequest,
) -> RefreshRemoteTableStatisticsBatchResult:
    """
    Refreshes statistics for selected remote tables with concurrency.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (RefreshRemoteTableStatisticsBatchRequest): Input for the
                                                            refreshes.

    Returns:
        RefreshRemoteTableStatisticsBatchResult: Ordered results of the
                                                refreshes.
    """
    total_items = len(request.tables) if request.tables is not None else None
    return await execute_batch(
        context=context,
        command=REFRESH_REMOTE_TABLE_STATISTICS_BATCH_COMMAND_NAME,
        request=request,
        operation=_refresh_remote_table_statistics_batch,
        total_items=total_items,
        result_phase=lambda result: batch_result_phase(result.summary),
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
        "Configure statistics for multiple remote tables with concurrency."
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
        "Refresh statistics for multiple remote tables with concurrency."
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
