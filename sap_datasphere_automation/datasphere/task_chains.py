import asyncio
import csv
from uuid import uuid4

import httpx
import pandas as pd

from sap_datasphere_automation.datasphere.automation import DatasphereAutomation
from sap_datasphere_automation.utils.filehandler import ALL_FILES, settings
from sap_datasphere_automation.utils.logging import logger

# Important URLs from settings
DATASPHERE_URL: str = settings["Setup"]["DATASPHERE_URL"]


class TaskChains(DatasphereAutomation):
    def __init__(self, session: httpx.AsyncClient | None = None):
        if session is not None:
            self.session = session
        else:
            super().__init__()

    async def initialize(self) -> None:
        """
        Initializes the Datasphere session.
        """
        self.session: httpx.AsyncClient = await (
            self.initialize_datasphere_session()
        )

    async def run_task_chains(self, thread_count: int = 1) -> None:
        """
        Starts all tasks chains specified in the task chain run file and waits
        for their completion. The results are saved in the task chain run
        result file.

        Args:
            thread_count (int, optional): Amount of concurrent asynchronous
                                          requests. Default is 1.
        """
        # Read task file
        task_chains_to_start = []
        file_name = ALL_FILES["TASK_CHAIN_RUN"]["absolute_path"]
        with open(file_name, newline="") as file:
            reader = csv.DictReader(
                file,
                fieldnames=ALL_FILES["TASK_CHAIN_RUN"]["columns"],
            )
            task_chains_to_start = list(reader)[1:]

        # Pre-fill results file with values
        with open(
            ALL_FILES["TASK_CHAIN_RUN_RESULT"]["absolute_path"],
            "a",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=ALL_FILES["TASK_CHAIN_RUN_RESULT"]["columns"],
            )
            for task_chain in task_chains_to_start:
                values = {
                    "entity": task_chain["entity"],
                    "space": task_chain["space"],
                    "isCompleted": False,
                    "runtime": None,
                }
                writer.writerow(values)

        # Update headers
        self.session.headers.update(
            {"Accept": "*/*", "x-request-id": str(uuid4()).replace("-", "")}
        )

        async def run_task_chain(task_chain):
            success, log_details = await self._run_task_chain(
                task_chain_name=task_chain["entity"],
                task_chain_space=task_chain["space"],
            )
            runtime = round(log_details.get("runTime", 0) / 1000)

            # Update results file (read in file first, then write the whole
            # file again to update the corresponding row)
            df = pd.read_csv(
                ALL_FILES["TASK_CHAIN_RUN_RESULT"]["absolute_path"]
            )
            df.loc[
                (df["entity"] == task_chain["entity"])
                & (df["space"] == task_chain["space"]),
                "isCompleted",
            ] = success

            # Add runtime only if completed successfully
            if success:
                df.loc[
                    (df["entity"] == task_chain["entity"])
                    & (df["space"] == task_chain["space"]),
                    "runtime",
                ] = runtime
            df.to_csv(
                ALL_FILES["TASK_CHAIN_RUN_RESULT"]["absolute_path"],
                index=False,
            )

        # Start tasks
        await self.run_async_tasks(
            task_chains_to_start, run_task_chain, thread_count
        )

        # Final logging with file path
        file_name = ALL_FILES["TASK_CHAIN_RUN_RESULT"]["absolute_path"]
        logger.info("Results saved to '%s'.", file_name)

        # Function to run a single task chain

    async def _run_task_chain(
        self, task_chain_name: str, task_chain_space: str
    ):
        """
        Starts a task chain and waits for the final result of the execution.

        Args:
            task_chain_name (str): Task chain to start.
            task_chain_space (str): Space of the task chain.
        """
        # Start task chain
        logger.debug(
            "Starting task chain '%s' in space '%s'...",
            task_chain_name,
            task_chain_space,
        )
        url = (
            f"{DATASPHERE_URL}/dwaas-core/tf/"
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
                url=f"{DATASPHERE_URL}/dwaas-core/tf/{task_chain_space}/logs",
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
