from pathlib import Path

from datasphere_core import CommandContext
from datasphere_core.models.task_chains import (
    RunTaskChainBatchRequest,
    RunTaskChainBatchResult,
    RunTaskChainRequest,
)

from datasphere_cli.actions.dispatch import dispatch_command
from datasphere_cli.files.records import TaskChainResultRecord
from datasphere_cli.files.storage import (
    initialize_result,
    read_task_csv,
    write_result_csv,
)
from datasphere_cli.logging import logger

_COMMAND = "task_chains.run_batch"


async def run_task_chains_from_file(
    context: CommandContext,
    timeout_seconds: float = 3600.0,
    max_concurrency: int = 4,
    workspace_root: str | Path | None = None,
) -> RunTaskChainBatchResult:
    """Run task chains and write only the final result atomically.

    Core progress contains counters but not result records, so this adapter
    does not fabricate partial checkpoints during a long-running command.

    Args:
        context (CommandContext): Core context with the authenticated client.
        timeout_seconds (float, optional): Maximum runtime for each task chain.
        max_concurrency (int, optional): Maximum concurrent SAP operations.
        workspace_root (str | Path | None, optional): Root for task and result
            files. Uses the default workspace when None.

    Returns:
        RunTaskChainBatchResult: Task-chain execution results.
    """
    initialize_result(_COMMAND, workspace_root)
    records = read_task_csv(_COMMAND, workspace_root)
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
    result = await dispatch_command(
        _COMMAND,
        context,
        request,
        RunTaskChainBatchRequest,
        RunTaskChainBatchResult,
    )
    rows: list[TaskChainResultRecord] = [
        {
            "task_chain": item.chain,
            "space": item.space,
            "status": item.status,
            "sap_status": item.sap_status,
            "log_id": item.log_id,
            "runtime_seconds": item.runtime_seconds,
        }
        for item in result.results
    ]
    path = write_result_csv(_COMMAND, rows, workspace_root)
    logger.info(
        "Task chains: %s succeeded, %s failed, %s timed out.",
        result.summary.succeeded,
        result.summary.failed,
        result.summary.timed_out,
    )
    logger.info("Results saved to '%s'.", path)
    return result
