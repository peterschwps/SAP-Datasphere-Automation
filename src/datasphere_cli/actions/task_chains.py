from typing import cast

from datasphere_api import DatasphereClient
from datasphere_core import (
    CommandContext,
    StartTaskChainRequest,
    start_task_chain,
)

from datasphere_cli.actions.files import (
    log_results_saved,
    prefill_result_rows,
    read_task_csv,
    update_result_row,
)
from datasphere_cli.models import ViewRef
from datasphere_cli.utils.concurrency import run_async_tasks


async def run_task_chains(
    client: DatasphereClient,
    thread_count: int,
) -> None:
    """
    Runs all task chains from the task file and saves the results.

    Args:
        client (DatasphereClient): Authenticated client.
        thread_count (int): Amount of concurrent asynchronous requests.
    """
    chains = cast(list[ViewRef], read_task_csv("TASK_CHAIN_RUN"))
    prefill_result_rows(
        "TASK_CHAIN_RUN_RESULT",
        [
            {
                "entity": chain["entity"],
                "space": chain["space"],
                "isCompleted": False,
                "runtime": None,
            }
            for chain in chains
        ],
    )

    # Function to run a task chain and update its result row
    async def run_task_chain(chain: ViewRef) -> None:
        result = await start_task_chain(
            CommandContext(client=client),
            StartTaskChainRequest(
                chain=chain["entity"],
                space=chain["space"],
                timeout_seconds=None,
            ),
        )
        update_result_row(
            "TASK_CHAIN_RUN_RESULT",
            {
                "entity": chain["entity"],
                "space": chain["space"],
                "isCompleted": result.status == "completed",
                "runtime": result.runtime_seconds,
            },
        )

    await run_async_tasks(chains, run_task_chain, thread_count)
    log_results_saved("TASK_CHAIN_RUN_RESULT")
