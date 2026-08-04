import logging
from dataclasses import replace
from pathlib import Path

from datasphere_core import CommandContext
from datasphere_core.commands.task_chains import run_task_chain_batch
from datasphere_core.models.common import BatchItemResult
from datasphere_core.models.task_chains import (
    RunTaskChainBatchRequest,
    RunTaskChainBatchResult,
    RunTaskChainRequest,
    RunTaskChainResult,
    TaskChainStatus,
)

from datasphere_cli.files.records import TaskChainResultRecord
from datasphere_cli.files.storage import (
    initialize_result,
    read_task_csv,
    write_result_csv,
)
from datasphere_cli.logging import logger

_COMMAND = "task_chains.run_batch"

# Log level and message per status. A start the tenant refused is left out:
# the Core already reports why the request failed.
_CHAIN_MESSAGES = {
    TaskChainStatus.COMPLETED: (
        logging.INFO,
        "Task chain '%s' completed.",
    ),
    TaskChainStatus.FAILED: (
        logging.ERROR,
        "Task chain '%s' failed.",
    ),
    TaskChainStatus.TIMED_OUT: (
        logging.ERROR,
        "Task chain '%s' timed out. It may still be running.",
    ),
}


async def _report_chain(update: BatchItemResult) -> None:
    """
    Logs the outcome of one task chain as soon as its run is done.

    Args:
        update (BatchItemResult): Result of one completed task chain.

    Raises:
        TypeError: If the item carries an unexpected result type.
    """
    if not isinstance(update.result, RunTaskChainResult):
        raise TypeError("Task chain item has an unexpected result.")

    item = update.result
    message = _CHAIN_MESSAGES.get(item.status)
    if message is None:
        return
    logger.log(message[0], message[1], item.chain)


async def run_task_chains_from_file(
    context: CommandContext,
    timeout_seconds: float = 3600.0,
    max_concurrency: int = 4,
    workspace_root: str | Path | None = None,
) -> RunTaskChainBatchResult:
    """
    Runs the task chains listed in the task file. Writes the result once
    the batch completed.

    Args:
        context (CommandContext): Context with the authenticated client.
        timeout_seconds (float, optional): Maximum runtime for each task chain.
                                           Defaults to 3600.0 seconds.
        max_concurrency (int, optional): Maximum amount of concurrent
                                         operations. Defaults to 4.
        workspace_root (str | Path | None, optional): Root for task and
                                                      result files. Uses the
                                                      default workspace when
                                                      None. Defaults to None.

    Returns:
        RunTaskChainBatchResult: Task chain execution results.
    """
    initialize_result(_COMMAND, workspace_root)
    records = read_task_csv(_COMMAND, workspace_root)

    # Build request from task file
    # The only task file whose column name differs from the request field
    request = RunTaskChainBatchRequest(
        requests=tuple(
            RunTaskChainRequest(
                chain=record["task_chain"],
                space=record["space"],
                timeout_seconds=timeout_seconds,
            )
            for record in records
        ),
        max_concurrency=max_concurrency,
    )
    # Report every chain as soon as it is done
    result = await run_task_chain_batch(
        replace(context, batch_item_result_callback=_report_chain),
        request,
    )
    rows: list[TaskChainResultRecord] = [
        {
            "task_chain": item.chain,
            "space": item.space,
            "status": item.status,
            "log_status": item.log_status,
            "log_id": item.log_id,
            "runtime_seconds": item.runtime_seconds,
        }
        for item in result.results
    ]
    path = write_result_csv(_COMMAND, rows, workspace_root)

    # Log outcome counts
    # TaskChainStatus has no skipped outcome, so that counter stays out
    logger.info(
        "Task chains: %s succeeded, %s failed, %s timed out.",
        result.summary.succeeded,
        result.summary.failed,
        result.summary.timed_out,
    )
    logger.info("Results saved to '%s'.", path)
    return result
