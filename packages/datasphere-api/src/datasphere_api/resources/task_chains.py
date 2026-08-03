import logging
from uuid import uuid4

from datasphere_api.resources.base import BaseResource

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
