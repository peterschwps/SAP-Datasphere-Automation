import asyncio
import logging
from collections.abc import Callable
from uuid import uuid4

from datasphere_api.models import TaskChainRunResult, ViewRef
from datasphere_api.resources.base import BaseResource

logger = logging.getLogger(__name__)


class TaskChains(BaseResource):

    async def run(
        self,
        chains: list[ViewRef],
        thread_count: int = 1,
        on_result: Callable[[TaskChainRunResult], None] | None = None,
    ) -> list[TaskChainRunResult]:
        """
        Starts the given task chains and waits for their completion.

        Args:
            chains (list[ViewRef]): Task chains to run.
            thread_count (int, optional): Amount of concurrent
                                          asynchronous requests.
                                          Default is 1.
            on_result (Callable | None, optional): Callback that is
                                                   invoked with each
                                                   result as soon as it
                                                   is available (e.g. to
                                                   save results
                                                   incrementally during
                                                   long runs).
                                                   Defaults to None.

        Returns:
            list[TaskChainRunResult]: Outcome for each task chain.
        """
        # Update headers
        self.session.headers.update(
            {"Accept": "*/*", "x-request-id": str(uuid4()).replace("-", "")}
        )
        results: list[TaskChainRunResult] = []

        # Function to run a single task chain
        async def run_one(chain) -> None:
            success, log_details = await self.run_single(
                task_chain_name=chain["entity"],
                task_chain_space=chain["space"],
            )
            runtime = round(log_details.get("runTime", 0) / 1000)

            # Save result and notify caller
            result: TaskChainRunResult = {
                "entity": chain["entity"],
                "space": chain["space"],
                "isCompleted": success,
                "runtime": runtime if success else None,
            }
            results.append(result)
            if on_result is not None:
                on_result(result)

        # Start tasks
        await self._client.run_async_tasks(
            chains, run_one, thread_count
        )
        return results

    async def run_single(
        self, task_chain_name: str, task_chain_space: str
    ) -> tuple[bool, dict]:
        """
        Starts a task chain and waits for the final result of the
        execution.

        Args:
            task_chain_name (str): Task chain to start.
            task_chain_space (str): Space of the task chain.

        Returns:
            tuple[bool, dict]: True if the run completed successfully,
                               otherwise False. Dict with log details.
        """
        # Start task chain
        logger.debug(
            "Starting task chain '%s' in space '%s'...",
            task_chain_name,
            task_chain_space,
        )
        url = (
            f"{self._base_url}/dwaas-core/tf/"
            f"{task_chain_space}/taskchains/"
            f"{task_chain_name}/start"
        )
        body = {
            "objectId": task_chain_name,
            "activity": "RUN_CHAIN",
            "applicationId": "TASK_CHAINS",
            "spaceId": task_chain_space,
        }
        response = await self.session.post(url=url, json=body)

        if response.status_code != 202:
            logger.error(
                "Error starting task chain '%s' in space '%s'. Skipping...",
                task_chain_name,
                task_chain_space,
            )
            return False, {}
        log_id = response.json()["logId"]

        # Function to fetch log details
        async def fetch_log_details() -> dict:
            self.session.headers.update(
                {"x-request-id": str(uuid4()).replace("-", "")}
            )
            response = await self.session.get(
                url=(
                    f"{self._base_url}/dwaas-core/tf"
                    f"/{task_chain_space}/logs"
                ),
                params={"taskLogId": log_id},
            )
            return response.json()[0]

        # Wait for results
        log_details = {}
        while True:
            log_details = await fetch_log_details()
            latest_status = log_details["status"]

            if latest_status == "COMPLETED":
                logger.info(
                    "Completed run for task chain '%s' in '%s'.",
                    task_chain_name,
                    task_chain_space,
                )
                return True, log_details

            elif latest_status == "FAILED" or (
                latest_status != "COMPLETED" and latest_status != "RUNNING"
            ):
                logger.error(
                    "Error running task chain '%s' in '%s'.",
                    task_chain_name,
                    task_chain_space,
                )
                return False, log_details

            else:
                # Convert runtime to readable format and print to console
                milliseconds = log_details["runTime"]
                hours, remainder = divmod(milliseconds, 3600000)
                minutes, seconds = divmod(remainder, 60000)
                seconds, milliseconds = divmod(seconds, 1000)
                logger.debug(
                    "Waiting for results for task chain '%s' in '%s'. "
                    "Current runtime: %02d:%02d:%02d.",
                    task_chain_name,
                    task_chain_space,
                    hours,
                    minutes,
                    seconds,
                )
                await asyncio.sleep(1)
