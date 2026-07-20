from typing import Any

from datasphere_api import TaskChainCancelled, TaskChainTimeout

from datasphere_core.context import CommandContext
from datasphere_core.errors import CommandCancelledError, CommandTimeoutError
from datasphere_core.models import (
    CommandProgress,
    StartTaskChainRequest,
    StartTaskChainResult,
)

COMMAND_NAME = "taskchain.start"


def get_sap_status(log_details: dict[str, Any]) -> str | None:
    """
    Fetches the status from the logs of a task chain execution.

    Args:
        log_details (dict[str, Any]): Log details containing the status
                                      information.

    Returns:
        str | None: Status of the task chain execution. None if the status
                    could not be retrieved.
    """
    status = log_details.get("status")
    return status if isinstance(status, str) else None


def get_runtime_seconds(log_details: dict[str, Any]) -> int | None:
    """
    Fetches the current runtime from the logs of a task chain execution.

    Args:
        log_details (dict[str, Any]): Log details containing the runtime
                                      information.

    Returns:
        int | None: Runtime in seconds. None if the runtime could not be
                    retrieved.
    """
    runtime = log_details.get("runTime")
    if not isinstance(runtime, (int, float)) or isinstance(runtime, bool):
        return None
    return round(runtime / 1000)


async def start_task_chain(
    context: CommandContext,
    request: StartTaskChainRequest,
) -> StartTaskChainResult:
    """
    Starts one task chain and waits for its terminal status.

    Args:
        context: Authenticated command dependencies.
        request: Request with required parameters (chain, space, timeout).

    Raises:
        CommandTimeoutError: If the configured timeout is exceeded.

    Returns:
        Result with normalized command and SAP status information.
    """
    await context.report(
        CommandProgress(
            command=COMMAND_NAME,
            phase="started",
        )
    )

    # Start task chain execution and wait for it to finish
    try:
        success, log_details = await context.client.task_chains.run(
            request.chain,
            request.space,
            timeout_seconds=request.timeout_seconds,
        )

    except TaskChainTimeout as error:
        await context.report(
            CommandProgress(
                command=COMMAND_NAME,
                phase="timed_out",
            )
        )
        raise CommandTimeoutError(
            str(error),
            operation_id=str(error.log_id),
        ) from None

    except TaskChainCancelled as error:
        await context.report(
            CommandProgress(
                command=COMMAND_NAME,
                phase="cancelled",
                message=str(error),
            )
        )
        raise CommandCancelledError(
            str(error),
            operation_id=str(error.log_id),
        ) from None

    except Exception:
        await context.report(
            CommandProgress(
                command=COMMAND_NAME,
                phase="failed",
            )
        )
        raise

    # Check for success and build the result object
    if success:
        result = StartTaskChainResult(
            chain=request.chain,
            space=request.space,
            status="completed",
            sap_status=get_sap_status(log_details),
            runtime_seconds=get_runtime_seconds(log_details),
        )
        phase = "completed"
    else:
        result = StartTaskChainResult(
            chain=request.chain,
            space=request.space,
            status="failed" if log_details else "start_failed",
            sap_status=get_sap_status(log_details),
            runtime_seconds=None,
        )
        phase = "failed"

    await context.report(
        CommandProgress(
            command=COMMAND_NAME,
            phase=phase,
        )
    )
    return result
