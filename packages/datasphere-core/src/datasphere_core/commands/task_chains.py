import math
from typing import Any

from datasphere_api import TaskChainCancelled, TaskChainTimeout

from datasphere_core.context import CommandContext
from datasphere_core.definitions import CommandDefinition
from datasphere_core.errors import CommandCancelledError
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
from datasphere_core.models.task_chains import (
    DEFAULT_TASK_CHAIN_TIMEOUT_SECONDS,
    MAXIMUM_TASK_CHAIN_TIMEOUT_SECONDS,
    RunTaskChainBatchRequest,
    RunTaskChainBatchResult,
    RunTaskChainRequest,
    RunTaskChainResult,
    TaskChainStatus,
)

RUN_TASK_CHAIN_COMMAND_NAME = "task_chains.run"
RUN_TASK_CHAIN_BATCH_COMMAND_NAME = "task_chains.run_batch"


def _get_log_status(log_details: dict[str, Any]) -> str | None:
    """
    Reads the status from the task chain log details.

    Args:
        log_details (dict[str, Any]): Log details to inspect.

    Returns:
        str | None: Status if present as a string.
    """
    status = log_details.get("status")
    return status if isinstance(status, str) else None


def _get_log_id(log_details: dict[str, Any]) -> str | None:
    """
    Reads and normalizes a task chain log identifier.

    Args:
        log_details (dict[str, Any]): Log details to inspect.

    Returns:
        str | None: Log ID or None for invalid values.
    """
    log_id = log_details.get("logId")
    if isinstance(log_id, bool) or not isinstance(log_id, (int, str)):
        return None
    return str(log_id)


def _get_runtime_seconds(log_details: dict[str, Any]) -> int | None:
    """
    Converts a millisecond runtime to rounded seconds.

    Args:
        log_details (dict[str, Any]): Log details containing 'runTime'.

    Returns:
        int | None: Rounded runtime in seconds, or None if the key is missing
                    or its value invalid.
    """
    runtime = log_details.get("runTime")
    if (
        not isinstance(runtime, (int, float))
        or isinstance(runtime, bool)
        or not math.isfinite(runtime)
        or runtime < 0
    ):
        return None
    return round(runtime / 1000)


def _map_result_to_command_progress_phase(
        result: RunTaskChainResult
    ) -> CommandProgressPhase:
    """
    Maps a task chain result to its lifecycle progress phase.

    Args:
        result (RunTaskChainResult): Result to classify.

    Returns:
        CommandProgressPhase: Corresponding command progress phase.
    """
    if result.status is TaskChainStatus.COMPLETED:
        return CommandProgressPhase.COMPLETED
    if result.status is TaskChainStatus.TIMED_OUT:
        return CommandProgressPhase.TIMED_OUT
    return CommandProgressPhase.FAILED


def _map_result_to_batch_item_final_status(
        result: RunTaskChainResult
    ) -> BatchItemFinalStatus:
    """
    Maps a task chain result of a batch run to its batch item status.

    Args:
        result (RunTaskChainResult): Result to classify.

    Returns:
        BatchItemFinalStatus: Corresponding batch item status.
    """
    if result.status is TaskChainStatus.COMPLETED:
        return BatchItemFinalStatus.SUCCEEDED
    if result.status is TaskChainStatus.TIMED_OUT:
        return BatchItemFinalStatus.TIMED_OUT
    return BatchItemFinalStatus.FAILED


async def _run_task_chain(
    context: CommandContext,
    request: RunTaskChainRequest,
) -> RunTaskChainResult:
    """
    Runs one task chain.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (RunTaskChainRequest): Input for the task chain execution.

    Returns:
        RunTaskChainResult: Result of the task chain run.

    Raises:
        CommandCancelledError: If the command itself was cancelled.
    """
    # Execute task chain
    try:
        success, log_details = await context.client.task_chains.run(
            request.chain,
            request.space,
            timeout_seconds=request.timeout_seconds,
        )
    except TaskChainTimeout as error:
        return RunTaskChainResult(
            chain=request.chain,
            space=request.space,
            status=TaskChainStatus.TIMED_OUT,
            log_id=_get_log_id({"logId": error.log_id}),
        )
    except TaskChainCancelled as error:
        raise CommandCancelledError(str(error),
            log_id=str(error.log_id),
        ) from None

    # Set status
    status: TaskChainStatus
    if success:
        status = TaskChainStatus.COMPLETED
    elif log_details:
        status = TaskChainStatus.FAILED
    else:
        status = TaskChainStatus.START_FAILED

    return RunTaskChainResult(
        chain=request.chain,
        space=request.space,
        status=status,
        sap_status=_get_log_status(log_details),
        log_id=_get_log_id(log_details),
        runtime_seconds=(
            _get_runtime_seconds(log_details) if success else None
        ),
    )


