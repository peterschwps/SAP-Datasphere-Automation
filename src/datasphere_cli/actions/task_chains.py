from datasphere_api import DatasphereClient

from datasphere_cli.models import TaskRow
from datasphere_cli.utils.concurrency import run_async_tasks
from datasphere_cli.utils.runs import Run, read_tasks


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
    chains = read_tasks()
    if not chains:
        return
    run = Run("run-task-chains")
    run.prefill_results(
        [
            {
                "entity": chain["entity"],
                "space": chain["space"],
                "success": False,
                "detail": "",
                "runtime": None,
            }
            for chain in chains
        ]
    )

    # Function to run a task chain and update its result row
    async def run_task_chain(chain: TaskRow) -> None:
        success, log_details = await client.task_chains.run(
            chain["entity"], chain["space"]
        )
        runtime = round(log_details.get("runTime", 0) / 1000)
        run.update_result(
            {
                "entity": chain["entity"],
                "space": chain["space"],
                "success": success,
                "runtime": runtime if success else None,
            }
        )

    await run_async_tasks(chains, run_task_chain, thread_count)
    run.log_saved()
