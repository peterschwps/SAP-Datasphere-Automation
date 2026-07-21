import asyncio
import logging
from uuid import uuid4

from datasphere_api.exceptions import TaskChainCancelled, TaskChainTimeout
from datasphere_api.resources.base import BaseResource, validate_timeout

logger = logging.getLogger(__name__)


class TaskChains(BaseResource):
    async def start(self, chain: str, space: str) -> int | None:
        """
        Starts a task chain. Does not wait for the result.

        Args:
            chain (str): Name of the task chain.
            space (str): Space of the task chain.

        Returns:
            int | None: Log ID of the started run or None if the start failed.
        """
        response = await self.session.post(
            url=(
                f"{self._base_url}/dwaas-core/tf/"
                f"{space}/taskchains/"
                f"{chain}/start"
            ),
            json={
                "objectId": chain,
                "activity": "RUN_CHAIN",
                "applicationId": "TASK_CHAINS",
                "spaceId": space,
            },
            headers={
                "Accept": "*/*",
                "x-request-id": str(uuid4()).replace("-", ""),
            },
        )
        if response.status_code != 202:
            logger.error(
                "Error starting task chain '%s' in space '%s'. Skipping...",
                chain,
                space,
            )
            return None
        return response.json()["logId"]

    async def get_log(self, log_id: int, space: str) -> dict:
        """
        Returns the log details of a task chain run.

        Args:
            log_id (int): Log ID of the run.
            space (str): Space of the task chain.

        Returns:
            dict: Log details with 'status' and 'runTime'.
        """
        response = await self.session.get(
            url=f"{self._base_url}/dwaas-core/tf/{space}/logs",
            params={"taskLogId": log_id},
            headers={
                "Accept": "*/*",
                "x-request-id": str(uuid4()).replace("-", ""),
            },
        )
        return response.json()[0]

    async def run(
        self,
        chain: str,
        space: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, dict]:
        """
        Starts a task chain and waits for the final result of the execution.
        Polls the log every second until the chain completes or fails.

        Args:
            chain (str): Name of the task chain.
            space (str): Space of the task chain.
            timeout_seconds (float | None, optional): Maximum polling duration.
                                                      None if no timeout should
                                                      be used.

        Raises:
            TaskChainTimeout: If a started run exceeds the timeout.
            ValueError: If timeout_seconds is not positive and finite, or is
                        a boolean.

        Returns:
            tuple[bool, dict]: True if the run completed successfully,
                               otherwise False. Dict with log details.
        """
        validate_timeout(timeout_seconds)

        # Start task chain
        logger.debug(
            "Starting task chain '%s' in space '%s'...",
            chain,
            space,
        )
        log_id = await self.start(chain, space)
        if log_id is None:
            return False, {}

        # Wait for results
        try:
            async with asyncio.timeout(timeout_seconds):
                while True:
                    log_details = await self.get_log(log_id, space)
                    log_details["logId"] = log_id
                    latest_status = log_details["status"]

                    if latest_status == "COMPLETED":
                        logger.info(
                            "Completed run for task chain '%s' in '%s'.",
                            chain,
                            space,
                        )
                        return True, log_details

                    if latest_status != "RUNNING":
                        logger.error(
                            "Error running task chain '%s' in '%s'.",
                            chain,
                            space,
                        )
                        return False, log_details

                    milliseconds = log_details["runTime"]
                    hours, remainder = divmod(milliseconds, 3600000)
                    minutes, seconds = divmod(remainder, 60000)
                    seconds, milliseconds = divmod(seconds, 1000)
                    logger.debug(
                        "Waiting for results for task chain '%s' in '%s'. "
                        "Current runtime: %02d:%02d:%02d.",
                        chain,
                        space,
                        hours,
                        minutes,
                        seconds,
                    )
                    await asyncio.sleep(1)
        except TimeoutError:
            raise TaskChainTimeout(chain, space, log_id) from None
        except asyncio.CancelledError:
            raise TaskChainCancelled(chain, space, log_id) from None
