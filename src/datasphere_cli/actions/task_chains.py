from typing import cast

from datasphere_api import DatasphereClient

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
        success, log_details = await client.task_chains.run(
            chain["entity"], chain["space"]
        )
        runtime = round(log_details.get("runTime", 0) / 1000)
        update_result_row(
            "TASK_CHAIN_RUN_RESULT",
            {
                "entity": chain["entity"],
                "space": chain["space"],
                "isCompleted": success,
                "runtime": runtime if success else None,
            },
        )

    await run_async_tasks(chains, run_task_chain, thread_count)
    log_results_saved("TASK_CHAIN_RUN_RESULT")