async def run_task_chain(
    context: CommandContext,
    request: RunTaskChainRequest,
) -> RunTaskChainResult:
    """
    Runs one task chain.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (RunTaskChainRequest): Input for the task chain execution.

    Returns:
        RunTaskChainResult: Result of the task chain run.

    Raises:
        CommandCancelledError: If the command itself was cancelled.
    """
    return await execute_command(
        context=context,
        command=RUN_TASK_CHAIN_COMMAND_NAME,
        request=request,
        operation=_run_task_chain,
        result_phase=_map_result_to_command_progress_phase,
    )


async def _run_task_chain_batch(
    execution: BatchExecution,
    request: RunTaskChainBatchRequest,
) -> RunTaskChainBatchResult:
    """
    Runs all requested task chains with concurrency.

    Args:
        execution (BatchExecution): Runtime state of the batch execution.
        request (RunTaskChainBatchRequest): Input for the task chain
                                            executions with concurrency.

    Returns:
        RunTaskChainBatchResult: Ordered results of the task chain runs.

    """
    results = await execution.execute_items(
        items=request.requests,
        operation=_run_task_chain,
        max_concurrency=request.max_concurrency,
        classify=_map_result_to_batch_item_final_status,
    )
    return RunTaskChainBatchResult(
        results=results,
        summary=execution.to_summary(),
    )


async def run_task_chain_batch(
    context: CommandContext,
    request: RunTaskChainBatchRequest,
) -> RunTaskChainBatchResult:
    """
    Runs multiple task chains with concurrency.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (RunTaskChainBatchRequest): Input for the task chain
                                            executions with concurrency.

    Returns:
        RunTaskChainBatchResult: Ordered results of the task chain runs.

    Raises:
        CommandCancelledError: If the command itself was cancelled.
    """

    return await execute_batch(
        context=context,
        command=RUN_TASK_CHAIN_BATCH_COMMAND_NAME,
        request=request,
        operation=_run_task_chain_batch,
        total_items=len(request.requests),
        result_phase=lambda result: batch_result_phase(result.summary),
    )


# Define all commands
TASK_CHAINS_RUN_COMMAND = CommandDefinition(
    name=RUN_TASK_CHAIN_COMMAND_NAME,
    request_type=RunTaskChainRequest,
    result_type=RunTaskChainResult,
    handler=run_task_chain,
    cli_description="Run a task chain and wait for its result.",
    mcp_description=(
        "Run a SAP Datasphere task chain and wait for its result."
    ),
    default_timeout_seconds=DEFAULT_TASK_CHAIN_TIMEOUT_SECONDS,
    maximum_timeout_seconds=MAXIMUM_TASK_CHAIN_TIMEOUT_SECONDS,
    read_only=False,
    destructive=True,
    idempotent=False,
    expose_to_mcp=True,
)

TASK_CHAINS_RUN_BATCH_COMMAND = CommandDefinition(
    name=RUN_TASK_CHAIN_BATCH_COMMAND_NAME,
    request_type=RunTaskChainBatchRequest,
    result_type=RunTaskChainBatchResult,
    handler=run_task_chain_batch,
    cli_description="Run task chains with bounded concurrency.",
    mcp_description=(
        "Run SAP Datasphere task chains with bounded concurrency and return "
        "ordered per-item results."
    ),
    default_timeout_seconds=DEFAULT_TASK_CHAIN_TIMEOUT_SECONDS,
    maximum_timeout_seconds=MAXIMUM_TASK_CHAIN_TIMEOUT_SECONDS,
    read_only=False,
    destructive=True,
    idempotent=False,
    expose_to_mcp=False,
)

# Gather all commands (to import to registry)
TASK_CHAINS_COMMAND_DEFINITIONS: tuple[CommandDefinition[Any, Any], ...] = (
    TASK_CHAINS_RUN_COMMAND,
    TASK_CHAINS_RUN_BATCH_COMMAND,
)
