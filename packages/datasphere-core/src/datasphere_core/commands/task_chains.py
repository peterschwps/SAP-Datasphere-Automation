from typing import Any

from datasphere_api import TaskChainCancelled, TaskChainTimeout

from datasphere_core.context import CommandContext
from datasphere_core.conversion import runtime_to_seconds, to_text
from datasphere_core.definitions import CommandDefinition
from datasphere_core.errors import CommandCancelledError
from datasphere_core.execution import batch_command, command, run_batch
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


@command(RUN_TASK_CHAIN_COMMAND_NAME)
async def run_task_chain(
    context: CommandContext,
    request: RunTaskChainRequest,
) -> RunTaskChainResult:
    """
    Runs one task chain and waits for its result.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (RunTaskChainRequest): Input for the task chain execution.

    Raises:
        CommandCancelledError: If the command was cancelled after the task
                               chain had already started remotely.

    Returns:
        RunTaskChainResult: Result of the task chain run.
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
            log_id=to_text(error.log_id),
        )
    except TaskChainCancelled as error:
        raise CommandCancelledError(
            message=str(error),
            log_id=to_text(error.log_id),
        ) from None

    # Set status
    status: TaskChainStatus
    if success:
        status = TaskChainStatus.COMPLETED
    elif log_details:
        status = TaskChainStatus.FAILED
    else:
        status = TaskChainStatus.START_FAILED

    # Datasphere returns an empty dict when the run never started, so
    # both keys are read defensively. A filled dict always carries them.
    return RunTaskChainResult(
        chain=request.chain,
        space=request.space,
        status=status,
        sap_status=to_text(log_details.get("status")),
        log_id=to_text(log_details.get("logId")),
        runtime_seconds=(
            runtime_to_seconds(log_details) if success else None
        ),
    )


@batch_command(RUN_TASK_CHAIN_BATCH_COMMAND_NAME)
async def run_task_chain_batch(
    context: CommandContext,
    request: RunTaskChainBatchRequest,
) -> RunTaskChainBatchResult:
    """
    Runs multiple task chains with concurrency and waits for their results.

    Args:
        context (CommandContext): Authenticated client and progress callbacks.
        request (RunTaskChainBatchRequest): Input for the task chain executions
                                            with concurrency.

    Raises:
        CommandCancelledError: If the command was cancelled after a task chain
                               had already started remotely.

    Returns:
        RunTaskChainBatchResult: Ordered results of the task chain runs.
    """
    results, summary = await run_batch(
        context=context,
        command=RUN_TASK_CHAIN_BATCH_COMMAND_NAME,
        items=request.requests,
        operation=run_task_chain,
        max_concurrency=request.max_concurrency,
    )
    return RunTaskChainBatchResult(results=results, summary=summary)


# Define all commands
TASK_CHAINS_RUN_COMMAND = CommandDefinition(
    name=RUN_TASK_CHAIN_COMMAND_NAME,
    request_type=RunTaskChainRequest,
    result_type=RunTaskChainResult,
    handler=run_task_chain,
    description="Run a task chain and wait for its result.",
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
    description=(
        "Run multiple task chains with bounded concurrency and wait for their "
        "results."
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
