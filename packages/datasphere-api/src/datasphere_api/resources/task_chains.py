import asyncio
import logging
from uuid import uuid4

from datasphere_api.resources.base import BaseResource

logger = logging.getLogger(__name__)


class TaskChains(BaseResource):

    # Endpoint methods (one HTTP call each)

    async def start(self, chain: str, space: str) -> int | None:
        """
        Starts a task chain.

        Args:
            chain (str): Name of the task chain.
            space (str): Space of the task chain.

        Returns:
            int | None: Log ID of the started run, or None if the start
                        failed.
        """
        self.session.headers.update(
            {"Accept": "*/*", "x-request-id": str(uuid4()).replace("-", "")}
        )
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
        self.session.headers.update(
            {"x-request-id": str(uuid4()).replace("-", "")}
        )
        response = await self.session.get(
            url=f"{self._base_url}/dwaas-core/tf/{space}/logs",
            params={"taskLogId": log_id},
        )
        return response.json()[0]

    # Single-chain workflow

    async def run(self, chain: str, space: str) -> tuple[bool, dict]:
        """
        Starts a task chain and waits for the final result of the
        execution.

        Args:
            chain (str): Name of the task chain.
            space (str): Space of the task chain.

        Returns:
            tuple[bool, dict]: True if the run completed successfully,
                               otherwise False. Dict with log details.
        """
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
        log_details = {}
        while True:
            log_details = await self.get_log(log_id, space)
            latest_status = log_details["status"]

            if latest_status == "COMPLETED":
                logger.info(
                    "Completed run for task chain '%s' in '%s'.",
                    chain,
                    space,
                )
                return True, log_details

            elif latest_status != "RUNNING":
                logger.error(
                    "Error running task chain '%s' in '%s'.",
                    chain,
                    space,
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
                    chain,
                    space,
                    hours,
                    minutes,
                    seconds,
                )
                await asyncio.sleep(1)
